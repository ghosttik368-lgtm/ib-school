from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render

from courses.models import Course, Enrollment
from courses.services import ensure_default_directions


@login_required
def home(request):
    ensure_default_directions()
    enrollments = Enrollment.objects.filter(user=request.user)
    enrollment_map = {item.course_id: item for item in enrollments}
    from studio.models import Release
    family_enrollments = {}
    for release in Release.objects.filter(course_id__in=enrollment_map):
        family_enrollments.setdefault(release.draft_id, enrollment_map[release.course_id])
    course_families = dict(Release.objects.values_list('course_id','draft_id'))

    courses = list(
        Course.objects.filter(status=Course.Status.PUBLISHED, is_listed=True)
        .select_related("direction", "created_by")
        .annotate(lessons_total=Count("modules__lessons", distinct=True))
        .order_by("-published_at", "title")
    )
    for course in courses:
        course.user_enrollment = enrollment_map.get(course.id) or family_enrollments.get(course_families.get(course.id))

    return render(
        request,
        "core/home.html",
        {
            "courses": courses,
            "directions": sorted({course.direction for course in courses}, key=lambda d: d.name),
            "active_section": "courses",
        },
    )
