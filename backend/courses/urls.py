from django.urls import path

from . import views
from learning import views as learning_views
from practice import views as practice_views


app_name = "courses"

urlpatterns = [
    path("courses/<str:slug>/", views.course_detail, name="course_detail"),
    path("courses/<str:slug>/enroll/", views.enroll_course, name="enroll_course"),
    path("lessons/<int:lesson_id>/", learning_views.lesson_detail, name="lesson_detail"),
    path(
        "lessons/<int:lesson_id>/complete/",
        learning_views.complete_lesson,
        name="complete_lesson",
    ),
    path("quizzes/<int:quiz_id>/submit/", learning_views.submit_quiz, name="submit_quiz"),
    path("library/", practice_views.library, name="library"),
    path("rating/", learning_views.leaderboard, name="leaderboard"),
    path("chat/", views.chat, name="chat"),
    path("management/", views.management_dashboard, name="management_dashboard"),
    path("management/courses/create/", views.course_create, name="course_create"),
    path(
        "management/courses/publish/", views.course_publish, name="course_publish"
    ),
    path(
        "management/courses/<int:course_id>/update/",
        views.course_update,
        name="course_update",
    ),
    path(
        "management/courses/<int:course_id>/unpublish/",
        views.course_unpublish,
        name="course_unpublish",
    ),
    path(
        "management/courses/<int:course_id>/delete/",
        views.course_delete,
        name="course_delete",
    ),
    path(
        "management/courses/<int:course_id>/lessons/create/",
        views.lesson_create,
        name="lesson_create",
    ),
    path(
        "management/lessons/<int:lesson_id>/update/",
        views.lesson_update,
        name="lesson_update",
    ),
    path(
        "management/lessons/<int:lesson_id>/delete/",
        views.lesson_delete,
        name="lesson_delete",
    ),
    path(
        "management/lessons/<int:lesson_id>/materials/create/",
        views.material_create,
        name="material_create",
    ),
    path(
        "management/materials/<int:material_id>/update/",
        views.material_update,
        name="material_update",
    ),
    path(
        "management/materials/<int:material_id>/delete/",
        views.material_delete,
        name="material_delete",
    ),
    path(
        "management/materials/<int:material_id>/questions/create/",
        views.question_create,
        name="question_create",
    ),
    path(
        "management/questions/<int:question_id>/delete/",
        views.question_delete,
        name="question_delete",
    ),
]
