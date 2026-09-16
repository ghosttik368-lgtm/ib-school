from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from learning.models import BlockProgress
from learning.services import authorize
from studio.views import manager, owned, body
from .models import Generation, QuestionSource, WorkerLease
from .services import queue_video, edit_result, apply_result, action, Conflict, steps, ACTIVE
from .validation import parse_subtitles


def job_owned(request, pk):
    job = get_object_or_404(Generation.objects.select_related('draft', 'asset'), pk=pk)
    owned(request, job.draft_id)
    return job


def packet(job, detail=False):
    result = {'generation_enabled': settings.AUTOQUIZ_ENABLED, 'id': str(job.pk), 'state': job.state, 'label': job.get_state_display(),
        'phase': job.phase, 'error': job.error, 'revision': job.revision,
        'video': job.video_key, 'asset': job.asset_id, 'quiz': job.quiz_key,
        'url': reverse('autoquiz:review', args=[job.pk]), 'active': job.state in ACTIVE,
        'reviewed': job.reviewed_revision == job.revision, 'has_transcript': bool(job.segments)}
    if detail:
        result['questions'] = job.questions
    return result


def conflict_response(exc):
    return JsonResponse({'error': ' '.join(exc.messages), 'conflict': True}, status=409)


@manager
@require_GET
def listing(request, draft_id):
    draft = owned(request, draft_id)
    current = {step['id']: step.get('asset') for _, step in steps(draft.data)}
    latest = {}
    for job in draft.quiz_generations.order_by('-created_at'):
        if current.get(job.video_key) == job.asset_id and job.video_key not in latest:
            latest[job.video_key] = packet(job)
    return JsonResponse({'enabled': settings.AUTOQUIZ_ENABLED, 'jobs': list(latest.values()), 'worker': settings.AUTOQUIZ_ENABLED and WorkerLease.objects.filter(name='autoquiz', expires_at__gt=timezone.now()).exists()})


@manager
@require_POST
def queue(request, draft_id):
    owned(request, draft_id)
    if not settings.AUTOQUIZ_ENABLED:
        return JsonResponse({'error': 'Генерация отключена на этом сервере. Добавьте обычный тест в редакторе.'}, status=503)
    payload = body(request)
    key = payload.get('video')
    if not isinstance(key, str) or len(key) > 40:
        raise ValidationError('Выберите видеолекцию.')
    subtitles = parse_subtitles(payload['subtitles']) if payload.get('subtitles') else None
    return JsonResponse(packet(queue_video(draft_id, key, request.user, subtitles)))


@manager
@require_GET
def review(request, pk):
    job = job_owned(request, pk)
    return render(request, 'autoquiz/review.html', {'job': job, 'job_data': packet(job, detail=True),
        'draft_revision': job.draft.revision, 'active_section': 'management'})


@manager
@require_GET
def status(request, pk):
    return JsonResponse(packet(job_owned(request, pk)))


@manager
@require_POST
def save(request, pk):
    job_owned(request, pk)
    payload = body(request)
    try:
        job = edit_result(pk, payload.get('revision'), payload.get('questions'), payload.get('reviewed'))
    except Conflict as exc:
        return conflict_response(exc)
    return JsonResponse(packet(job, detail=True))


@manager
@require_POST
def control(request, pk):
    job_owned(request, pk)
    payload = body(request)
    try:
        job = action(pk, payload.get('revision'), payload.get('action'), payload.get('index'))
    except Conflict as exc:
        return conflict_response(exc)
    return JsonResponse(packet(job))


@manager
@require_POST
def apply(request, pk):
    job_owned(request, pk)
    payload = body(request)
    try:
        draft, key = apply_result(pk, payload.get('revision'), payload.get('draft_revision'))
    except Conflict as exc:
        return conflict_response(exc)
    return JsonResponse({'url': reverse('studio:editor', args=[draft.pk]) + '?step=' + key})


def timestamp(seconds):
    ms = round(seconds*1000)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'


@manager
@require_GET
def transcript(request, pk):
    job = job_owned(request, pk)
    result = '\n\n'.join(f'{i}\n{timestamp(s["start"])} --> {timestamp(s["end"])}\n{s["text"]}' for i, s in enumerate(job.segments, 1))
    response = HttpResponse(result, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="lecture.srt"'
    return response


@login_required
@require_GET
def replay(request, question_id):
    source = get_object_or_404(QuestionSource.objects.select_related('question__quiz__material__lesson__module__course', 'video__lesson__module__course'), question_id=question_id)
    material = source.question.quiz.material
    authorize(request.user, material, practice=True)
    authorize(request.user, source.video, practice=True)
    if material.lesson.module.course_id != source.video.lesson.module.course_id:
        raise PermissionDenied
    if not BlockProgress.objects.filter(user=request.user, material=material, completed_at__isnull=False).exists():
        raise PermissionDenied
    return redirect(reverse('learning:block', args=[source.video_id]) + f'?t={source.start:.3f}')
