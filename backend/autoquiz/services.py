import copy
import hashlib
import json
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from studio.content import normalize, uid
from studio.models import Draft, Asset
from .models import Generation, DraftSource, QuestionSource
from .validation import questions_checked, segments_checked

ACTIVE = ['queued', 'transcribing', 'generating']


class Conflict(ValidationError):
    pass


def steps(data):
    for section in data.get('sections', []):
        for lesson in section.get('lessons', []):
            for step in lesson.get('steps', []):
                yield lesson, step


def video_in(draft, key, asset_id=None):
    pair = next(((lesson, step) for lesson, step in steps(draft.data) if step['id'] == key), None)
    if draft.archived or not pair or pair[1]['kind'] != 'video' or not pair[1].get('asset'):
        raise ValidationError('Откройте активный черновик и загрузите видеофайл в этот шаг.')
    if asset_id is not None and pair[1]['asset'] != asset_id:
        raise ValidationError('Видео заменено. Создайте тест по новому файлу.')
    return pair


def locked_draft(pk):
    # Write first: SQLite, as well as PostgreSQL, serializes concurrent mutations.
    Draft.objects.filter(pk=pk).update(revision=F('revision'))
    return Draft.objects.get(pk=pk)


def enqueue(draft, key, actor, segments=None):
    if not settings.AUTOQUIZ_ENABLED:
        raise ValidationError('Автоматическая генерация отключена. Добавьте обычный тест в редакторе курса.')
    _, step = video_in(draft, key)
    asset = Asset.objects.get(pk=step['asset'], draft=draft)
    source = segments_checked(segments) if segments is not None else []
    identity = [asset.pk, source, settings.AUTOQUIZ_MODEL, settings.AUTOQUIZ_WHISPER, 'prompt-v1']
    fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    existing = Generation.objects.filter(draft=draft, video_key=key, fingerprint=fingerprint).first()
    if existing:
        return existing
    if Generation.objects.filter(draft=draft, state__in=ACTIVE).count() >= 20:
        raise ValidationError('В этом курсе уже 20 видео в очереди. Дождитесь обработки.')
    Generation.objects.filter(draft=draft, video_key=key, state__in=ACTIVE + ['ready', 'failed']).update(
        state='stale', token=None, revision=F('revision')+1, updated_at=timezone.now())
    return Generation.objects.create(draft=draft, asset=asset, video_key=key, fingerprint=fingerprint,
        segments=source, model=settings.AUTOQUIZ_MODEL, whisper_model=settings.AUTOQUIZ_WHISPER,
        created_by=actor, phase='Ждём свободный обработчик')


def sync_videos(draft, actor):
    """Called inside the editor save transaction; never load a model here."""
    valid = {step['id']: step.get('asset') for _, step in steps(draft.data) if step['kind'] == 'video'}
    for job in Generation.objects.filter(draft=draft, state__in=ACTIVE + ['ready']):
        if draft.archived or valid.get(job.video_key) != job.asset_id:
            Generation.objects.filter(pk=job.pk).update(state='stale', token=None, revision=F('revision')+1)
    for _, step in steps(draft.data):
        if settings.AUTOQUIZ_ENABLED and step['kind'] == 'video' and step.get('auto_quiz') and step.get('asset') and not draft.archived:
            # Subtitles/manual jobs for the same file are respected by autosave.
            if not Generation.objects.filter(draft=draft, video_key=step['id'], asset_id=step['asset']).exists():
                enqueue(draft, step['id'], actor)


@transaction.atomic
def queue_video(draft_pk, key, actor, segments=None):
    return enqueue(locked_draft(draft_pk), key, actor, segments)


def check_revision(job, expected):
    if isinstance(expected, bool) or not isinstance(expected, int) or job.revision != expected:
        raise Conflict('Данные изменились в другой вкладке. Сохраните свой текст и обновите страницу.')


@transaction.atomic
def edit_result(job_id, expected, raw, reviewed):
    draft_id = Generation.objects.values_list('draft_id', flat=True).get(pk=job_id)
    draft = locked_draft(draft_id)
    job = Generation.objects.get(pk=job_id)
    check_revision(job, expected)
    video_in(draft, job.video_key, job.asset_id)
    if job.state != 'ready':
        raise ValidationError('Дождитесь готового теста. Добавленные тесты редактируются в программе курса.')
    checked = questions_checked(raw, job.segments)
    # Source anchors belong to the transcript, not to an editable browser form.
    for current, updated in zip(job.questions, checked):
        if updated['segment'] != current['segment'] or updated['quote'] != current['quote']:
            raise ValidationError('Источник вопроса изменять нельзя. Пересоздайте вопрос по лекции.')
    job.questions = checked
    job.revision += 1
    job.reviewed_revision = job.revision if reviewed is True else 0
    job.save(update_fields=['questions', 'revision', 'reviewed_revision', 'updated_at'])
    return job


@transaction.atomic
def action(job_id, expected, name, index=None):
    draft = locked_draft(Generation.objects.values_list('draft_id', flat=True).get(pk=job_id))
    job = Generation.objects.get(pk=job_id)
    check_revision(job, expected)
    if name == 'cancel':
        if job.state not in ACTIVE:
            raise ValidationError('Эта обработка уже завершена.')
        job.state, job.token, job.phase = 'cancelled', None, 'Обработка отменена'
    else:
        if not settings.AUTOQUIZ_ENABLED:
            raise ValidationError('Генерация отключена на этом сервере. Готовый тест можно редактировать и опубликовать.')
        video_in(draft, job.video_key, job.asset_id)
        if name == 'retry':
            if job.state not in ['failed', 'cancelled']:
                raise ValidationError('Повтор доступен для отменённой или неудачной обработки.')
        elif name == 'regenerate':
            if job.state != 'ready' or isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < 10:
                raise ValidationError('Выберите вопрос готового теста.')
            job.replace_index = index
        else:
            raise ValidationError('Неизвестное действие.')
        job.state, job.token, job.error, job.phase = 'queued', None, '', 'Ждём свободный обработчик'
        job.reviewed_revision = 0
    job.revision += 1
    job.save()
    return job


@transaction.atomic
def apply_result(job_id, expected, draft_revision):
    draft = locked_draft(Generation.objects.values_list('draft_id', flat=True).get(pk=job_id))
    job = Generation.objects.get(pk=job_id)
    if job.state == 'applied':
        return draft, job.quiz_key  # Network retry cannot insert another quiz.
    check_revision(job, expected)
    if draft.revision != draft_revision or isinstance(draft_revision, bool):
        raise Conflict('Курс изменился в другой вкладке. Обновите страницу проверки и повторите добавление.')
    if job.state != 'ready' or job.reviewed_revision != job.revision:
        raise ValidationError('Проверьте вопросы и сохраните отметку «Я проверил вопросы и ответы».')
    lesson, video = video_in(draft, job.video_key, job.asset_id)
    if len(lesson['steps']) >= 200:
        raise ValidationError('В уроке уже 200 шагов.')
    questions = questions_checked(job.questions, job.segments)
    quiz_key = uid()
    quiz = {'id': quiz_key, 'kind': 'quiz', 'title': ('Тест · ' + video['title'])[:180],
            'required': True, 'points': 1, 'passing': 100, 'questions': []}
    anchors = []
    for q in questions:
        key = uid()
        quiz['questions'].append({'id': key, 'type': 'single', 'text': q['question'],
            'explanation': q['explanation'], 'choices': [{'text': text, 'correct': i == q['correct']} for i, text in enumerate(q['choices'])]})
        anchors.append(DraftSource(generation=job, question_key=key, start=q['start'], end=q['end'], quote=q['quote']))
    lesson['steps'].insert(lesson['steps'].index(video)+1, quiz)
    draft.data = normalize(draft.data, draft)
    draft.revision += 1
    draft.save(update_fields=['data', 'revision', 'updated_at'])
    DraftSource.objects.bulk_create(anchors)
    job.state, job.quiz_key = 'applied', quiz_key
    job.revision += 1
    job.save(update_fields=['state', 'quiz_key', 'revision', 'updated_at'])
    return draft, quiz_key


def publish_sources(draft, material_map, question_map):
    records = []
    for anchor in DraftSource.objects.filter(generation__draft=draft, question_key__in=question_map).select_related('generation__asset'):
        video = material_map.get(anchor.generation.video_key)
        question = question_map[anchor.question_key]
        # A replaced/deleted/inactive video must not gain a link to the old file.
        if not video or video.kind != 'video' or not video.lesson.is_active or video.file.name != anchor.generation.asset.file.name:
            continue
        records.append(QuestionSource(question=question, video=video, start=anchor.start, end=anchor.end, quote=anchor.quote))
    QuestionSource.objects.bulk_create(records)
