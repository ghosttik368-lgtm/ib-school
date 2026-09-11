from django.conf import settings
from django.db import models


class BlockProgress(models.Model):
    class Verdict(models.TextChoices):
        UNKNOWN = 'unknown', 'Нет данных'
        POSITIVE = 'positive', 'Без срабатываний'
        NEGATIVE = 'negative', 'Требует проверки'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='block_progress')
    material = models.ForeignKey('courses.Material', on_delete=models.PROTECT, related_name='block_progress')
    opened_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    elapsed_ms = models.PositiveBigIntegerField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    verdict = models.CharField(max_length=12, choices=Verdict.choices, default=Verdict.UNKNOWN)
    reasons = models.JSONField(default=list, blank=True)
    rule_version = models.CharField(max_length=30, blank=True)
    comment_count = models.PositiveIntegerField(null=True, blank=True)
    imported = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'material'], name='unique_user_block')]
        indexes = [models.Index(fields=['user', 'completed_at'], name='block_user_completed')]

    @property
    def effective_verdict(self):
        review = getattr(self, 'review', None)
        return review.verdict if review else self.verdict


class BlockReview(models.Model):
    progress = models.OneToOneField(BlockProgress, on_delete=models.CASCADE, related_name='review')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    verdict = models.CharField(max_length=12, choices=BlockProgress.Verdict.choices)
    note = models.TextField(max_length=2000)
    updated_at = models.DateTimeField(auto_now=True)
