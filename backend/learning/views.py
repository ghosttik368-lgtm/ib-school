from functools import wraps
import math
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Case, When, F, CharField
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from courses.models import Course, Direction, Enrollment, Lesson, Material, Quiz
from access.services import audit
from .models import BlockProgress, BlockReview
from .services import authorize, open_block, complete_information, submit_test, course_blocks, lock_user
from .rules import zone


def manager(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.can_manage_courses:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def load_material(user, pk):
    material = get_object_or_404(Material.objects.select_related('lesson__module__course'), pk=pk, attachment_of__isnull=True)
    authorize(user, material, practice=True)
    return material


def seek_time(request):
    try:
        value = float(request.GET.get('t', request.POST.get('t', '')))
        return value if math.isfinite(value) and 0 <= value <= 7200 else None
    except (TypeError, ValueError):
        return None


@login_required
@never_cache
@require_GET
def lesson_detail(request, lesson_id):
    lesson = get_object_or_404(Lesson.objects.select_related('module__course'), pk=lesson_id, is_active=True, module__course__status='published')
    course = lesson.module.course
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    # Only titles are sent here. Opening the lesson must not expose every block.
    materials = list(lesson.materials.filter(attachment_of__isnull=True).only('id', 'title', 'kind', 'order', 'lesson_id'))
    completed = set(BlockProgress.objects.filter(user=request.user, material__lesson=lesson, completed_at__isnull=False).values_list('material_id', flat=True))
    for material in materials:
        material.done = material.pk in completed
    return render(request, 'learning/lesson.html', {'lesson': lesson, 'course': course, 'enrollment': enrollment, 'materials': materials, 'active_section': 'library'})


@login_required
@never_cache
@require_POST
def start(request, pk):
    material = load_material(request.user, pk)
    if material.kind == 'code' and not hasattr(material, 'practice_task'):
        return HttpResponse('Для этого старого блока ещё не настроена задача. Обратитесь к преподавателю.', status=409)
    open_block(request.user, material, practice=True)
    from practice.models import Workspace
    ws, _ = Workspace.objects.get_or_create(user=request.user, material=material, defaults={'code':getattr(getattr(material,'practice_task',None),'starter','')})
    ws.save(update_fields=['touched_at'])
    seek = seek_time(request)
    if material.kind == 'video' and seek is not None:
        return redirect(reverse('learning:block', args=[pk]) + f'?t={seek:.3f}')
    return redirect('learning:block', pk=pk)


@login_required
@never_cache
@require_GET
def block(request, pk):
    material = load_material(request.user, pk)
    progress = BlockProgress.objects.filter(user=request.user, material=material).first()
    if not progress or not (progress.opened_at or progress.completed_at):
        return render(request, 'learning/open.html', {'material': material, 'active_section': 'library', 'seek': seek_time(request)})
    latest = None
    if material.kind == 'quiz':
        quiz = get_object_or_404(Quiz.objects.prefetch_related('questions__choices'), material=material)
        material._state.fields_cache['quiz'] = quiz
        latest = quiz.attempts.filter(user=request.user).first()
    course = material.lesson.module.course
    from practice.models import Workspace
    ws, _ = Workspace.objects.get_or_create(user=request.user, material=material, defaults={'code':getattr(getattr(material,'practice_task',None),'starter','')})
    ws.save(update_fields=['touched_at'])
    all_blocks = list(course_blocks(course).order_by('lesson__module__order','lesson__order','order','id'))
    index = next((i for i, b in enumerate(all_blocks) if b.pk == pk), -1)
    completed_ids = set(BlockProgress.objects.filter(user=request.user, material__in=all_blocks, completed_at__isnull=False).values_list('material_id',flat=True))
    for b in all_blocks: b.done = b.pk in completed_ids
    task = getattr(material, 'practice_task', None)
    feedback = []
    if material.kind == 'quiz' and progress.completed_at:
        from autoquiz.models import QuestionSource
        sources = {s.question_id: s for s in QuestionSource.objects.filter(question__quiz=quiz)}
        for question in quiz.questions.all():
            if question.pk in sources:
                source = sources[question.pk]
                feedback.append({'id': question.pk, 'text': question.text, 'explanation': question.explanation,
                    'answer': ' · '.join(c.text for c in question.choices.all() if c.is_correct),
                    'time': f'{int(source.start)//60}:{int(source.start)%60:02}', 'quote': source.quote})
    # Explicit public fields only; never pass verdict/reasons/reviews to student UI.
    return render(request, 'learning/block.html', {
        'material': material, 'course': course, 'done': bool(progress.completed_at),
        'latest_attempt': latest, 'enrollment': Enrollment.objects.get(user=request.user, course=course),
        'video_feedback': feedback,
        'active_section': 'library',
        'task': task,
        'workspace_data': {'code':ws.code if ws else task.starter if task else '', 'stdin':ws.stdin if ws else '', 'revision':ws.revision if ws else 0, 'video_revision':ws.video_revision if ws else 0, 'position':ws.video_position if ws else 0, 'seek': seek_time(request) if material.kind == 'video' else None},
        'all_blocks': all_blocks,
        'next_block': all_blocks[index+1] if 0<=index<len(all_blocks)-1 else None,
        'previous_block': all_blocks[index-1] if index>0 else None,
    })


@login_required
@never_cache
@require_POST
def complete(request, pk):
    received_at = timezone.now()
    material = load_material(request.user, pk)
    try:
        created = complete_information(request.user, material, received_at)
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages), status=409)
    messages.success(request, 'Блок пройден. Начислен 1 балл.' if created else 'Блок уже пройден. Балл сохранён.')
    return redirect('learning:block', pk=pk)


@login_required
@never_cache
@require_POST
def submit_quiz(request, quiz_id):
    received_at = timezone.now()
    quiz = get_object_or_404(Quiz.objects.select_related('material__lesson__module__course'), pk=quiz_id)
    try:
        score, passed, awarded = submit_test(request.user, quiz, request.POST, received_at)
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages), status=409)
    if awarded:
        messages.success(request, f'Результат: {score}%. Блок пройден, начислен 1 балл.')
    elif passed:
        messages.success(request, 'Блок уже пройден. Повторные баллы не начисляются.')
    else:
        messages.warning(request, f'Результат: {score}%. Для зачёта нужно {quiz.passing_score}%. Попробуйте ещё раз.')
    return redirect('learning:block', pk=quiz.material_id)


@login_required
@require_POST
def complete_lesson(request, lesson_id):
    return HttpResponse('Теперь завершайте каждый блок отдельно: откройте урок.', status=410)


def scope(request, private):
    courses = Course.objects.filter(status='published')
    if private and not request.user.is_platform_admin:
        courses = courses.filter(created_by=request.user)
    course_id = request.GET.get('course', '')
    direction_id = request.GET.get('direction', '')
    if course_id:
        if not course_id.isdigit():
            raise PermissionDenied
        chosen = get_object_or_404(courses, pk=course_id)
        courses = courses.filter(pk=chosen.pk)
    if direction_id:
        if not direction_id.isdigit():
            raise PermissionDenied
        courses = courses.filter(direction_id=direction_id)
    return courses


def scoped_records(courses):
    return BlockProgress.objects.filter(material__lesson__module__course__in=courses, completed_at__isnull=False).annotate(
        effective=Case(When(review__isnull=False, then=F('review__verdict')), default=F('verdict'), output_field=CharField()))


def summary(records):
    counts = records.aggregate(total=Count('pk'), positive=Count('pk', filter=Q(effective='positive')),
                               negative=Count('pk', filter=Q(effective='negative')), unknown=Count('pk', filter=Q(effective='unknown')))
    counts['assessed'] = counts['positive'] + counts['negative']
    counts['percent'], counts['zone'] = zone(counts['negative'], counts['assessed'])
    return counts


@login_required
@never_cache
@require_GET
def leaderboard(request):
    return ranking_page(request, False)


@manager
@never_cache
@require_GET
def analytics(request):
    return ranking_page(request, True)


def ranking_page(request, private):
    courses = Course.objects.filter(status='published')
    if private and not request.user.is_platform_admin:
        courses = courses.filter(created_by=request.user)
    return render(request, 'learning/rating.html', {
        'private': private, 'courses': courses.select_related('direction').order_by('title', '-id'),
        'directions': Direction.objects.filter(courses__in=courses).distinct(),
        'active_section': 'analytics' if private else 'leaderboard',
    })


@login_required
@never_cache
@require_GET
def public_data(request):
    return rating_data(request, False)


@manager
@never_cache
@require_GET
def private_data(request):
    return rating_data(request, True)


def rating_data(request, private):
    courses = scope(request, private)
    User = get_user_model()
    users = User.objects.filter(role='student', is_active=True, is_superuser=False)
    if private or request.GET.get('course') or request.GET.get('direction'):
        users = users.filter(enrollments__course__in=courses)
    users = users.annotate(total_points=Count('block_progress', filter=Q(
        block_progress__completed_at__isnull=False, block_progress__material__lesson__module__course__in=courses), distinct=True)).order_by('-total_points', 'username', 'id')
    page = Paginator(users.distinct(), 50).get_page(request.GET.get('page', 1))
    rows = []
    records = scoped_records(courses)
    for index, student in enumerate(page.object_list, page.start_index()):
        row = {'id': student.pk, 'rank': index, 'username': student.username, 'year': student.study_year, 'points': student.total_points}
        if private:
            row.update(summary(records.filter(user=student)))
        rows.append(row)
    return JsonResponse({'rows': rows, 'page': page.number, 'pages': page.paginator.num_pages, 'count': page.paginator.count})


@login_required
@never_cache
@require_GET
def public_student(request, pk):
    return student_data(request, pk, False)


@manager
@never_cache
@require_GET
def private_student(request, pk):
    return student_data(request, pk, True)


def student_data(request, pk, private):
    courses = scope(request, private)
    student = get_object_or_404(get_user_model(), pk=pk, role='student', is_active=True, is_superuser=False)
    enrollments = Enrollment.objects.filter(user=student, course__in=courses).select_related('course__direction')
    if private and not enrollments.exists():
        raise PermissionDenied
    records = scoped_records(courses).filter(user=student)
    result = {'username': student.username, 'points': records.count(), 'courses': []}
    for enrollment in enrollments:
        cr = records.filter(material__lesson__module__course=enrollment.course)
        row = {'title': enrollment.course.title, 'id': enrollment.course_id, 'progress': enrollment.progress_percent,
               'completed': cr.count(), 'total': course_blocks(enrollment.course).count(), 'points': cr.count()}
        if private:
            row.update(summary(cr))
        result['courses'].append(row)
    if private:
        result['summary'] = summary(records)
        page = Paginator(records.select_related('material__lesson__module__course', 'review__reviewer').order_by('-completed_at', '-id'), 50).get_page(request.GET.get('blocks_page', 1))
        result['blocks_page'], result['blocks_pages'] = page.number, page.paginator.num_pages
        result['blocks'] = []
        for p in page.object_list:
            review = getattr(p, 'review', None)
            result['blocks'].append({
                'id': p.pk, 'course': p.material.lesson.module.course.title, 'lesson': p.material.lesson.title, 'title': p.material.title,
                'seconds': round(p.elapsed_ms / 1000, 3) if p.elapsed_ms is not None else None,
                'opened': p.opened_at.isoformat() if p.opened_at else None,
                'submitted': p.submitted_at.isoformat() if p.submitted_at else None,
                'attempts': p.attempts, 'verdict': p.effective, 'automatic': p.verdict, 'reasons': p.reasons,
                'rule': p.rule_version, 'imported': p.imported,
                'review': {'note': review.note, 'by': review.reviewer.username if review.reviewer else 'Удалённый аккаунт'} if review else None,
            })
    return JsonResponse(result)


@manager
@never_cache
@require_POST
def review(request, pk):
    progress = get_object_or_404(BlockProgress.objects.select_related('material__lesson__module__course', 'user'), pk=pk, completed_at__isnull=False)
    course = progress.material.lesson.module.course
    if not request.user.is_platform_admin and course.created_by_id != request.user.pk:
        raise PermissionDenied
    value = request.POST.get('verdict')
    note = request.POST.get('note', '').strip()
    if value not in ('positive', 'negative', 'unknown', 'reset') or not note or len(note) > 2000:
        return JsonResponse({'error': 'Выберите результат и добавьте комментарий (до 2000 символов).'}, status=400)
    from teaching.services import record_review
    record_review(request.user, progress, value, note)
    return JsonResponse({'ok': True})
