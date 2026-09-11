from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from learning.views import manager
from learning.models import BlockProgress
from learning.services import lock_user
from .models import StudyGroup, AssignmentStudent, ReviewEvent, ReportSnapshot
from . import services


@manager
@require_GET
def dashboard(request):
    groups = services.visible_groups(request.user)
    if request.GET.get('archive') != '1':
        groups = groups.filter(archived=False)
    groups = groups.select_related('owner').annotate(people=Count('members',distinct=True), courses=Count('assignments',distinct=True)).order_by('title','id')
    return render(request,'teaching/groups.html',{'active_section':'teaching','groups':Paginator(groups,30).get_page(request.GET.get('page')), 'archive':request.GET.get('archive') == '1'})


@manager
@require_POST
def create_group(request):
    title = request.POST.get('title','').strip()
    if not 1 <= len(title) <= 100:
        messages.error(request,'Введите название группы до 100 символов.')
        return redirect('teaching:groups')
    try:
        with transaction.atomic():
            lock_user(request.user)
            group = StudyGroup.objects.create(owner=request.user, title=title)
    except IntegrityError:
        messages.error(request,'У вас уже есть группа с таким названием.')
        return redirect('teaching:groups')
    return redirect('teaching:group',pk=group.pk)


@manager
def group(request, pk):
    group = get_object_or_404(services.visible_groups(request.user),pk=pk)
    if request.method == 'POST':
        try:
            services.change_group(request.user,pk,request.POST.get('action'),request.POST)
            messages.success(request,'Изменения сохранены.')
        except (ValidationError, ValueError, TypeError) as exc:
            messages.error(request,'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Проверьте введённые данные.')
        return redirect('teaching:group',pk=pk)
    if request.method != 'GET':
        return HttpResponse(status=405)
    query = request.GET.get('q','').strip()[:100]
    candidates = get_user_model().objects.filter(role='student',is_superuser=False,is_active=True).exclude(study_memberships__group=group).order_by('username')
    if query:
        candidates = candidates.filter(username__icontains=query)
    available = services.visible_courses(request.user).filter(is_listed=True)
    if not group.owner.is_platform_admin:
        available = available.filter(created_by=group.owner)
    return render(request,'teaching/group.html',{'active_section':'teaching','group':group,
        'members':group.members.select_related('user').order_by('user__username'), 'candidates':candidates[:30], 'q':query,
        'assignments':group.assignments.select_related('course').order_by('-id'), 'available_courses':available})


@login_required
@require_GET
def assigned(request):
    items = AssignmentStudent.objects.filter(user=request.user, assignment__group__archived=False,
        assignment__group__members__user=request.user).select_related('assignment__group','assignment__course','enrollment__course').distinct().order_by('-id')
    page = Paginator(items,30).get_page(request.GET.get('page'))
    for item in page:
        item.overdue = bool(item.assignment.due_date and item.assignment.due_date < timezone.localdate() and item.enrollment.progress_percent < 100)
    return render(request,'teaching/assigned.html',{'active_section':'assignments','items':page})


@manager
@require_GET
def reports(request):
    try:
        rows = services.report_rows(request.user,request.GET)
    except ValidationError as exc:
        messages.error(request,'; '.join(exc.messages))
        rows = []
    page = Paginator(rows,50).get_page(request.GET.get('page'))
    comparisons = {}
    for row in rows:
        c = comparisons.setdefault(row['course_id'],{'title':row['course'],'n':0,'done':0,'sum':0})
        c['n'] += 1; c['done'] += row['progress'] == 100; c['sum'] += row['progress']
    for c in comparisons.values():
        c['average'] = round(c['sum']/c['n'],1)
    params = request.GET.copy(); params.pop('page',None)
    return render(request,'teaching/reports.html',{'active_section':'teaching','rows':page,'params':params.urlencode(),
        'groups':services.visible_groups(request.user),'courses':services.visible_courses(request.user),
        'comparisons':comparisons.values(),'students':len({r['user_id'] for r in rows}),'completed':sum(r['state']=='done' for r in rows)})


@manager
@require_GET
def export(request):
    try:
        return services.export_csv(services.report_rows(request.user,request.GET))
    except ValidationError as exc:
        return HttpResponse('; '.join(exc.messages),status=400)


@manager
@require_GET
def student(request, pk):
    person = get_object_or_404(get_user_model(),pk=pk,role='student',is_superuser=False)
    courses, enrollments = services.filtered(request.user,request.GET)
    memberships = person.study_memberships.filter(group__in=services.visible_groups(request.user))
    if request.GET.get('group'):
        memberships = memberships.filter(group_id=request.GET['group'])
    if not enrollments.filter(user=person).exists() and not memberships.exists():
        raise PermissionDenied
    records = BlockProgress.objects.filter(user=person,material__lesson__module__course__in=courses).select_related('material__lesson__module__course','review__reviewer').order_by('-id')
    page = Paginator(records,30).get_page(request.GET.get('page'))
    for record in page:
        record.seconds = round(record.elapsed_ms/1000,3) if record.elapsed_ms is not None else None
        if getattr(record,'review',None):
            record.review.label = dict(BlockProgress.Verdict.choices).get(record.review.verdict,record.review.verdict)
    events = Paginator(ReviewEvent.objects.filter(progress__user=person,progress__material__lesson__module__course__in=courses).select_related('reviewer','progress__material'),30).get_page(request.GET.get('events_page'))
    rows = [r for r in services.report_rows(request.user,request.GET) if r['user_id'] == person.pk]
    params = request.GET.copy(); params.pop('page',None); params.pop('events_page',None)
    return render(request,'teaching/student.html',{'active_section':'teaching','person':person,'rows':rows,'records':page,'events':events,'params':params.urlencode()})


@manager
@require_GET
def attempts(request, pk):
    progress = get_object_or_404(BlockProgress.objects.select_related('material__lesson__module__course','user'),pk=pk,
        material__lesson__module__course__in=services.visible_courses(request.user))
    material = progress.material
    code_page, quiz_page = None,None
    if material.kind == 'code':
        from practice.models import Submission
        code_page = Paginator(Submission.objects.filter(user=progress.user,task__material=material).order_by('-submitted_at'),10).get_page(request.GET.get('page'))
        labels = {'queued':'В очереди','running':'Проверяется','accepted':'Зачёт','wrong_answer':'Неверный ответ','compile_error':'Ошибка компиляции','runtime_error':'Ошибка выполнения','time_limit':'Превышено время','output_limit':'Слишком большой вывод','error':'Ошибка сервиса','cancelled':'Отменено','run_ok':'Запуск завершён'}
        for job in code_page:
            job.status_label = labels.get(job.status,job.status)
    elif material.kind == 'quiz':
        from courses.models import QuizAttempt, Question
        quiz_page = Paginator(QuizAttempt.objects.filter(user=progress.user,quiz__material=material).order_by('-created_at'),10).get_page(request.GET.get('page'))
        questions = {str(q.pk):q for q in Question.objects.filter(quiz__material=material).prefetch_related('choices')}
        for attempt in quiz_page:
            attempt.answers = []
            for key, values in attempt.selected_answers.items():
                question = questions.get(str(key))
                if question:
                    choices = {str(c.pk):c.text for c in question.choices.all()}
                    values = values if isinstance(values,list) else [str(values)]
                    attempt.answers.append({'question':question.text,'answer':', '.join(choices.get(str(v),str(v)) for v in values)})
    return render(request,'teaching/attempts.html',{'active_section':'teaching','progress':progress,'code_page':code_page,'quiz_page':quiz_page})


@manager
def snapshots(request):
    if request.method == 'POST':
        try:
            title = request.POST.get('title','').strip()
            if not 1 <= len(title) <= 120:
                raise ValidationError('Название отчёта — до 120 символов.')
            rows = services.report_rows(request.user,request.POST)
            if len(rows) > 5000:
                raise ValidationError('Для сохранения выберите не больше 5000 строк.')
            if ReportSnapshot.objects.filter(owner=request.user).count() >= 100:
                raise ValidationError('Сохранено 100 отчётов. Удалите ненужные.')
            snapshot = ReportSnapshot.objects.create(owner=request.user,title=title,rows=rows,filters={k:request.POST.get(k,'') for k in ('group','course','state','zone','q')})
            return redirect('teaching:snapshot',pk=snapshot.pk)
        except ValidationError as exc:
            messages.error(request,'; '.join(exc.messages))
    elif request.method != 'GET':
        return HttpResponse(status=405)
    return render(request,'teaching/snapshots.html',{'active_section':'teaching','snapshots':Paginator(ReportSnapshot.objects.filter(owner=request.user),30).get_page(request.GET.get('page'))})


@manager
def snapshot(request, pk):
    item = get_object_or_404(ReportSnapshot,pk=pk,owner=request.user)
    if request.method == 'POST':
        item.delete()
        return redirect('teaching:snapshots')
    if request.method != 'GET':
        return HttpResponse(status=405)
    visible = set(services.visible_courses(request.user).values_list('id',flat=True))
    if any(r['course_id'] not in visible for r in item.rows):
        raise PermissionDenied
    if request.GET.get('download') == '1':
        return services.export_csv(item.rows)
    comparison, changes = None, []
    if request.GET.get('compare','').isdigit():
        comparison = get_object_or_404(ReportSnapshot,pk=int(request.GET['compare']),owner=request.user)
        if any(r['course_id'] not in visible for r in comparison.rows):
            raise PermissionDenied
        previous = {(r['user_id'],r['course_id']):r for r in comparison.rows}
        current = {(r['user_id'],r['course_id']):r for r in item.rows}
        for key in sorted(previous.keys() | current.keys()):
            before, after = previous.get(key), current.get(key)
            row = after or before
            changes.append({'name':row['name'],'course':row['course'],
                'progress_before':before['progress'] if before else None, 'progress_after':after['progress'] if after else None,
                'points_delta':after['blocks']-before['blocks'] if before and after else None,
                'negative_delta':after['negative']-before['negative'] if before and after else None})
    return render(request,'teaching/snapshot.html',{'active_section':'teaching','snapshot':item,'rows':Paginator(item.rows,50).get_page(request.GET.get('page')),
        'others':ReportSnapshot.objects.filter(owner=request.user).exclude(pk=item.pk),'comparison':comparison,
        'changes':Paginator(changes,50).get_page(request.GET.get('diff_page'))})


@manager
@require_GET
def rules(request):
    courses, enrollments = services.filtered(request.user,request.GET)
    records = BlockProgress.objects.filter(material__lesson__module__course__in=courses,user__in=enrollments.values('user_id'),completed_at__isnull=False)
    reviewed = records.filter(review__isnull=False)
    binary = reviewed.filter(verdict__in=['positive','negative'], review__verdict__in=['positive','negative'])
    matrix = {k:0 for k in ('pp','pn','np','nn')}
    for row in binary.values('verdict','review__verdict').annotate(n=Count('id')):
        matrix[row['verdict'][0]+row['review__verdict'][0]] = row['n']
    total = sum(matrix.values())
    agreement = round(100*(matrix['pp']+matrix['nn'])/total,1) if total else None
    thresholds = {'info':10,'quiz':7,'code':20}
    valid = True
    for kind in thresholds:
        try:
            thresholds[kind] = int(request.GET.get(kind,thresholds[kind]))
            if not 0 <= thresholds[kind] <= 3600:
                raise ValueError
        except (ValueError,TypeError):
            valid = False
    comments = request.GET.get('comments','1') == '1'
    simulated = {'positive':0,'negative':0,'unknown':0,'changed':0}
    if valid:
        for r in records.select_related('material').iterator(chunk_size=500):
            kind = r.material.kind if r.material.kind in ('quiz','code') else 'info'
            if r.elapsed_ms is None or (kind == 'code' and r.comment_count is None and comments):
                verdict = 'unknown'
            else:
                flag = r.elapsed_ms <= thresholds[kind]*1000 or (kind=='code' and comments and (r.comment_count or 0)>0)
                verdict = 'negative' if flag else 'positive'
            simulated[verdict] += 1
            simulated['changed'] += verdict != r.verdict
    else:
        messages.error(request,'Пороги задаются целыми секундами от 0 до 3600.')
        thresholds = {'info':10,'quiz':7,'code':20}
    return render(request,'teaching/rules.html',{'active_section':'teaching','courses':services.visible_courses(request.user),
        'groups':services.visible_groups(request.user),'matrix':matrix,'reviewed':reviewed.count(),'total':total,'agreement':agreement,
        'thresholds':thresholds,'comments':comments,'simulated':simulated,'valid':valid})
