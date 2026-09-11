from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            "Платформа ИБ",
            {"fields": ("role", "study_year", "study_group", "department", "avatar")},
        ),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Платформа ИБ",
            {"fields": ("role", "study_year", "study_group", "department")},
        ),
    )
    list_display = ("username", "email", "role", "study_year", "is_staff")
    list_filter = ("role", "study_year", "is_staff", "is_superuser")

