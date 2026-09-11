from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import (
    Course,
    Direction,
    Enrollment,
    Lesson,
    LessonProgress,
    ScoreAward,
    UserAchievement,
)


DEFAULT_DIRECTIONS = (
    ("Программирование", "Языки, алгоритмы и безопасная разработка"),
    ("Реверс-инжиниринг", "Исследование программ и бинарных файлов"),
    ("Криптография", "Криптографические методы и протоколы"),
    ("Сетевая безопасность", "Сети, анализ трафика и защита инфраструктуры"),
    ("Безопасность Windows", "Устройство и защита операционных систем Windows"),
)


def ensure_default_directions():
    for name, description in DEFAULT_DIRECTIONS:
        Direction.objects.get_or_create(
            name=name,
            defaults={"description": description, "is_active": True},
        )


def grant_achievement(user, code, title, description):
    UserAchievement.objects.get_or_create(
        user=user,
        code=code,
        defaults={"title": title, "description": description},
    )


@transaction.atomic
def recalculate_course_progress(user, course):
    enrollment, _ = Enrollment.objects.get_or_create(user=user, course=course)
    lesson_ids = list(
        Lesson.objects.filter(module__course=course, is_active=True).values_list(
            "id", flat=True
        )
    )
    total = len(lesson_ids)
    completed = LessonProgress.objects.filter(
        user=user, lesson_id__in=lesson_ids, completed=True
    ).count()
    percent = round(completed * 100 / total) if total else 0

    enrollment.progress_percent = percent
    if percent == 100 and total:
        enrollment.completed_at = enrollment.completed_at or timezone.now()
        grant_achievement(
            user,
            f"course_complete_{course.id}",
            "Курс завершён",
            f"Полностью пройден курс «{course.title}».",
        )
    else:
        enrollment.completed_at = None
    enrollment.save(update_fields=("progress_percent", "completed_at", "updated_at"))
    return enrollment


def recalculate_all_enrollments(course):
    for enrollment in course.enrollments.select_related("user"):
        recalculate_course_progress(enrollment.user, course)


@transaction.atomic
def award_quiz_points(user, quiz):
    course = quiz.material.lesson.module.course
    award, created = ScoreAward.objects.get_or_create(
        user=user,
        quiz=quiz,
        defaults={"course": course, "points": quiz.points},
    )

    if created:
        grant_achievement(
            user,
            "first_test",
            "Первый зачёт",
            "Первый тест пройден без ошибок.",
        )
        total_points = ScoreAward.objects.filter(user=user).aggregate(
            total=Coalesce(Sum("points"), 0)
        )["total"]
        if total_points >= 25:
            grant_achievement(
                user,
                "points_25",
                "Уверенный старт",
                "Набрано 25 баллов на платформе.",
            )
        if total_points >= 100:
            grant_achievement(
                user,
                "points_100",
                "Сотня",
                "Набрано 100 баллов на платформе.",
            )

    return award, created
