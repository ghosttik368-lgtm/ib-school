from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.text import slugify


MAX_UPLOAD_SIZE = 500 * 1024 * 1024


def make_unique_slug(instance, value, max_length=180):
    base_slug = (slugify(value, allow_unicode=True) or "item")[:max_length]
    slug = base_slug
    number = 2
    queryset = instance.__class__.objects.all()
    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    while queryset.filter(slug=slug).exists():
        suffix = f"-{number}"
        slug = f"{base_slug[:max_length - len(suffix)]}{suffix}"
        number += 1
    return slug


def validate_upload_size(upload):
    if upload and upload.size > MAX_UPLOAD_SIZE:
        raise ValidationError("Размер файла не должен превышать 500 МБ.")


def material_upload_path(instance, filename):
    course_id = instance.lesson.module.course_id
    return f"courses/{course_id}/lessons/{instance.lesson_id}/{filename}"


class Direction(models.Model):
    name = models.CharField("Название", max_length=120, unique=True)
    slug = models.SlugField(
        "Адрес", max_length=140, unique=True, allow_unicode=True, blank=True
    )
    description = models.TextField("Описание", blank=True)
    is_active = models.BooleanField("Отображать", default=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "Направление"
        verbose_name_plural = "Направления"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = make_unique_slug(self, self.name, 140)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Course(models.Model):
    is_listed = models.BooleanField(default=True)
    class Level(models.TextChoices):
        BEGINNER = "beginner", "Начальный"
        BASIC = "basic", "Базовый"
        ADVANCED = "advanced", "Продвинутый"

    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликован"

    direction = models.ForeignKey(
        Direction,
        on_delete=models.PROTECT,
        related_name="courses",
        verbose_name="Направление",
    )
    title = models.CharField("Название", max_length=180)
    slug = models.SlugField(
        "Адрес", max_length=180, unique=True, allow_unicode=True, blank=True
    )
    short_description = models.CharField(
        "Краткое описание", max_length=260, blank=True
    )
    description = models.TextField("Полное описание", blank=True)
    cover = models.ImageField(
        "Обложка",
        upload_to="courses/covers/%Y/%m/",
        blank=True,
        null=True,
        validators=[validate_upload_size],
    )
    level = models.CharField(
        "Уровень",
        max_length=20,
        choices=Level.choices,
        default=Level.BEGINNER,
    )
    points_per_test = models.PositiveSmallIntegerField(
        "Баллов за тест", default=5, validators=[MinValueValidator(1)]
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_courses",
        verbose_name="Автор",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)
    published_at = models.DateTimeField("Опубликован", blank=True, null=True)

    class Meta:
        ordering = ("-updated_at",)
        verbose_name = "Курс"
        verbose_name_plural = "Курсы"
        indexes = [
            models.Index(
                fields=("direction", "status"), name="idx_course_direction_status"
            )
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = make_unique_slug(self, self.title)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("courses:course_detail", kwargs={"slug": self.slug})

    def __str__(self):
        return self.title


class Module(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="modules",
        verbose_name="Курс",
    )
    title = models.CharField("Название", max_length=180)
    description = models.TextField("Описание", blank=True)
    order = models.PositiveIntegerField("Порядок", default=1)

    class Meta:
        ordering = ("order", "id")
        verbose_name = "Модуль"
        verbose_name_plural = "Модули"

    def __str__(self):
        return f"{self.course.title}: {self.title}"


class Lesson(models.Model):
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name="lessons",
        verbose_name="Модуль",
    )
    title = models.CharField("Название", max_length=180)
    summary = models.TextField("Краткое описание", blank=True)
    duration_minutes = models.PositiveSmallIntegerField(
        "Продолжительность, минут", default=15, validators=[MinValueValidator(1)]
    )
    order = models.PositiveIntegerField("Порядок", default=1)
    is_active = models.BooleanField("Доступно студентам", default=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        ordering = ("order", "id")
        verbose_name = "Урок"
        verbose_name_plural = "Уроки"

    @property
    def course(self):
        return self.module.course

    def __str__(self):
        return f"{self.module.course.title}: {self.title}"


class Material(models.Model):
    attachment_of = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='attachments')
    rich_text = models.BooleanField(default=False)
    required = models.BooleanField(default=True)
    class Kind(models.TextChoices):
        TEXT = "text", "Статья"
        VIDEO = "video", "Видеолекция"
        PRESENTATION = "presentation", "Презентация"
        DOCUMENT = "document", "Документ Word"
        PDF = "pdf", "PDF-документ"
        LINK = "link", "Внешняя ссылка"
        QUIZ = "quiz", "Тест"
        CODE = "code", "Консоль программирования"

    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="materials",
        verbose_name="Урок",
    )
    title = models.CharField("Название", max_length=180)
    kind = models.CharField("Тип материала", max_length=20, choices=Kind.choices)
    text = models.TextField("Текст", blank=True)
    file = models.FileField(
        "Файл",
        upload_to=material_upload_path,
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "mp4",
                    "webm",
                    "mov",
                    "mkv",
                    "pdf",
                    "ppt",
                    "pptx",
                    "doc",
                    "docx",
                    "txt",
                    "zip",
                ]
            ),
            validate_upload_size,
        ],
    )
    external_url = models.URLField("Ссылка", blank=True)
    order = models.PositiveIntegerField("Порядок", default=1)
    created_at = models.DateTimeField("Добавлено", auto_now_add=True)

    class Meta:
        ordering = ("order", "id")
        verbose_name = "Материал"
        verbose_name_plural = "Материалы"

    def clean(self):
        super().clean()
        errors = {}
        text_value = (self.text or "").strip()

        if self.kind == self.Kind.TEXT and not text_value:
            errors["text"] = "Для статьи необходимо заполнить текст."

        if self.kind in {self.Kind.PRESENTATION, self.Kind.DOCUMENT, self.Kind.PDF}:
            if not self.file:
                errors["file"] = "Для этого материала необходимо выбрать файл."

        if self.kind == self.Kind.VIDEO and not self.file and not self.external_url:
            errors["file"] = "Загрузите видео или укажите ссылку на него."

        if self.kind == self.Kind.LINK and not self.external_url:
            errors["external_url"] = "Укажите адрес внешнего материала."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class Quiz(models.Model):
    points = models.PositiveSmallIntegerField(default=5)
    material = models.OneToOneField(
        Material,
        on_delete=models.CASCADE,
        related_name="quiz",
        verbose_name="Материал",
    )
    passing_score = models.PositiveSmallIntegerField("Проходной процент", default=100)

    class Meta:
        verbose_name = "Тест"
        verbose_name_plural = "Тесты"

    def __str__(self):
        return self.material.title


class Question(models.Model):
    kind = models.CharField(max_length=12, default='single', choices=[('single', 'Один ответ'), ('multiple', 'Несколько ответов'), ('short', 'Короткий ответ')])
    accepted_answers = models.JSONField(default=list, blank=True)
    case_sensitive = models.BooleanField(default=False)
    explanation = models.TextField(blank=True)
    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name="Тест",
    )
    text = models.TextField("Вопрос")
    order = models.PositiveIntegerField("Порядок", default=1)

    class Meta:
        ordering = ("order", "id")
        verbose_name = "Вопрос"
        verbose_name_plural = "Вопросы"

    def __str__(self):
        return self.text[:80]


class AnswerChoice(models.Model):
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        related_name="choices",
        verbose_name="Вопрос",
    )
    text = models.CharField("Вариант ответа", max_length=500)
    is_correct = models.BooleanField("Правильный ответ", default=False)
    order = models.PositiveIntegerField("Порядок", default=1)

    class Meta:
        ordering = ("order", "id")
        verbose_name = "Вариант ответа"
        verbose_name_plural = "Варианты ответа"

    def __str__(self):
        return self.text


class Enrollment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollments",
        verbose_name="Студент",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="enrollments",
        verbose_name="Курс",
    )
    progress_percent = models.PositiveSmallIntegerField("Прогресс", default=0)
    started_at = models.DateTimeField("Добавлен", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)
    completed_at = models.DateTimeField("Завершён", blank=True, null=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "course"), name="unique_user_course_enrollment"
            )
        ]
        verbose_name = "Запись на курс"
        verbose_name_plural = "Записи на курсы"

    def __str__(self):
        return f"{self.user} — {self.course}"


class LessonProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lesson_progress",
        verbose_name="Студент",
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="progress_records",
        verbose_name="Урок",
    )
    completed = models.BooleanField("Пройден", default=False)
    completed_at = models.DateTimeField("Пройден", blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "lesson"), name="unique_user_lesson_progress"
            )
        ]
        verbose_name = "Прогресс урока"
        verbose_name_plural = "Прогресс уроков"


class QuizAttempt(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quiz_attempts",
        verbose_name="Студент",
    )
    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name="attempts",
        verbose_name="Тест",
    )
    score_percent = models.PositiveSmallIntegerField("Результат")
    passed = models.BooleanField("Пройден", default=False)
    selected_answers = models.JSONField("Выбранные ответы", default=dict, blank=True)
    created_at = models.DateTimeField("Попытка", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Попытка теста"
        verbose_name_plural = "Попытки тестов"


class ScoreAward(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="score_awards",
        verbose_name="Студент",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="score_awards",
        verbose_name="Курс",
    )
    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name="score_awards",
        verbose_name="Тест",
    )
    points = models.PositiveSmallIntegerField("Баллы")
    created_at = models.DateTimeField("Начислено", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "quiz"), name="unique_user_quiz_award"
            )
        ]
        verbose_name = "Начисление баллов"
        verbose_name_plural = "Начисления баллов"


class UserAchievement(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="achievements",
        verbose_name="Студент",
    )
    code = models.CharField("Код", max_length=120)
    title = models.CharField("Название", max_length=180)
    description = models.CharField("Описание", max_length=320, blank=True)
    earned_at = models.DateTimeField("Получено", auto_now_add=True)

    class Meta:
        ordering = ("-earned_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "code"), name="unique_user_achievement_code"
            )
        ]
        verbose_name = "Достижение"
        verbose_name_plural = "Достижения"


class ChatMessage(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
        verbose_name="Автор",
    )
    text = models.TextField("Сообщение", max_length=2000)
    created_at = models.DateTimeField("Отправлено", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Сообщение чата"
        verbose_name_plural = "Сообщения чата"

    def __str__(self):
        return f"{self.user}: {self.text[:50]}"
