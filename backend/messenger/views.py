from functools import wraps
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import JsonResponse, FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from .models import Room, Member, Message
from . import services


def api(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            if request.method == 'POST' and int(request.META.get('CONTENT_LENGTH') or 0) > 11 * 1024 * 1024:
                return JsonResponse({'error':'Файл слишком большой: максимум 10 МБ.'}, status=413)
            return view(request, *args, **kwargs)
        except (ValidationError, ValueError, TypeError) as exc:
            return JsonResponse({'error':'; '.join(exc.messages) if isinstance(exc, ValidationError) else 'Проверьте введённые данные.'}, status=400)
    return wrapped


def room_title(room, user):
    if room.kind != 'direct':
        return room.title
    other = next((m.user for m in room.members.all() if m.user_id != user.pk), None)
    return other.username if other else 'Удалённый аккаунт'


def packed(message, user):
    deleted = bool(message.deleted_at)
    reply = message.reply_to
    return {
        'id':message.pk, 'mine':message.sender_id == user.pk, 'sender':message.sender.username if message.sender else 'Удалённый аккаунт',
        'text':'' if deleted else message.text, 'created':message.created_at.isoformat(), 'edited':bool(message.edited_at),
        'deleted':deleted, 'revision':message.revision,
        'file':{'name':message.filename, 'size':message.size, 'url':reverse('messenger:file', args=[message.pk])} if message.attachment and not deleted else None,
        'reply':{'id':reply.pk, 'sender':reply.sender.username if reply.sender else 'Удалённый аккаунт', 'text':'Сообщение удалено' if reply.deleted_at else (reply.text or reply.filename)[:180]} if reply and not deleted else None,
    }


@login_required
@require_GET
def home(request):
    services.join_lobby(request.user)
    return render(request, 'messenger/home.html', {'active_section':'chat'})


@api
@require_GET
def people(request):
    query = request.GET.get('q', '').strip()[:100]
    users = get_user_model().objects.filter(is_active=True).exclude(pk=request.user.pk).order_by('username')
    if query:
        users = users.filter(username__icontains=query)
    return JsonResponse({'users':[{'id':u.pk, 'name':u.username, 'role':u.role_label} for u in users[:30]]})


@api
@require_GET
def rooms(request):
    memberships = Member.objects.filter(user=request.user, active=True).select_related('room').prefetch_related('room__members__user')
    query = request.GET.get('q', '').strip()[:100]
    if query:
        memberships = memberships.filter(Q(room__title__icontains=query) | Q(room__kind='direct', room__members__user__username__icontains=query)).distinct()
    page = Paginator(memberships.order_by('-room__updated_at', '-room_id'), 30).get_page(request.GET.get('page'))
    rows = []
    for m in page:
        latest = m.room.messages.order_by('-id').first()
        unread = m.room.messages.filter(id__gt=m.last_read_id, deleted_at__isnull=True).exclude(sender=request.user).count()
        rows.append({'id':m.room_id, 'kind':m.room.kind, 'title':room_title(m.room, request.user), 'muted':m.muted, 'unread':unread,
                     'preview':'Сообщение удалено' if latest and latest.deleted_at else (latest.text or latest.filename)[:90] if latest else 'Начните разговор',
                     'updated':m.room.updated_at.isoformat()})
    return JsonResponse({'rooms':rows, 'page':page.number, 'pages':page.paginator.num_pages})


@api
@require_POST
def create(request):
    room = services.create_room(request.user, request.POST.get('kind'), request.POST.get('title',''), request.POST.getlist('users'))
    return JsonResponse({'id':room.pk})


@api
@require_GET
def history(request, pk):
    member = services.access(request.user, pk)
    room = member.room
    before = max(0, int(request.GET.get('before', 0)))
    since = max(0, int(request.GET.get('since', 0)))
    messages = room.messages.select_related('sender', 'reply_to__sender')
    reset = False
    if before:
        selected = list(messages.filter(pk__lt=before).order_by('-id')[:50])[::-1]
    elif since:
        # Snapshot version is read before messages; a concurrent update is sent again next poll.
        changed = messages.filter(change_seq__gt=since).order_by('change_seq', 'id')
        reset = changed.count() > 150 or since > room.version
        selected = list(messages.order_by('-id')[:50])[::-1] if reset else list(changed[:150])
    else:
        selected = list(messages.order_by('-id')[:50])[::-1]
    members = list(room.members.select_related('user').filter(active=True, user__is_active=True))
    return JsonResponse({'messages':[packed(m,request.user) for m in selected], 'version':room.version, 'reset':reset,
        'has_older':bool(selected) and room.messages.filter(pk__lt=selected[0].pk).exists() if not since or before or reset else False,
        'title':room_title(room,request.user), 'kind':room.kind, 'owner':room.owner_id == request.user.pk, 'muted':member.muted,
        'members':[{'id':m.user_id, 'name':m.user.username, 'owner':m.user_id == room.owner_id, 'read':m.last_read_id} for m in members],
        'last_id':room.messages.order_by('-id').values_list('id',flat=True).first() or 0})


@api
@require_POST
def send(request, pk):
    services.access(request.user, pk)
    if len(request.FILES) > 1:
        raise ValidationError('Можно прикрепить один файл к сообщению.')
    message = services.send(request.user, pk, request.POST.get('text',''), request.POST.get('key'), request.POST.get('reply'), request.FILES.get('file'))
    return JsonResponse({'message':packed(message, request.user)})


@api
@require_POST
def edit(request, pk):
    message = services.change_message(request.user, pk, int(request.POST.get('revision', 0)), request.POST.get('text'), request.POST.get('delete') == '1')
    return JsonResponse({'message':packed(message, request.user)})


@api
@require_POST
def read(request, pk):
    with transaction.atomic():
        services.lock_room(pk)
        member = services.access(request.user, pk)
        last = get_object_or_404(Message, room_id=pk, pk=int(request.POST.get('last', 0)))
        Member.objects.filter(pk=member.pk, last_read_id__lt=last.pk).update(last_read_id=last.pk)
    return JsonResponse({'ok':True})


@api
@require_POST
def members(request, pk):
    services.manage_members(request.user, pk, request.POST.get('action'), request.POST.get('user'), request.POST.get('title',''))
    return JsonResponse({'ok':True})


@login_required
@require_GET
def file(request, pk):
    message = get_object_or_404(Message, pk=pk, deleted_at__isnull=True)
    services.access(request.user, message.room_id)
    if not message.attachment:
        raise Http404
    try:
        response = FileResponse(message.attachment.open('rb'), as_attachment=True, filename=message.filename, content_type='application/octet-stream')
    except FileNotFoundError:
        raise Http404
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@api
@require_GET
def notifications(request):
    from teaching.models import Notice
    memberships = Member.objects.filter(user=request.user, active=True, muted=False).annotate(unread=Count('room__messages', filter=Q(room__messages__id__gt=F('last_read_id'), room__messages__deleted_at__isnull=True) & ~Q(room__messages__sender=request.user)))
    chat_count = sum(m.unread for m in memberships)
    notices = Notice.objects.filter(user=request.user).order_by('-created_at','-id')
    return JsonResponse({'chat_count':chat_count, 'notice_count':notices.filter(read_at__isnull=True).count(),
        'notices':[{'id':n.pk, 'text':n.text, 'read':bool(n.read_at), 'url':reverse('teaching:assigned')} for n in notices[:20]]})


@api
@require_POST
def notices_read(request):
    from teaching.models import Notice
    # Only IDs actually rendered by this client; concurrent arrivals stay unread.
    ids = [int(x) for x in request.POST.getlist('ids')[:20]]
    Notice.objects.filter(user=request.user, pk__in=ids, read_at__isnull=True).update(read_at=timezone.now())
    return JsonResponse({'ok':True})
