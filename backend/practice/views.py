import json
import math
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from courses.models import Enrollment, Material
from learning.models import BlockProgress
from learning.services import authorize, lock_user, course_blocks
from .models import Workspace, Task, Submission
from .services import enqueue, worker_available


def material_for(user, pk):
    material = get_object_or_404(Material.objects.select_related('lesson__module__course'), pk=pk)
    authorize(user, material, practice=True)
    if not BlockProgress.objects.filter(user=user, material=material).filter(opened_at__isnull=False).exists() and not BlockProgress.objects.filter(user=user, material=material, completed_at__isnull=False).exists():
        raise PermissionDenied
    return material


def payload(request):
    if len(request.body)>200000: raise ValueError('Слишком большой запрос.')
    data = json.loads(request.body)
    if not isinstance(data, dict): raise ValueError('Неверный запрос.')
    return data


@login_required
@never_cache
@require_POST
def save_workspace(request, pk):
    material = material_for(request.user, pk)
    try:
        data = payload(request)
        with transaction.atomic():
            lock_user(request.user)
            ws, _ = Workspace.objects.get_or_create(user=request.user, material=material, defaults={'code':getattr(getattr(material,'practice_task',None),'starter','')})
            if data.get('type') == 'video':
                value = data.get('position')
                if material.kind!='video' or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=86400: raise ValueError('Неверная позиция видео.')
                if data.get('revision') != ws.video_revision: return JsonResponse({'error':'Видео открыто в другой вкладке. Обновите страницу.', 'revision':ws.video_revision}, status=409)
                ws.video_position=value; ws.video_revision+=1
                ws.save(update_fields=['video_position','video_revision','touched_at'])
                return JsonResponse({'revision':ws.video_revision})
            code, stdin = data.get('code'), data.get('stdin')
            if material.kind!='code' or not isinstance(code,str) or not isinstance(stdin,str) or len(code.encode())>100000 or len(stdin.encode())>10000: raise ValueError('Код до 100 КБ, ввод до 10 КБ.')
            if data.get('revision') != ws.revision: return JsonResponse({'error':'Черновик изменён в другой вкладке. Скачайте свой код и перезагрузите страницу.'}, status=409)
            ws.code=code; ws.stdin=stdin; ws.revision+=1
            ws.save(update_fields=['code','stdin','revision','touched_at'])
            return JsonResponse({'revision':ws.revision})
    except (ValueError, TypeError): return JsonResponse({'error':'Не удалось сохранить: проверьте размер и формат данных.'}, status=400)


def serialize(job):
    return {'id':str(job.pk),'status':job.status,'mode':job.mode,'submitted':job.submitted_at.isoformat(),
            'diagnostic':job.diagnostic,'stdout':job.stdout,'passed':job.passed_tests,'total':job.total_tests,
            'retries':job.retries}


@login_required
@never_cache
@require_POST
def submit(request, pk):
    material = material_for(request.user, pk)
    task = get_object_or_404(Task, material=material)
    try:
        data=payload(request)
        job=enqueue(request.user,task,data.get('code'),data.get('stdin',''),data.get('mode'),data.get('key'))
        return JsonResponse(serialize(job))
    except (ValueError, TypeError, ValidationError) as exc:
        return JsonResponse({'error':'; '.join(exc.messages) if isinstance(exc,ValidationError) else 'Неверный запрос.'}, status=400)


@login_required
@never_cache
@require_GET
def history(request, pk):
    material=material_for(request.user,pk)
    jobs=Submission.objects.filter(user=request.user,task__material=material)
    from django.core.paginator import Paginator
    page=Paginator(jobs,20).get_page(request.GET.get('page',1))
    done=BlockProgress.objects.filter(user=request.user,material=material,completed_at__isnull=False).exists()
    enrollment=Enrollment.objects.get(user=request.user,course=material.lesson.module.course)
    return JsonResponse({'items':[serialize(x) for x in page], 'page':page.number,'pages':page.paginator.num_pages,'active':next((serialize(j) for j in jobs.filter(status__in=['queued','running'])[:1]),None),'available':worker_available(),'done':done,'progress':enrollment.progress_percent})


@login_required
@never_cache
@require_GET
def source(request, pk):
    job=get_object_or_404(Submission.objects.select_related('task__material__lesson__module__course'),pk=pk,user=request.user)
    authorize(request.user,job.task.material,practice=True)
    return JsonResponse({'code':job.code,'stdin':job.stdin})


@login_required
@never_cache
@require_POST
def cancel(request, pk):
    job=get_object_or_404(Submission,pk=pk,user=request.user)
    with transaction.atomic():
        lock_user(request.user)
        Submission.objects.filter(pk=job.pk,status__in=['queued','running']).update(status='cancelled',finished_at=timezone.now())
    return JsonResponse({'ok':True})


@login_required
@never_cache
@require_GET
def resume(request, pk):
    enrollment=get_object_or_404(Enrollment.objects.select_related('course'),pk=pk,user=request.user,course__status='published')
    blocks=course_blocks(enrollment.course).order_by('lesson__module__order','lesson__order','order','id')
    completed=BlockProgress.objects.filter(user=request.user,completed_at__isnull=False).values('material_id')
    ws=Workspace.objects.filter(user=request.user,material__in=blocks).exclude(material_id__in=completed).order_by('-touched_at').first()
    last=BlockProgress.objects.filter(user=request.user,material__in=blocks,completed_at__isnull=True).order_by('-opened_at').first()
    material=ws.material if ws else last.material if last else blocks.exclude(pk__in=completed).first()
    return redirect('learning:block',pk=material.pk) if material else redirect(enrollment.course.get_absolute_url())


@login_required
@require_GET
def library(request):
    enrollments=list(Enrollment.objects.filter(user=request.user,course__status='published').select_related('course__direction'))
    state=request.GET.get('state','all')
    if state=='active':enrollments=[e for e in enrollments if e.progress_percent<100]
    if state=='done':enrollments=[e for e in enrollments if e.progress_percent==100]
    for e in enrollments:
        e.blocks_total=course_blocks(e.course).count()
        e.blocks_done=BlockProgress.objects.filter(user=request.user,material__in=course_blocks(e.course),completed_at__isnull=False).count()
    return render(request,'practice/library.html',{'enrollments':enrollments,'state':state,'active_section':'library'})
