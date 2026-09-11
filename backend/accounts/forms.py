from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class RegisterForm(UserCreationForm):
    username = forms.CharField(
        label="Логин",
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Например, nikita_ivanov",
                "autocomplete": "username",
                "autofocus": True,
            }
        ),
    )
    study_year = forms.TypedChoiceField(
        label="Курс обучения",
        choices=User.StudyYear.choices,
        coerce=int,
        empty_value=None,
    )
    password1 = forms.CharField(
        label="Пароль",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"placeholder": "Не менее 8 символов", "autocomplete": "new-password"}
        ),
    )
    password2 = forms.CharField(
        label="Повторите пароль",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"placeholder": "Введите пароль ещё раз", "autocomplete": "new-password"}
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "study_year", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.STUDENT
        user.study_year = self.cleaned_data["study_year"]
        if commit:
            user.save()
        return user

