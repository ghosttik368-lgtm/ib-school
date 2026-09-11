from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "student", "Студент"
        TEACHER = "teacher", "Преподаватель"
        ADMIN = "admin", "Администратор"

    class StudyYear(models.IntegerChoices):
        FIRST = 1, "1 курс"
        SECOND = 2, "2 курс"
        THIRD = 3, "3 курс"
        FOURTH = 4, "4 курс"
        FIFTH = 5, "5 курс"
        SIXTH = 6, "6 курс"

    role = models.CharField(
        "Роль",
        max_length=20,
        choices=Role.choices,
        default=Role.STUDENT,
        db_index=True,
    )
    study_year = models.PositiveSmallIntegerField(
        "Курс обучения",
        choices=StudyYear.choices,
        blank=True,
        null=True,
    )
    study_group = models.CharField("Учебная группа", max_length=40, blank=True)
    department = models.CharField("Кафедра", max_length=160, blank=True)
    avatar = models.ImageField("Аватар", upload_to="avatars/", blank=True, null=True)

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    @property
    def display_name(self):
        return self.get_full_name().strip() or self.username

    @property
    def can_manage_courses(self):
        return self.is_active and (self.is_platform_admin or self.role == self.Role.TEACHER)

    @property
    def is_platform_admin(self):
        return self.is_active and (self.is_superuser or self.role == self.Role.ADMIN)

    @property
    def role_label(self):
        return "Администратор" if self.is_platform_admin else self.get_role_display()

    def __str__(self):
        return self.display_name
