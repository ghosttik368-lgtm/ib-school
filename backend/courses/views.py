from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, IntegerField, Max, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    ChatMessageForm,
    CourseEditForm,
    CourseWizardForm,
    LessonEditForm,
    MaterialForm,
    QuestionCreateForm,
)
from .models import (
    AnswerChoice,
    ChatMessage,
    Course,
    Direction,
    Enrollment,
    Lesson,
    LessonProgress,
    Material,
    Module,
    Question,
    Quiz,
    QuizAttempt,
    ScoreAward,
)
from .services import (
    award_quiz_points,
    ensure_default_directions,
    recalculate_all_enrollments,
    recalculate_course_progress,
)


def management_required(view_func):
    @login_required(login_url="login")
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not getattr(request.user, "can_manage_courses", False):
            raise PermissionDenied
        owner = None
        if 'course_id' in kwargs: owner = get_object_or_404(Course, pk=kwargs['course_id'])
        elif 'lesson_id' in kwargs: owner = get_object_or_404(Lesson, pk=kwargs['lesson_id']).module.course
        elif 'material_id' in kwargs: owner = get_object_or_404(Material, pk=kwargs['material_id']).lesson.module.course
        elif 'question_id' in kwargs: owner = get_object_or_404(Question, pk=kwargs['question_id']).quiz.material.lesson.module.course
        elif view_func.__name__ == 'course_publish' and request.method == 'POST':
            value = request.POST.get('course_id', '')
            if not value.isdigit(): raise PermissionDenied
            owner = get_object_or_404(Course, pk=int(value))
        elif view_func.__name__ == 'management_dashboard' and request.GET.get('course', '').isdigit():
            owner = get_object_or_404(Course, pk=int(request.GET['course']))
        if owner and not request.user.is_platform_admin and owner.created_by_id != request.user.pk: raise PermissionDenied
        if request.method == 'POST':
            from django.http import HttpResponse
            return HttpResponse('Редактор обновлён. Откройте /management/ и редактируйте черновик курса.', status=410)
        response = view_func(request, *args, **kwargs)
        if request.method == 'POST':
            from access.services import audit
            audit('Запрос изменения курса', actor=request.user, detail=view_func.__name__)
        return response

    return wrapped


def form_error_message(form):
    errors = []
    for field_name, error_list in form.errors.items():
        label = form.fields[field_name].label if field_name in form.fields else "Форма"
        errors.extend(f"{label}: {error}" for error in error_list)
    return " ".join(errors)


def management_redirect(course_id=None, lesson_id=None):
    url = reverse("courses:management_dashboard")
    params = {}
    if course_id:
        params["course"] = course_id
    if lesson_id:
        params["lesson"] = lesson_id
    return redirect(f"{url}?{urlencode(params)}" if params else url)


@management_required
def management_dashboard(request):
    ensure_default_directions()
    accessible = Course.objects.all() if request.user.is_platform_admin else Course.objects.filter(created_by=request.user)
    courses = list(
        accessible.select_related("direction", "created_by")
        .annotate(
            lessons_total=Count("modules__lessons", distinct=True),
            materials_total=Count("modules__lessons__materials", distinct=True),
        )
        .order_by("-updated_at")
    )
    drafts = [course for course in courses if course.status == Course.Status.DRAFT]

    selected_course = None
    selected_lesson = None
    lessons = []
    course_id = request.GET.get("course")
    lesson_id = request.GET.get("lesson")

    if course_id and course_id.isdigit():
        selected_course = get_object_or_404(
            Course.objects.select_related("direction", "created_by"), id=course_id
        )
        lessons = list(
            Lesson.objects.filter(module__course=selected_course)
            .annotate(materials_total=Count("materials"))
            .order_by("order", "id")
        )

    if selected_course and lesson_id and lesson_id.isdigit():
        selected_lesson = get_object_or_404(
            Lesson.objects.select_related("module", "module__course").prefetch_related(
                "materials__quiz__questions__choices"
            ),
            id=lesson_id,
            module__course=selected_course,
        )
        for material in selected_lesson.materials.all():
            if material.kind == Material.Kind.QUIZ:
                quiz, _ = Quiz.objects.get_or_create(
                    material=material, defaults={"passing_score": 100}
                )
                material._state.fields_cache["quiz"] = quiz
            material.edit_form = MaterialForm(
                instance=material, auto_id=f"material_{material.id}_%s"
            )

    context = {
        "courses": courses,
        "drafts": drafts,
        "directions": Direction.objects.filter(is_active=True),
        "selected_course": selected_course,
        "selected_lesson": selected_lesson,
        "lessons": lessons,
        "course_form": CourseWizardForm(),
        "course_edit_form": CourseEditForm(instance=selected_course)
        if selected_course
        else None,
        "lesson_form": LessonEditForm(instance=selected_lesson)
        if selected_lesson
        else None,
        "material_form": MaterialForm(),
        "question_form": QuestionCreateForm(),
        "active_section": "management",
    }
    return render(request, "courses/management/dashboard.html", context)


@management_required
@require_POST
def course_create(request):
    form = CourseWizardForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, form_error_message(form))
        return management_redirect()

    with transaction.atomic():
        course = form.save(commit=False)
        course.created_by = request.user
        course.status = Course.Status.DRAFT
        course.save()
        Module.objects.create(course=course, title="Основная программа", order=1)

    messages.success(request, "Черновик создан. Теперь добавьте уроки и материалы.")
    return management_redirect(course.id)


@management_required
@require_POST
def course_update(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    form = CourseEditForm(request.POST, request.FILES, instance=course)
    if form.is_valid():
        form.save()
        messages.success(request, "Настройки курса сохранены.")
    else:
        messages.error(request, form_error_message(form))
    return management_redirect(course.id)


@management_required
@require_POST
def course_publish(request):
    course_id = request.POST.get("course_id", "")
    course = get_object_or_404(Course, id=course_id, status=Course.Status.DRAFT)
    lessons = Lesson.objects.filter(module__course=course, is_active=True).prefetch_related(
        "materials__quiz__questions"
    )

    if not lessons.exists():
        messages.error(request, "Добавьте хотя бы один доступный урок перед публикацией.")
        return management_redirect(course.id)

    empty_lessons = [lesson.title for lesson in lessons if not lesson.materials.exists()]
    if empty_lessons:
        messages.error(
            request,
            f"Добавьте материалы в уроки: {', '.join(empty_lessons)}.",
        )
        return management_redirect(course.id)

    empty_quizzes = []
    for lesson in lessons:
        for material in lesson.materials.all():
            if material.kind == Material.Kind.QUIZ:
                quiz = getattr(material, "quiz", None)
                if quiz is None or not quiz.questions.exists():
                    empty_quizzes.append(material.title)
    if empty_quizzes:
        messages.error(
            request,
            f"Добавьте вопросы в тесты: {', '.join(empty_quizzes)}.",
        )
        return management_redirect(course.id)

    course.status = Course.Status.PUBLISHED
    course.published_at = timezone.now()
    course.save(update_fields=("status", "published_at", "updated_at"))
    messages.success(request, f"Курс «{course.title}» опубликован и виден студентам.")
    return management_redirect(course.id)


@management_required
@require_POST
def course_unpublish(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    course.status = Course.Status.DRAFT
    course.published_at = None
    course.save(update_fields=("status", "published_at", "updated_at"))
    messages.success(request, "Курс возвращён в черновики. Данные студентов сохранены.")
    return management_redirect(course.id)


@management_required
@require_POST
def course_delete(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    title = course.title
    course.delete()
    messages.success(request, f"Курс «{title}» удалён.")
    return management_redirect()


@management_required
@require_POST
def lesson_create(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    module = course.modules.order_by("order", "id").first()
    if module is None:
        module = Module.objects.create(
            course=course, title="Основная программа", order=1
        )
    last_order = (
        Lesson.objects.filter(module__course=course).aggregate(value=Max("order"))["value"]
        or 0
    )
    number = last_order + 1
    lesson = Lesson.objects.create(
        module=module,
        title=f"Урок {number}",
        order=number,
        duration_minutes=15,
    )
    recalculate_all_enrollments(course)
    messages.success(request, f"{lesson.title} добавлен.")
    return management_redirect(course.id, lesson.id)


@management_required
@require_POST
def lesson_update(request, lesson_id):
    lesson = get_object_or_404(Lesson.objects.select_related("module"), id=lesson_id)
    form = LessonEditForm(request.POST, instance=lesson)
    if form.is_valid():
        form.save()
        recalculate_all_enrollments(lesson.module.course)
        messages.success(request, "Урок сохранён.")
    else:
        messages.error(request, form_error_message(form))
    return management_redirect(lesson.module.course_id, lesson.id)


@management_required
@require_POST
def lesson_delete(request, lesson_id):
    lesson = get_object_or_404(Lesson.objects.select_related("module"), id=lesson_id)
    course = lesson.module.course
    course_id = course.id
    title = lesson.title
    lesson.delete()
    recalculate_all_enrollments(course)
    messages.success(request, f"{title} удалён.")
    return management_redirect(course_id)


@management_required
@require_POST
def material_create(request, lesson_id):
    lesson = get_object_or_404(
        Lesson.objects.select_related("module", "module__course"), id=lesson_id
    )
    form = MaterialForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, form_error_message(form))
        return management_redirect(lesson.module.course_id, lesson.id)

    with transaction.atomic():
        material = form.save(commit=False)
        material.lesson = lesson
        material.order = (lesson.materials.aggregate(value=Max("order"))["value"] or 0) + 1
        material.save()
        if material.kind == Material.Kind.QUIZ:
            Quiz.objects.create(material=material, passing_score=100)

    messages.success(request, f"Материал «{material.title}» добавлен.")
    return management_redirect(lesson.module.course_id, lesson.id)


@management_required
@require_POST
def material_delete(request, material_id):
    material = get_object_or_404(
        Material.objects.select_related("lesson", "lesson__module"), id=material_id
    )
    course_id = material.lesson.module.course_id
    lesson_id = material.lesson_id
    title = material.title
    material.delete()
    messages.success(request, f"Материал «{title}» удалён.")
    return management_redirect(course_id, lesson_id)


@management_required
@require_POST
def material_update(request, material_id):
    material = get_object_or_404(
        Material.objects.select_related("lesson", "lesson__module"), id=material_id
    )
    previous_kind = material.kind
    form = MaterialForm(request.POST, request.FILES, instance=material)
    if not form.is_valid():
        messages.error(request, form_error_message(form))
        return management_redirect(material.lesson.module.course_id, material.lesson_id)

    with transaction.atomic():
        material = form.save()
        if material.kind == Material.Kind.QUIZ:
            Quiz.objects.get_or_create(material=material, defaults={"passing_score": 100})
        elif previous_kind == Material.Kind.QUIZ:
            Quiz.objects.filter(material=material).delete()

    messages.success(request, f"Материал «{material.title}» обновлён.")
    return management_redirect(material.lesson.module.course_id, material.lesson_id)


@management_required
@require_POST
def question_create(request, material_id):
    material = get_object_or_404(
        Material.objects.select_related("lesson", "lesson__module"),
        id=material_id,
        kind=Material.Kind.QUIZ,
    )
    quiz, _ = Quiz.objects.get_or_create(material=material, defaults={"passing_score": 100})
    form = QuestionCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, form_error_message(form))
        return management_redirect(material.lesson.module.course_id, material.lesson_id)

    with transaction.atomic():
        order = (quiz.questions.aggregate(value=Max("order"))["value"] or 0) + 1
        question = Question.objects.create(
            quiz=quiz, text=form.cleaned_data["text"], order=order
        )
        correct_number = form.cleaned_data["correct_answer"]
        for number in range(1, 5):
            AnswerChoice.objects.create(
                question=question,
                text=form.cleaned_data[f"answer_{number}"],
                is_correct=number == correct_number,
                order=number,
            )

    messages.success(request, f"Вопрос {order} добавлен в тест.")
    return management_redirect(material.lesson.module.course_id, material.lesson_id)


@management_required
@require_POST
def question_delete(request, question_id):
    question = get_object_or_404(
        Question.objects.select_related(
            "quiz__material__lesson", "quiz__material__lesson__module"
        ),
        id=question_id,
    )
    material = question.quiz.material
    question.delete()
    messages.success(request, "Вопрос удалён.")
    return management_redirect(material.lesson.module.course_id, material.lesson_id)


@login_required
def course_detail(request, slug):
    course = get_object_or_404(
        Course.objects.select_related("direction", "created_by").prefetch_related(
            "modules__lessons__materials"
        ),
        slug=slug,
        status=Course.Status.PUBLISHED,
    )
    enrollment = Enrollment.objects.filter(user=request.user, course=course).first()
    completed_ids = set(
        LessonProgress.objects.filter(
            user=request.user,
            lesson__module__course=course,
            completed=True,
        ).values_list("lesson_id", flat=True)
    )
    lessons = list(
        Lesson.objects.filter(module__course=course, is_active=True)
        .annotate(materials_total=Count("materials"))
        .order_by("order", "id")
    )
    for lesson in lessons:
        lesson.is_completed_by_user = lesson.id in completed_ids

    return render(
        request,
        "courses/course_detail.html",
        {
            "course": course,
            "lessons": lessons,
            "enrollment": enrollment,
            "active_section": "courses",
        },
    )


@login_required
@require_POST
@transaction.atomic
def enroll_course(request, slug):
    from learning.services import lock_user
    lock_user(request.user)
    course = get_object_or_404(Course, slug=slug, status=Course.Status.PUBLISHED)
    from studio.models import Release
    release=Release.objects.filter(course=course).first()
    if release:
        previous=Enrollment.objects.filter(user=request.user,course__studio_release__draft=release.draft).select_related('course').first()
        if previous:return redirect(previous.course.get_absolute_url())
    if not course.is_listed:raise PermissionDenied
    enrollment, created = Enrollment.objects.get_or_create(user=request.user, course=course)
    if created:
        messages.success(request, f"Курс «{course.title}» добавлен в библиотеку.")
    return redirect(course.get_absolute_url())


@login_required
def library(request):
    enrollments = Enrollment.objects.filter(
        user=request.user, course__status=Course.Status.PUBLISHED
    ).select_related("course", "course__direction")
    return render(
        request,
        "courses/library.html",
        {"enrollments": enrollments, "active_section": "library"},
    )


@login_required
def lesson_detail(request, lesson_id):
    lesson = get_object_or_404(
        Lesson.objects.select_related("module", "module__course").prefetch_related(
            "materials__quiz__questions__choices"
        ),
        id=lesson_id,
        is_active=True,
        module__course__status=Course.Status.PUBLISHED,
    )
    course = lesson.module.course
    enrollment = get_object_or_404(Enrollment, user=request.user, course=course)
    progress = LessonProgress.objects.filter(user=request.user, lesson=lesson).first()

    materials = list(lesson.materials.all())
    for material in materials:
        if material.kind == Material.Kind.QUIZ:
            quiz, _ = Quiz.objects.get_or_create(
                material=material, defaults={"passing_score": 100}
            )
            material._state.fields_cache["quiz"] = quiz
            material.latest_attempt = (
                quiz.attempts.filter(user=request.user).first() if quiz else None
            )
            material.points_received = (
                ScoreAward.objects.filter(user=request.user, quiz=quiz).exists()
                if quiz
                else False
            )

    all_lessons = list(
        Lesson.objects.filter(module__course=course, is_active=True).order_by("order", "id")
    )
    index = next(i for i, item in enumerate(all_lessons) if item.id == lesson.id)
    previous_lesson = all_lessons[index - 1] if index > 0 else None
    next_lesson = all_lessons[index + 1] if index + 1 < len(all_lessons) else None

    return render(
        request,
        "courses/lesson_detail.html",
        {
            "course": course,
            "lesson": lesson,
            "materials": materials,
            "enrollment": enrollment,
            "progress": progress,
            "previous_lesson": previous_lesson,
            "next_lesson": next_lesson,
            "has_quiz": any(material.kind == Material.Kind.QUIZ and material.required for material in materials),
            "active_section": "library",
        },
    )


@login_required
@require_POST
def complete_lesson(request, lesson_id):
    lesson = get_object_or_404(
        Lesson.objects.select_related("module", "module__course"),
        id=lesson_id,
        is_active=True,
        module__course__status=Course.Status.PUBLISHED,
    )
    get_object_or_404(Enrollment, user=request.user, course=lesson.module.course)
    has_quiz = Quiz.objects.filter(material__lesson=lesson, material__required=True).exists()
    if has_quiz:
        messages.error(request, "Сначала пройдите все тесты этого урока.")
        return redirect("courses:lesson_detail", lesson_id=lesson.id)

    LessonProgress.objects.update_or_create(
        user=request.user,
        lesson=lesson,
        defaults={"completed": True, "completed_at": timezone.now()},
    )
    recalculate_course_progress(request.user, lesson.module.course)
    messages.success(request, "Урок отмечен как пройденный.")
    return redirect("courses:lesson_detail", lesson_id=lesson.id)


@login_required
@require_POST
def submit_quiz(request, quiz_id):
    quiz = get_object_or_404(
        Quiz.objects.select_related(
            "material__lesson", "material__lesson__module", "material__lesson__module__course"
        ).prefetch_related("questions__choices"),
        id=quiz_id,
        material__lesson__is_active=True,
        material__lesson__module__course__status=Course.Status.PUBLISHED,
    )
    lesson = quiz.material.lesson
    course = lesson.module.course
    get_object_or_404(Enrollment, user=request.user, course=course)

    questions = list(quiz.questions.all())
    if not questions:
        messages.error(request, "В этом тесте пока нет вопросов.")
        return redirect("courses:lesson_detail", lesson_id=lesson.id)

    correct_count = 0
    selected_answers = {}
    for question in questions:
        values = request.POST.getlist(f"question_{question.id}")
        selected_answers[str(question.id)] = values
        if question.kind == 'short':
            normalize = (lambda value: value.strip()) if question.case_sensitive else (lambda value: value.strip().casefold())
            correct = len(values) == 1 and normalize(values[0]) in {normalize(x) for x in question.accepted_answers if x.strip()}
        else:
            correct_ids = {str(choice.id) for choice in question.choices.all() if choice.is_correct}
            correct = bool(correct_ids) and set(values) == correct_ids and len(values) == len(set(values))
            if question.kind == 'single': correct = correct and len(values) == 1
        if correct:
            correct_count += 1

    score = round(correct_count * 100 / len(questions))
    passed = correct_count * 100 >= quiz.passing_score * len(questions)
    for question in questions:
        if question.explanation:
            messages.info(request, question.explanation)
    QuizAttempt.objects.create(
        user=request.user,
        quiz=quiz,
        score_percent=score,
        passed=passed,
        selected_answers=selected_answers,
    )

    if passed:
        _, points_created = award_quiz_points(request.user, quiz)
        lesson_quiz_ids = list(
            Quiz.objects.filter(material__lesson=lesson, material__required=True).values_list("id", flat=True)
        )
        passed_quizzes = (
            QuizAttempt.objects.filter(
                user=request.user, quiz_id__in=lesson_quiz_ids, passed=True
            )
            .values("quiz_id")
            .distinct()
            .count()
        )
        if passed_quizzes == len(lesson_quiz_ids):
            LessonProgress.objects.update_or_create(
                user=request.user,
                lesson=lesson,
                defaults={"completed": True, "completed_at": timezone.now()},
            )
            recalculate_course_progress(request.user, course)

        if points_created:
            messages.success(
                request,
                f"Отлично: {score}%. Начислено {quiz.points} баллов.",
            )
        else:
            messages.success(request, f"Тест снова пройден на {score}%. Баллы уже начислялись.")
    else:
        messages.warning(
            request,
            f"Результат: {score}%. Для зачёта нужно {quiz.passing_score}%. Попробуйте ещё раз.",
        )

    return redirect("courses:lesson_detail", lesson_id=lesson.id)


@login_required
def leaderboard(request):
    User = get_user_model()
    users = list(
        User.objects.filter(
            role=User.Role.STUDENT,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
        .annotate(
            total_points=Coalesce(
                Sum("score_awards__points"), 0, output_field=IntegerField()
            )
        )
        .prefetch_related("enrollments__course", "achievements")
        .order_by("-total_points", "date_joined", "username")
    )

    for rank, user in enumerate(users, start=1):
        user.rank = rank
        points_rows = ScoreAward.objects.filter(user=user).values("course_id").annotate(
            value=Coalesce(Sum("points"), 0)
        )
        points_map = {row["course_id"]: row["value"] for row in points_rows}
        user.course_details = [
            {
                "course": enrollment.course,
                "progress": enrollment.progress_percent,
                "points": points_map.get(enrollment.course_id, 0),
            }
            for enrollment in user.enrollments.all()
            if enrollment.course.status == Course.Status.PUBLISHED
        ]

    return render(
        request,
        "courses/leaderboard.html",
        {"ranked_users": users, "active_section": "leaderboard"},
    )


@login_required
def chat(request):
    if request.method == "POST":
        form = ChatMessageForm(request.POST)
        if form.is_valid():
            chat_message = form.save(commit=False)
            chat_message.user = request.user
            chat_message.save()
            return redirect("courses:chat")
    else:
        form = ChatMessageForm()

    chat_messages = list(ChatMessage.objects.select_related("user")[:100])
    chat_messages.reverse()
    return render(
        request,
        "courses/chat.html",
        {
            "chat_messages": chat_messages,
            "form": form,
            "active_section": "chat",
        },
    )
