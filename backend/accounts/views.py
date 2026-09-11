from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render

from courses.models import Enrollment, ScoreAward

from .forms import RegisterForm


def register(request):
    from access.views import register as invited_register
    return invited_register(request)


def _unused_legacy_register(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("home")
    else:
        form = RegisterForm()

    return render(request, "registration/register.html", {"form": form})


@login_required
def profile(request):
    enrollments = Enrollment.objects.filter(
        user=request.user, course__status="published"
    ).select_related("course", "course__direction")
    from learning.models import BlockProgress
    total_points = BlockProgress.objects.filter(user=request.user, completed_at__isnull=False, material__lesson__module__course__status='published').count()

    return render(
        request,
        "accounts/profile.html",
        {
            "enrollments": enrollments,
            "total_points": total_points,
            "achievements": request.user.achievements.all(),
            "active_section": "profile",
        },
    )
