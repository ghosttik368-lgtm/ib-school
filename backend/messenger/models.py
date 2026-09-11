import uuid
from pathlib import Path
from django.conf import settings
from django.db import models


def attachment_path(instance, name):
    return f'messenger/{instance.room_id}/{uuid.uuid4().hex}{Path(name).suffix.lower()}'


class Room(models.Model):
    kind = models.CharField(max_length=10, default='group')
    key = models.CharField(max_length=100, null=True, blank=True, unique=True)
    title = models.CharField(max_length=120, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    version = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)


class Member(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_memberships')
    active = models.BooleanField(default=True)
    muted = models.BooleanField(default=False)
    last_read_id = models.PositiveBigIntegerField(default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['room', 'user'], name='chat_unique_member')]


class Message(models.Model):
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='sent_messages')
    text = models.TextField(max_length=4000, blank=True)
    attachment = models.FileField(upload_to=attachment_path, blank=True)
    filename = models.CharField(max_length=200, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    request_key = models.UUIDField(default=uuid.uuid4)
    payload_hash = models.CharField(max_length=64, blank=True)
    reply_to = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    change_seq = models.PositiveBigIntegerField(default=0)
    legacy_id = models.PositiveBigIntegerField(null=True, unique=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['sender', 'request_key'], name='chat_idempotent_send')]
        indexes = [models.Index(fields=['room', 'change_seq'], name='chat_room_changes'), models.Index(fields=['room', 'id'], name='chat_room_history')]
