import hashlib
import json
import uuid
from datetime import timedelta
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from learning.services import lock_user
from .models import Room, Member, Message

MAX_FILE = 10 * 1024 * 1024
EXTENSIONS = {'.pdf', '.txt', '.md', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.csv', '.png', '.jpg', '.jpeg', '.webp', '.zip', '.cpp', '.h', '.hpp', '.c', '.py'}


def access(user, room_id):
    if not user.is_active:
        raise PermissionDenied
    return get_object_or_404(Member.objects.select_related('room'), user=user, room_id=room_id, active=True)


@transaction.atomic
def join_lobby(user):
    lock_user(user)
    room, _ = Room.objects.get_or_create(key='lobby', defaults={'kind':'common', 'title':'Общий чат'})
    Member.objects.get_or_create(room=room, user=user)
    return room


def bump(room):
    room.version += 1
    room.updated_at = timezone.now()
    room.save(update_fields=['version', 'updated_at'])
    return room.version


def lock_room(room_id):
    # First statement is a write: also serializes writers on SQLite.
    Room.objects.filter(pk=room_id).update(version=F('version'))
    return get_object_or_404(Room.objects.select_for_update(), pk=room_id)


@transaction.atomic
def create_room(user, kind, title, ids):
    lock_user(user)
    if not user.is_active or kind not in ('direct', 'group'):
        raise PermissionDenied
    try:
        ids = {int(x) for x in ids} - {user.pk}
    except (ValueError, TypeError):
        raise ValidationError('Выберите участников.')
    if not ids or len(ids) > 99 or (kind == 'direct' and len(ids) != 1):
        raise ValidationError('Личный чат — с одним человеком, группа — до 100 участников.')
    users = list(get_user_model().objects.filter(pk__in=ids, is_active=True))
    if len(users) != len(ids):
        raise ValidationError('Один из выбранных пользователей недоступен.')
    title = title.strip()
    if kind == 'group' and not 1 <= len(title) <= 120:
        raise ValidationError('Введите название группы: до 120 символов.')
    if Room.objects.filter(owner=user, created_at__gte=timezone.now()-timedelta(hours=1)).count() >= 20:
        raise ValidationError('Слишком много новых чатов. Попробуйте через час.')
    key = 'dm:' + ':'.join(map(str, sorted(ids | {user.pk}))) if kind == 'direct' else None
    if key:
        # Unique key handles the race when both people open the same dialogue.
        room, _ = Room.objects.get_or_create(key=key, defaults={'kind':kind, 'owner':user})
    else:
        room = Room.objects.create(kind=kind, title=title, owner=user)
    for person in [user] + users:
        Member.objects.get_or_create(room=room, user=person)
    return room


def file_info(upload):
    if upload is None:
        return '', 0, ''
    name = Path(upload.name.replace('\\', '/')).name
    if not name or len(name) > 200 or any(ord(c) < 32 for c in name) or Path(name).suffix.lower() not in EXTENSIONS:
        raise ValidationError('Разрешены документы, изображения, ZIP и исходники C/C++/Python. Имя файла — до 200 символов.')
    if not 0 < upload.size <= MAX_FILE:
        raise ValidationError('Размер файла должен быть от 1 байта до 10 МБ.')
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return name, upload.size, digest.hexdigest()


def send(user, room_id, text, key, reply_id=None, upload=None):
    text = text.strip()
    if len(text) > 4000 or (not text and not upload):
        raise ValidationError('Напишите сообщение до 4000 символов или прикрепите файл.')
    try:
        key = uuid.UUID(str(key))
        reply_id = int(reply_id) if reply_id else None
    except (ValueError, TypeError):
        raise ValidationError('Некорректный идентификатор сообщения.')
    name, size, digest = file_info(upload)
    fingerprint = hashlib.sha256(json.dumps([room_id, text, reply_id, name, size, digest], ensure_ascii=False).encode()).hexdigest()
    stored = None
    try:
        with transaction.atomic():
            lock_user(user)
            room = lock_room(room_id)
            access(user, room_id)
            old = Message.objects.filter(sender=user, request_key=key).first()
            if old:
                if old.payload_hash != fingerprint:
                    raise ValidationError('Этот запрос уже отправлен с другим содержимым. Обновите страницу.')
                return old
            if Message.objects.filter(sender=user, created_at__gte=timezone.now()-timedelta(minutes=1)).count() >= 30:
                raise ValidationError('Не больше 30 сообщений в минуту. Подождите немного.')
            if size and (Message.objects.filter(sender=user, deleted_at__isnull=True).aggregate(n=Sum('size'))['n'] or 0) + size > 100 * 1024 * 1024:
                raise ValidationError('Лимит ваших вложений — 100 МБ. Удалите ненужные сообщения с файлами.')
            reply = get_object_or_404(Message, pk=reply_id, room=room, deleted_at__isnull=True) if reply_id else None
            message = Message(room=room, sender=user, text=text, request_key=key, payload_hash=fingerprint, reply_to=reply, filename=name, size=size, change_seq=bump(room))
            if upload:
                message.attachment.save(name, upload, save=False)
                stored = (message.attachment.storage, message.attachment.name)
            message.save()
            return message
    except Exception:
        if stored:
            stored[0].delete(stored[1])
        raise


@transaction.atomic
def change_message(user, pk, revision, text=None, delete=False):
    initial = get_object_or_404(Message, pk=pk)
    room = lock_room(initial.room_id)
    access(user, room.pk)
    message = Message.objects.get(pk=pk)
    if message.sender_id != user.pk:
        raise PermissionDenied
    if message.revision != revision or message.deleted_at:
        raise ValidationError('Сообщение уже изменено. Обновите чат.')
    if delete:
        message.deleted_at = timezone.now()
        message.text = ''
        if message.attachment:
            storage, name = message.attachment.storage, message.attachment.name
            transaction.on_commit(lambda: storage.delete(name))
        message.attachment, message.filename, message.size = '', '', 0
    else:
        text = (text or '').strip()
        if len(text) > 4000 or (not text and not message.attachment):
            raise ValidationError('Напишите сообщение до 4000 символов.')
        message.text, message.edited_at = text, timezone.now()
    message.revision += 1
    message.change_seq = bump(room)
    message.save()
    # Reply previews must refresh in clients too, even for older loaded messages.
    Message.objects.filter(reply_to=message).update(change_seq=room.version)
    return message


@transaction.atomic
def manage_members(user, room_id, action, target=None, title=''):
    room = lock_room(room_id)
    member = access(user, room_id)
    if action == 'mute':
        member.muted = not member.muted
        member.save(update_fields=['muted'])
        return
    if room.kind != 'group':
        raise ValidationError('Состав личного и общего чата менять нельзя.')
    if action == 'leave':
        if room.owner_id == user.pk:
            raise ValidationError('Сначала передайте управление другому участнику.')
        member.active = False
        member.save(update_fields=['active'])
    else:
        if room.owner_id != user.pk:
            raise PermissionDenied
        if action == 'rename':
            if not 1 <= len(title.strip()) <= 120:
                raise ValidationError('Название — от 1 до 120 символов.')
            room.title = title.strip()
            room.save(update_fields=['title'])
        elif action in ('add', 'remove', 'transfer'):
            try:
                target = int(target)
            except (ValueError, TypeError):
                raise ValidationError('Выберите участника.')
            if target == user.pk:
                raise ValidationError('Выберите другого участника.')
            person = get_object_or_404(get_user_model(), pk=target, is_active=True)
            if action == 'add':
                if room.members.filter(active=True).count() >= 100:
                    raise ValidationError('В чате уже 100 участников.')
                Member.objects.update_or_create(room=room, user=person, defaults={'active':True})
            else:
                other = get_object_or_404(Member, room=room, user=person, active=True)
                if action == 'remove':
                    other.active = False
                    other.save(update_fields=['active'])
                else:
                    room.owner = person
                    room.save(update_fields=['owner'])
        else:
            raise ValidationError('Неизвестное действие.')
    bump(room)
