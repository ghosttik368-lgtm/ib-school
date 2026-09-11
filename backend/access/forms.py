from django import forms
from django.contrib.auth.forms import AuthenticationForm
from accounts.forms import RegisterForm


class SignInForm(AuthenticationForm):
    error_messages = {'invalid_login': 'Неверный логин или пароль. Проверьте доступ к аккаунту.', 'inactive': 'Неверный логин или пароль. Проверьте доступ к аккаунту.'}


class InvitedRegisterForm(RegisterForm):
    invitation = forms.CharField(label='Код приглашения', max_length=100)


class OTPForm(forms.Form):
    code = forms.CharField(label='Код из приложения или резервный код', max_length=40, widget=forms.TextInput(attrs={'autocomplete': 'one-time-code'}))


class InviteForm(forms.Form):
    label = forms.CharField(label='Для кого (необязательно)', max_length=120, required=False)
    days = forms.TypedChoiceField(label='Срок действия', choices=[(1, '1 день'), (7, '7 дней'), (30, '30 дней')], coerce=int, initial=7)


class SensitiveForm(forms.Form):
    current_password = forms.CharField(label='Ваш пароль для подтверждения', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))
    code = forms.CharField(label='Свежий код 2FA или резервный код', max_length=40)


class ResetAccessForm(forms.Form):
    username = forms.CharField(label='Логин', max_length=150)
    token = forms.CharField(label='Одноразовый код от администратора', max_length=100)
    new_password1 = forms.CharField(label='Новый пароль', strip=False, widget=forms.PasswordInput)
    new_password2 = forms.CharField(label='Повторите новый пароль', strip=False, widget=forms.PasswordInput)
