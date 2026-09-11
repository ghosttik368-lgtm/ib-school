import json
from pathlib import Path
from functools import wraps
from PIL import Image
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.http import JsonResponse, FileResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from courses.models import Course, Direction, Enrollment
from courses.services import ensure_default_directions
from access.services import audit
from .models import Draft, Asset, PublishedAsset
from .content import blank, normalize, problems
from .services import import_legacy, import_course, publish
from .media import file_response


def manager(view):
    @login_required
    @wraps(view)
    def wrapped(request,*args,**kwargs):
        if not request.user.can_manage_courses:raise PermissionDenied
        try:return view(request,*args,**kwargs)
        except ValidationError as exc:return JsonResponse({'error':' '.join(exc.messages)},status=400)
        except (json.JSONDecodeError,UnicodeDecodeError,TypeError,ValueError,KeyError,AttributeError):
            return JsonResponse({'error':'Некорректный запрос. Обновите страницу и повторите.'},status=400)
    return wrapped


def owned(request,pk):
    draft=get_object_or_404(Draft,pk=pk)
    if not request.user.is_platform_admin and draft.owner_id!=request.user.pk:raise PermissionDenied
    return draft


def packet(draft):
    return {'id':draft.pk,'data':draft.data,'revision':draft.revision,'published_revision':draft.published_revision,'archived':draft.archived,'published_url':draft.latest_course.get_absolute_url() if draft.latest_course_id else None,'assets':[{'id':a.pk,'name':a.name,'url':f'/studio/assets/{a.pk}/','size':a.size} for a in draft.assets.all()], 'updated':draft.updated_at.isoformat()}


def body(request):
    if int(request.META.get('CONTENT_LENGTH') or 0)>3*1024*1024:raise ValidationError('Черновик слишком большой (максимум 3 МБ).')
    if len(request.body)>3*1024*1024:raise ValidationError('Черновик слишком большой (максимум 3 МБ). Разделите курс.')
    data=json.loads(request.body)
    if not isinstance(data,dict):raise ValidationError('Неверный запрос.')
    return data


def conflict():return JsonResponse({'error':'Курс уже изменён в другой вкладке. Скачайте свои правки и загрузите актуальную версию.','conflict':True},status=409)


@manager
def dashboard(request):
    ensure_default_directions()
    if request.GET.get('course','').isdigit():
        course=get_object_or_404(Course,pk=int(request.GET['course']))
        if not request.user.is_platform_admin and course.created_by_id!=request.user.pk:raise PermissionDenied
        draft=import_course(course)
        return redirect('studio:editor',pk=draft.pk)
    import_legacy(request.user)
    drafts=Draft.objects.all() if request.user.is_platform_admin else Draft.objects.filter(owner=request.user)
    return render(request,'studio/dashboard.html',{'drafts':drafts.select_related('latest_course').order_by('-updated_at'),'active_section':'management'})


@manager
@require_POST
def create(request):
    data=blank()
    draft=Draft.objects.create(owner=request.user,data=data,title=data['title'])
    audit('Черновик курса создан',actor=request.user,detail=str(draft.pk))
    return JsonResponse({'url':f'/studio/{draft.pk}/?wizard=1'})


@manager
def editor(request,pk):
    draft=owned(request,pk)
    return render(request,'studio/editor.html',{'packet':packet(draft),'directions':list(Direction.objects.filter(is_active=True).values('id','name')),'active_section':'management'})


@manager
@require_http_methods(['GET','POST'])
def save(request,pk):
    draft=owned(request,pk)
    if request.method=='GET':return JsonResponse(packet(draft))
    payload=body(request)
    normalized=normalize(payload['data'],draft)
    expected=payload['revision']
    if type(expected)!=int:raise ValidationError('Не указан номер редакции.')
    with transaction.atomic():
        from autoquiz.services import locked_draft, sync_videos
        current=locked_draft(pk)
        if current.revision!=expected:return conflict()
        if current.data==normalized:return JsonResponse({'revision':expected,'updated':current.updated_at.isoformat()})
        now=timezone.now()
        if not Draft.objects.filter(pk=pk,revision=expected).update(data=normalized,title=normalized['title'] or 'Без названия',revision=F('revision')+1,updated_at=now):return conflict()
        current.data=normalized
        sync_videos(current,request.user)
    return JsonResponse({'revision':expected+1,'updated':now.isoformat()})


@manager
@require_POST
def validate(request,pk):
    draft=owned(request,pk)
    return JsonResponse({'errors':problems(draft.data),'revision':draft.revision})


@manager
@require_POST
def publish_course(request,pk):
    owned(request,pk);payload=body(request)
    with transaction.atomic():
        draft=Draft.objects.select_for_update().get(pk=pk)
        if payload.get('revision')!=draft.revision:return conflict()
        if draft.archived:return JsonResponse({'error':'Сначала верните курс из архива.'},status=400)
        errors=problems(draft.data)
        if errors:return JsonResponse({'errors':errors,'error':'Исправьте замечания перед публикацией.'},status=400)
        if draft.latest_course_id and draft.published_revision==draft.revision:
            return JsonResponse({'url':draft.latest_course.get_absolute_url(),'revision':draft.revision})
        if not Draft.objects.filter(pk=pk,revision=draft.revision).update(revision=F('revision')+1):return conflict()
        draft.refresh_from_db()
        course=publish(draft)
        audit('Версия курса опубликована',actor=request.user,detail=f'Курс {course.pk}; черновик {pk}')
    return JsonResponse({'url':course.get_absolute_url(),'revision':draft.revision})


@manager
@require_POST
def archive(request,pk):
    owned(request,pk);payload=body(request)
    with transaction.atomic():
        draft=Draft.objects.select_for_update().get(pk=pk)
        if payload.get('revision')!=draft.revision:return conflict()
        if not Draft.objects.filter(pk=pk,revision=draft.revision).update(archived=not draft.archived,revision=F('revision')+1):return conflict()
        if draft.latest_course_id:Course.objects.filter(pk=draft.latest_course_id).update(is_listed=draft.archived)
        audit('Курс возвращён из архива' if draft.archived else 'Курс архивирован',actor=request.user,detail=str(pk))
    return JsonResponse({'ok':True})


@manager
@require_POST
def upload(request,pk):
    draft=owned(request,pk)
    file=request.FILES.get('file')
    if not file:raise ValidationError('Выберите файл.')
    suffix=Path(file.name).suffix.lower()
    if suffix not in {'.mp4','.webm','.pdf','.ppt','.pptx','.doc','.docx','.jpg','.jpeg','.png','.webp'}:raise ValidationError('Этот формат не поддерживается. Видео: MP4/WebM; документы: PDF, DOC/DOCX, PPT/PPTX; изображения: JPG/PNG/WebP.')
    if file.size>500*1024*1024:raise ValidationError('Максимум 500 МБ на файл.')
    if suffix in {'.jpg','.jpeg','.png','.webp'}:
        if file.size>10*1024*1024:raise ValidationError('Изображение должно быть не больше 10 МБ.')
        try:
            image=Image.open(file)
            if image.width*image.height>30_000_000:raise ValueError()
            image.verify();file.seek(0)
        except Exception:raise ValidationError('Не удалось прочитать изображение.')
    asset=Asset.objects.create(draft=draft,file=file,name=Path(file.name).name[:240],size=file.size)
    return JsonResponse({'id':asset.pk,'name':asset.name,'url':f'/studio/assets/{asset.pk}/','size':asset.size})


@login_required
def asset_file(request,pk):
    asset=get_object_or_404(Asset.objects.select_related('draft'),pk=pk)
    allowed=request.user.is_platform_admin or (request.user.can_manage_courses and asset.draft.owner_id==request.user.pk)
    if not allowed:
        allowed=PublishedAsset.objects.filter(asset=asset,course__status='published').filter(Q(is_cover=True)|Q(course__enrollments__user=request.user)).exists()
    if not allowed:raise Http404
    try:return file_response(request,asset.file.path,asset.name)
    except (FileNotFoundError,OSError):raise Http404


@manager
def preview(request,pk):
    draft=owned(request,pk)
    # No answers, hidden tests or reference solution enter the preview payload.
    import copy
    data=copy.deepcopy(draft.data)
    for s in data['sections']:
        s['lessons']=[lesson for lesson in s['lessons'] if lesson.get('active',True)]
        for l in s['lessons']:
            for st in l['steps']:
                for q in st['questions']:
                    q.pop('answers',None);q.pop('explanation',None)
                    for c in q['choices']:c.pop('correct',None)
                st['code'].pop('solution',None);st['code'].pop('tests',None)
    return render(request,'studio/preview.html',{'course_data':data,'draft':draft,'active_section':'management'})
