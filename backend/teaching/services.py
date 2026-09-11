import csv
import io
from datetime import date
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Max, Q, F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from courses.models import Course, Enrollment, Material
from studio.models import Release
from learning.models import BlockProgress, BlockReview
from learning.views import scoped_records
from learning.rules import zone
from learning.services import lock_user
from access.services import audit
from .models import StudyGroup, GroupMember, Assignment, AssignmentStudent, Notice, ReviewEvent


def visible_courses(user):
    if not user.can_manage_courses:
        raise PermissionDenied
    qs = Course.objects.filter(status='published')
    return qs if user.is_platform_admin else qs.filter(created_by=user)


def visible_groups(user):
    if not user.can_manage_courses:
        raise PermissionDenied
    return StudyGroup.objects.all() if user.is_platform_admin else StudyGroup.objects.filter(owner=user)


def ensure_target(assignment, user):
    old = AssignmentStudent.objects.filter(assignment=assignment, user=user).first()
    if old:
        return old
    release = Release.objects.filter(course=assignment.course).first()
    enrollment = Enrollment.objects.filter(user=user, course__studio_release__draft_id=release.draft_id).order_by('id').first() if release else None
    if not enrollment:
        enrollment, _ = Enrollment.objects.get_or_create(user=user, course=assignment.course)
    item = AssignmentStudent.objects.create(assignment=assignment, user=user, enrollment=enrollment)
    Notice.objects.get_or_create(user=user, key=f'assignment:{assignment.pk}', defaults={'text':f'Назначен курс «{enrollment.course.title}» · {assignment.group.title}'[:240]})
    return item


@transaction.atomic
def change_group(user, pk, action, data):
    StudyGroup.objects.filter(pk=pk).update(archived=F('archived'))
    group = get_object_or_404(visible_groups(user).select_for_update(), pk=pk)
    if action == 'archive':
        group.archived = not group.archived
        group.save(update_fields=['archived'])
    elif group.archived:
        raise ValidationError('Сначала восстановите группу из архива.')
    elif action == 'rename':
        title, description = data.get('title','').strip(), data.get('description','').strip()
        if not 1 <= len(title) <= 100 or len(description) > 1000:
            raise ValidationError('Название — до 100, описание — до 1000 символов.')
        if StudyGroup.objects.filter(owner=group.owner, title=title).exclude(pk=pk).exists():
            raise ValidationError('У вас уже есть группа с таким названием.')
        group.title, group.description = title, description
        group.save(update_fields=['title','description'])
    elif action in ('add','remove'):
        try:
            person_id = int(data.get('user'))
        except (ValueError, TypeError):
            raise ValidationError('Выберите студента.')
        person = get_object_or_404(get_user_model(), pk=person_id, role='student', is_superuser=False)
        if action == 'add':
            if not person.is_active:
                raise ValidationError('Этот аккаунт заблокирован.')
            if group.members.count() >= 300:
                raise ValidationError('В группе уже 300 студентов.')
            lock_user(person)
            GroupMember.objects.get_or_create(group=group, user=person)
            for assignment in group.assignments.select_related('course','group'):
                ensure_target(assignment, person)
        else:
            GroupMember.objects.filter(group=group, user=person).delete()
    elif action == 'assign':
        try:
            course_id = int(data.get('course'))
            due = date.fromisoformat(data['due_date']) if data.get('due_date') else None
        except (ValueError, TypeError):
            raise ValidationError('Проверьте курс и срок.')
        course = get_object_or_404(visible_courses(user), pk=course_id, is_listed=True)
        if not group.owner.is_platform_admin and course.created_by_id != group.owner_id:
            raise ValidationError('Группе можно назначить курс её преподавателя. Для другого курса создайте отдельную группу.')
        release = Release.objects.filter(course=course).first()
        existing = group.assignments.filter(course__studio_release__draft_id=release.draft_id).first() if release else group.assignments.filter(course=course).first()
        if existing:
            raise ValidationError('Этот курс уже назначен группе. Срок можно изменить в карточке назначения.')
        assignment = Assignment.objects.create(group=group, course=course, due_date=due)
        for person in get_user_model().objects.filter(study_memberships__group=group, is_active=True).order_by('id'):
            lock_user(person)
            ensure_target(assignment, person)
    elif action == 'deadline':
        assignment = get_object_or_404(Assignment, pk=data.get('assignment'), group=group)
        try:
            assignment.due_date = date.fromisoformat(data['due_date']) if data.get('due_date') else None
        except ValueError:
            raise ValidationError('Проверьте дату.')
        assignment.save(update_fields=['due_date'])
    else:
        raise ValidationError('Неизвестное действие.')
    audit('Учебная группа изменена', actor=user, detail=f'Группа {group.pk}; {action}')
    return group


def filtered(user, params):
    courses, groups = visible_courses(user), visible_groups(user)
    enrollments = Enrollment.objects.filter(course__in=courses, user__role='student', user__is_superuser=False)
    for key in ('course', 'group'):
        value = params.get(key,'')
        if value:
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValidationError('Неверный фильтр.')
            if key == 'course':
                chosen = get_object_or_404(courses, pk=value)
                enrollments = enrollments.filter(course=chosen)
                courses = courses.filter(pk=value)
            else:
                chosen = get_object_or_404(groups, pk=value)
                enrollments = enrollments.filter(user__study_memberships__group=chosen)
    search = params.get('q','').strip()[:100]
    if search:
        enrollments = enrollments.filter(user__username__icontains=search)
    return courses, enrollments.distinct()


def report_rows(user, params):
    courses, enrollments = filtered(user, params)
    if enrollments.count() > 10000:
        raise ValidationError('В отчёте больше 10 000 строк. Выберите группу или курс.')
    pairs = list(enrollments.select_related('user','course').order_by('user__username','course__title','id'))
    user_ids = {e.user_id for e in pairs}
    stats = scoped_records(courses).filter(user_id__in=user_ids).values('user_id','material__lesson__module__course_id').annotate(
        total=Count('id'), positive=Count('id',filter=Q(effective='positive')), negative=Count('id',filter=Q(effective='negative')),
        unknown=Count('id',filter=Q(effective='unknown')), reviewed=Count('id',filter=Q(review__isnull=False)), completed=Max('completed_at'))
    by_pair = {(s['user_id'],s['material__lesson__module__course_id']):s for s in stats}
    blocks = Material.objects.filter(lesson__module__course__in=courses, lesson__is_active=True, attachment_of__isnull=True).filter(~Q(kind='code') | Q(practice_task__isnull=False))
    totals = dict(blocks.values('lesson__module__course_id').annotate(n=Count('id')).values_list('lesson__module__course_id','n'))
    rows = []
    for e in pairs:
        s = by_pair.get((e.user_id,e.course_id),{})
        positive, negative = s.get('positive',0), s.get('negative',0)
        percent, color = zone(negative, positive+negative)
        progress = e.progress_percent
        state = 'done' if progress == 100 else 'new' if not s.get('total') else 'active'
        if params.get('state') and params['state'] != state:
            continue
        if params.get('zone') and params['zone'] != color:
            continue
        rows.append({'user_id':e.user_id, 'name':e.user.username, 'active':e.user.is_active, 'year':e.user.study_year,
            'course_id':e.course_id, 'course':e.course.title, 'progress':progress, 'blocks':s.get('total',0), 'total':totals.get(e.course_id,0),
            'positive':positive, 'negative':negative, 'unknown':s.get('unknown',0), 'reviewed':s.get('reviewed',0),
            'percent':percent, 'zone':color, 'state':state, 'last':s['completed'].isoformat() if s.get('completed') else None})
    return rows


def export_csv(rows):
    def safe(value):
        value = '' if value is None else str(value)
        if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')):
            return "'" + value
        return value
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter=';')
    writer.writerow(['Никнейм','Курс','ID курса','Прогресс %','Баллы / блоки','Всего блоков','Положительные','Отрицательные','Нет данных','Доля отрицательных %','Зона','Проверено преподавателем','Последний завершённый блок'])
    for r in rows:
        writer.writerow([safe(r[k]) for k in ['name','course','course_id','progress','blocks','total','positive','negative','unknown','percent','zone','reviewed','last']])
    response = HttpResponse('\ufeff'+stream.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="ib-report.csv"'
    return response


@transaction.atomic
def record_review(actor, progress, value, note):
    lock_user(progress.user)
    progress = BlockProgress.objects.select_related('review').get(pk=progress.pk)
    before = progress.effective_verdict
    after = progress.verdict if value == 'reset' else value
    ReviewEvent.objects.create(progress=progress, reviewer=actor, before=before, after=after, action=value, note=note)
    if value == 'reset':
        BlockReview.objects.filter(progress=progress).delete()
    else:
        BlockReview.objects.update_or_create(progress=progress, defaults={'reviewer':actor,'verdict':value,'note':note})
    audit('Проверка прохождения блока', actor=actor, subject=progress.user, detail=f'Блок {progress.material_id}, отметка {value}. {note}')
