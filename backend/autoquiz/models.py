import uuid
from django.conf import settings
from django.db import models


class Generation(models.Model):
    class State(models.TextChoices):
        QUEUED = 'queued', 'В очереди'
        TRANSCRIBING = 'transcribing', 'Распознаём речь'
        GENERATING = 'generating', 'Составляем вопросы'
        READY = 'ready', 'Ожидает проверки'
        FAILED = 'failed', 'Нужна помощь'
        CANCELLED = 'cancelled', 'Отменено'
        STALE = 'stale', 'Видео заменено'
        APPLIED = 'applied', 'Тест добавлен'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    draft = models.ForeignKey('studio.Draft', on_delete=models.CASCADE, related_name='quiz_generations')
    asset = models.ForeignKey('studio.Asset', on_delete=models.PROTECT)
    video_key = models.CharField(max_length=40)
    fingerprint = models.CharField(max_length=64)
    state = models.CharField(max_length=20, choices=State.choices, default=State.QUEUED, db_index=True)
    phase = models.CharField(max_length=240, blank=True)
    error = models.TextField(blank=True)
    language = models.CharField(max_length=5, default='ru')
    model = models.CharField(max_length=120)
    whisper_model = models.CharField(max_length=40, default='medium')
    segments = models.JSONField(default=list, blank=True)
    questions = models.JSONField(default=list, blank=True)
    replace_index = models.PositiveSmallIntegerField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    reviewed_revision = models.PositiveIntegerField(default=0)
    token = models.UUIDField(null=True, blank=True)
    quiz_key = models.CharField(max_length=40, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['draft', 'video_key', 'fingerprint'], name='unique_video_quiz_input')]


class DraftSource(models.Model):
    generation = models.ForeignKey(Generation, on_delete=models.CASCADE, related_name='draft_sources')
    question_key = models.CharField(max_length=40)
    start = models.FloatField()
    end = models.FloatField()
    quote = models.TextField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['generation', 'question_key'], name='unique_draft_question_source')]


class QuestionSource(models.Model):
    question = models.OneToOneField('courses.Question', on_delete=models.CASCADE, related_name='video_source')
    video = models.ForeignKey('courses.Material', on_delete=models.PROTECT, related_name='quiz_sources')
    start = models.FloatField()
    end = models.FloatField()
    quote = models.TextField()


class WorkerLease(models.Model):
    # One shared lease prevents two local workers loading large models at once.
    name = models.CharField(max_length=32, primary_key=True, default='autoquiz')
    token = models.UUIDField(null=True)
    expires_at = models.DateTimeField(null=True)
