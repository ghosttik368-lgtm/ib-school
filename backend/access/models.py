from django.conf import settings
from django.db import models
from django.utils import timezone


class AccountSecurity(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='security')
    version = models.PositiveIntegerField(default=1)
    secret_encrypted = models.TextField(blank=True)
    enabled = models.BooleanField(default=False)
    last_counter = models.BigIntegerField(default=-1)


class RecoveryCode(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    digest = models.CharField(max_length=64, unique=True)
    used_at = models.DateTimeField(null=True)


class Invitation(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='issued_invites')
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    used_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='used_invites')
    used_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)

    @property
    def status_label(self):
        if self.revoked_at: return 'Отозвано'
        if self.used_at: return 'Использовано'
        if self.expires_at <= timezone.now(): return 'Истекло'
        return 'Действует'


class ResetGrant(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='audit_actions')
    subject = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='audit_subjects')
    action = models.CharField(max_length=120)
    detail = models.CharField(max_length=220, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ('-created_at', '-id')


class RateBucket(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)
