import uuid
from pathlib import Path
from django.conf import settings
from django.db import models


def asset_path(instance, filename):
    return f'studio/{instance.draft_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'


class Draft(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    source_course = models.OneToOneField('courses.Course', null=True, blank=True, on_delete=models.PROTECT, related_name='studio_source')
    latest_course = models.ForeignKey('courses.Course', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    title = models.CharField(max_length=180, default='Новый курс')
    data = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    published_revision = models.PositiveIntegerField(default=0)
    archived = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class Asset(models.Model):
    draft = models.ForeignKey(Draft, on_delete=models.CASCADE, related_name='assets')
    file = models.FileField(upload_to=asset_path)
    name = models.CharField(max_length=240)
    size = models.PositiveBigIntegerField(default=0)


class Release(models.Model):
    draft = models.ForeignKey(Draft, on_delete=models.PROTECT, related_name='releases')
    course = models.OneToOneField('courses.Course', on_delete=models.PROTECT, related_name='studio_release')
    number = models.PositiveIntegerField()
    snapshot = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['draft', 'number'], name='unique_studio_release_number')]


class PublishedAsset(models.Model):
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT)
    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE)
    is_cover = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['asset','course'], name='unique_release_asset')]
