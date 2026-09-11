from pathlib import Path
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404
from courses.models import Course, Material


@login_required
def protected_media(request, path):
    filters = Q(status='published')
    if request.user.can_manage_courses: filters |= Q(created_by=request.user)
    if request.user.is_platform_admin: filters = Q()
    allowed = Course.objects.filter(filters, cover=path).exists()
    materials=Material.objects.filter(file=path)
    access=Q(lesson__module__course__status='published',lesson__is_active=True,lesson__module__course__enrollments__user=request.user)
    if request.user.can_manage_courses:access|=Q(lesson__module__course__created_by=request.user)
    if request.user.is_platform_admin:access=Q()
    allowed=allowed or materials.filter(access).exists()
    if path and path == str(request.user.avatar): allowed = True
    root = Path(settings.MEDIA_ROOT).resolve()
    filename = (root / path).resolve()
    if not allowed or not filename.is_relative_to(root) or not filename.is_file(): raise Http404
    from studio.media import file_response
    return file_response(request,filename,filename.name)
