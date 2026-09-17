import uuid
from django.conf import settings
from django.db import models


class Task(models.Model):
    material = models.OneToOneField('courses.Material', on_delete=models.CASCADE, related_name='practice_task')
    statement = models.TextField()
    input_format = models.TextField(blank=True)
    output_format = models.TextField(blank=True)
    examples = models.TextField(blank=True)
    starter = models.TextField(blank=True)
    solution = models.TextField(blank=True)
    tests = models.JSONField(default=list)
    time_limit = models.PositiveSmallIntegerField(default=2)
    memory_limit = models.PositiveSmallIntegerField(default=128)


class Workspace(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    material = models.ForeignKey('courses.Material', on_delete=models.CASCADE)
    code = models.TextField(blank=True)
    stdin = models.TextField(blank=True)
    revision = models.PositiveIntegerField(default=0)
    video_position = models.FloatField(default=0)
    video_revision = models.PositiveIntegerField(default=0)
    touched_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'material'], name='unique_learning_workspace')]


class Submission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    task = models.ForeignKey(Task, on_delete=models.PROTECT)
    mode = models.CharField(max_length=10, default='check')
    code = models.TextField()
    stdin = models.TextField(blank=True)
    request_key = models.UUIDField()
    status = models.CharField(max_length=20, default='queued', db_index=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    lease_until = models.DateTimeField(null=True)
    claim_token = models.UUIDField(null=True)
    task_snapshot = models.JSONField(default=dict)
    retries = models.PositiveSmallIntegerField(default=0)
    retry_after = models.DateTimeField(null=True)
    diagnostic = models.TextField(blank=True)
    stdout = models.TextField(blank=True)
    passed_tests = models.PositiveIntegerField(default=0)
    total_tests = models.PositiveIntegerField(default=0)
    class Meta:
        ordering = ['-submitted_at']
        constraints = [models.UniqueConstraint(fields=['user', 'request_key'], name='unique_submission_request')]


class Worker(models.Model):
    name = models.CharField(max_length=100, primary_key=True)
    heartbeat = models.DateTimeField()
