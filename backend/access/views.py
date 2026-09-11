import base64
import io
import secrets
from datetime import timedelta
from functools import wraps
import pyotp
import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from accounts.models import User
from .forms import InviteForm, InvitedRegisterForm, OTPForm, ResetAccessForm, SensitiveForm, SignInForm
from .models import AccountSecurity, AuditEvent, Invitation, RecoveryCode, ResetGrant
from .services import audit, consume_otp, counter_for, digest, finish_login, limited, new_recovery_codes, pending_user, revoke_sessions, secret_box, security_for, start_pending


def admin_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_platform_admin: raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def error(request, heading, explanation, status):
    return render(request, 'access/error.html', {'heading': heading, 'explanation': explanation}, status=status)


def slow_down(request):
    response = error(request, 'Слишком много попыток', 'Подождите 15 минут и попробуйте снова.', 429)
    response['Retry-After'] = '900'
    return response


@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def sign_in(request):
    if request.user.is_authenticated: return redirect('home')
    if request.method == 'POST' and limited(request, 'login', request.POST.get('username', '')): return slow_down(request)
    form = SignInForm(request, data=request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        sec = security_for(user)
        if not settings.DEV_DISABLE_MFA and (user.can_manage_courses or sec.enabled):
            start_pending(request, user)
            return redirect('access:verify' if sec.enabled else 'access:setup')
        finish_login(request, user)
        return redirect('home')
    return render(request, 'registration/login.html', {'form': form})


@require_POST
def sign_out(request):
    if request.user.is_authenticated: audit('Выход', actor=request.user)
    logout(request)
    return redirect('login')


@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def register(request):
    if request.user.is_authenticated: return redirect('home')
    if request.method == 'POST' and limited(request, 'register', request.POST.get('username', ''), limit=5): return slow_down(request)
    form = InvitedRegisterForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                now = timezone.now()
                invite = Invitation.objects.filter(digest=digest(form.cleaned_data['invitation']), used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now).first()
                if not invite or not Invitation.objects.filter(pk=invite.pk, used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now).update(used_at=now):
                    form.add_error('invitation', 'Приглашение недействительно, использовано или истекло.')
                else:
                    user = form.save()
                    invite.used_by = user
                    invite.save(update_fields=['used_by'])
                    security_for(user)
                    audit('Регистрация по приглашению', actor=user)
                    finish_login(request, user)
                    return redirect('home')
        except IntegrityError:
            form.add_error(None, 'Регистрация не завершена. Проверьте логин и приглашение.')
    return render(request, 'registration/register.html', {'form': form})


@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def verify(request):
    if settings.DEV_DISABLE_MFA: return redirect('login')
    user = pending_user(request)
    if not user: return redirect('login')
    if not security_for(user).enabled: return redirect('access:setup')
    if request.method == 'POST' and limited(request, 'otp', str(user.pk), limit=6): return slow_down(request)
    form = OTPForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        if consume_otp(user, form.cleaned_data['code']):
            finish_login(request, user, verified=True)
            return redirect('home')
        audit('Неудачная проверка 2FA', subject=user)
        form.add_error('code', 'Код неверный или уже использован. Дождитесь нового либо используйте резервный.')
    return render(request, 'access/verify.html', {'form': form})


@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def setup(request):
    if settings.DEV_DISABLE_MFA: return redirect('login')
    user = pending_user(request)
    if not user: return redirect('login')
    sec = security_for(user)
    if sec.enabled: return redirect('access:verify')
    if 'setup_secret' not in request.session:
        request.session['setup_secret'] = secret_box().encrypt(pyotp.random_base32().encode()).decode()
    encrypted = request.session['setup_secret']
    secret = secret_box().decrypt(encrypted.encode()).decode()
    form = OTPForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if limited(request, 'otp', str(user.pk), limit=6): return slow_down(request)
        if form.is_valid():
            counter = counter_for(secret, form.cleaned_data['code'])
            if counter is not None:
                with transaction.atomic():
                    updated = AccountSecurity.objects.filter(pk=sec.pk, enabled=False, version=request.session['pending_version']).update(secret_encrypted=encrypted, enabled=True, last_counter=counter)
                    if not updated: return redirect('login')
                    codes = new_recovery_codes(user)
                    audit('Двухфакторный вход подключён', actor=user)
                finish_login(request, user, verified=True)
                return render(request, 'access/recovery_codes.html', {'codes': codes})
            form.add_error('code', 'Код не подошёл. Проверьте время на телефоне.')
    stream = io.BytesIO()
    qrcode.make(pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name='ИБ')).save(stream, format='PNG')
    return render(request, 'access/setup.html', {'form': form, 'qr': base64.b64encode(stream.getvalue()).decode(), 'secret': secret})


@sensitive_post_parameters()
@login_required
@require_http_methods(['GET', 'POST'])
def security(request):
    sec = security_for(request.user)
    if settings.DEV_DISABLE_MFA:
        sec.enabled = False  # Display only; persisted MFA settings remain intact.
    form = SensitiveForm(request.POST if request.method == 'POST' else None)
    if not sec.enabled: form.fields.pop('code')
    if request.method == 'POST':
        if limited(request, 'security', str(request.user.pk), limit=6): return slow_down(request)
        if form.is_valid():
            action = request.POST.get('action')
            if action not in {'sessions', 'codes', 'enable'}: raise PermissionDenied
            if not request.user.check_password(form.cleaned_data['current_password']) or (sec.enabled and not consume_otp(request.user, form.cleaned_data['code'])):
                form.add_error(None, 'Не удалось подтвердить действие. Проверьте пароль и свежий код.')
            elif action == 'sessions':
                revoke_sessions(request.user)
                audit('Все сеансы завершены', actor=request.user)
                logout(request)
                return redirect('login')
            elif sec.enabled and action == 'codes':
                codes = new_recovery_codes(request.user)
                audit('Резервные коды перевыпущены', actor=request.user)
                return render(request, 'access/recovery_codes.html', {'codes': codes})
            elif not sec.enabled and action == 'enable':
                if settings.DEV_DISABLE_MFA:
                    form.add_error(None, '2FA отключена для локальной разработки.')
                    return render(request, 'access/security.html', {'form': form, 'sec': sec, 'active_section': 'profile', 'mfa_disabled': True})
                start_pending(request, request.user)
                return redirect('access:setup')
            else: raise PermissionDenied
    return render(request, 'access/security.html', {'form': form, 'sec': sec, 'active_section': 'profile', 'mfa_disabled': settings.DEV_DISABLE_MFA})


@sensitive_post_parameters()
@login_required
@require_http_methods(['GET', 'POST'])
def change_password(request):
    if request.method == 'POST' and limited(request, 'password', str(request.user.pk), limit=6): return slow_down(request)
    form = PasswordChangeForm(request.user, request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        audit('Пароль изменён', actor=request.user)
        logout(request)
        messages.success(request, 'Пароль изменён. Войдите заново.')
        return redirect('login')
    return render(request, 'access/password.html', {'form': form})


@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def reset_access(request):
    if request.method == 'POST' and limited(request, 'reset', request.POST.get('username', ''), limit=5): return slow_down(request)
    form = ResetAccessForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        user = User.objects.filter(username=form.cleaned_data['username'], is_active=True).first()
        grant = ResetGrant.objects.filter(user=user, digest=digest(form.cleaned_data['token']), used_at__isnull=True, expires_at__gt=timezone.now()).first() if user else None
        if not grant:
            form.add_error(None, 'Логин или код неверен, либо срок действия кода истёк.')
        else:
            password_form = SetPasswordForm(user, request.POST)
            if not password_form.is_valid():
                for field, errors in password_form.errors.items():
                    for message in errors: form.add_error(field if field in form.fields else None, message)
            else:
                with transaction.atomic():
                    claimed = ResetGrant.objects.filter(pk=grant.pk, used_at__isnull=True, expires_at__gt=timezone.now()).update(used_at=timezone.now())
                    if not claimed: form.add_error(None, 'Код уже использован.')
                    else:
                        password_form.save()
                        revoke_sessions(user)
                        audit('Пароль восстановлен', subject=user)
                        logout(request)
                        return redirect('login')
    return render(request, 'access/reset.html', {'form': form})


@admin_required
def people(request):
    query = request.GET.get('q', '').strip()[:150]
    users = User.objects.order_by('username')
    if query: users = users.filter(username__icontains=query)
    return render(request, 'access/people.html', {'page': Paginator(users, 20).get_page(request.GET.get('page')), 'query': query, 'active_section': 'access'})


@sensitive_post_parameters()
@admin_required
@require_http_methods(['GET', 'POST'])
def person(request, user_id):
    target = get_object_or_404(User, pk=user_id)
    form = SensitiveForm(request.POST if request.method == 'POST' else None)
    if settings.DEV_DISABLE_MFA: form.fields.pop('code')
    if request.method == 'POST':
        if limited(request, 'admin-action', str(request.user.pk), limit=8): return slow_down(request)
        if form.is_valid():
            if target.pk == request.user.pk or target.is_superuser:
                form.add_error(None, 'Свой аккаунт и владельца сервера здесь изменять нельзя.')
            elif not request.user.check_password(form.cleaned_data['current_password']) or (not settings.DEV_DISABLE_MFA and not consume_otp(request.user, form.cleaned_data['code'])):
                form.add_error(None, 'Не удалось подтвердить действие. Нужен пароль и свежий код 2FA.')
            else:
                raw_code = None
                action = request.POST.get('action')
                with transaction.atomic():
                    target = User.objects.select_for_update().get(pk=target.pk)
                    if target.pk == request.user.pk or target.is_superuser: raise PermissionDenied
                    if action == 'role':
                        role = request.POST.get('role')
                        if role not in User.Role.values: raise PermissionDenied
                        target.role, target.is_staff = role, False
                        target.save(update_fields=['role', 'is_staff'])
                        audit('Роль изменена', request.user, target, role)
                    elif action == 'toggle':
                        target.is_active = not target.is_active
                        target.save(update_fields=['is_active'])
                        audit('Доступ разрешён' if target.is_active else 'Аккаунт заблокирован', request.user, target)
                    elif action == 'reset':
                        ResetGrant.objects.filter(user=target, used_at__isnull=True).update(used_at=timezone.now())
                        raw_code = secrets.token_urlsafe(24)
                        ResetGrant.objects.create(user=target, digest=digest(raw_code), expires_at=timezone.now() + timedelta(minutes=30))
                        audit('Выдан код восстановления', request.user, target)
                    elif action == 'reset_mfa':
                        security_for(target)
                        AccountSecurity.objects.filter(user=target).update(enabled=False, secret_encrypted='', last_counter=-1)
                        RecoveryCode.objects.filter(user=target).delete()
                        audit('2FA сброшена после проверки личности', request.user, target)
                    else: raise PermissionDenied
                    revoke_sessions(target)
                if raw_code:
                    return render(request, 'access/issued.html', {'raw_code': raw_code, 'heading': 'Код восстановления', 'explanation': 'Действует 30 минут, один раз. Передайте после проверки личности.'})
                messages.success(request, 'Изменения сохранены. Предыдущие сеансы отозваны.')
                return redirect('access:person', user_id=target.pk)
    return render(request, 'access/person.html', {'target': target, 'form': form, 'active_section': 'access'})


@admin_required
@require_http_methods(['GET', 'POST'])
def invitations(request):
    form = InviteForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        if limited(request, 'invite', str(request.user.pk), limit=30): return slow_down(request)
        code = secrets.token_urlsafe(24)
        invitation = Invitation.objects.create(digest=digest(code), label=form.cleaned_data['label'], created_by=request.user, expires_at=timezone.now() + timedelta(days=form.cleaned_data['days']))
        audit('Приглашение создано', request.user, detail=f'№ {invitation.pk}')
        return render(request, 'access/issued.html', {'raw_code': code, 'heading': 'Приглашение готово', 'explanation': 'Скопируйте и передайте студенту. Код показывается только сейчас и действует один раз.'})
    return render(request, 'access/invitations.html', {'form': form, 'page': Paginator(Invitation.objects.select_related('used_by').order_by('-created_at'), 15).get_page(request.GET.get('page')), 'active_section': 'access'})


@admin_required
@require_POST
def revoke_invite(request, invite_id):
    invitation = get_object_or_404(Invitation, pk=invite_id)
    Invitation.objects.filter(pk=invitation.pk, revoked_at__isnull=True).update(revoked_at=timezone.now())
    audit('Приглашение отозвано', request.user, detail=f'№ {invitation.pk}')
    messages.success(request, 'Приглашение отозвано. Уже зарегистрированный аккаунт не блокируется.')
    return redirect('access:invitations')


@admin_required
def audit_log(request):
    return render(request, 'access/audit.html', {'page': Paginator(AuditEvent.objects.select_related('actor', 'subject'), 30).get_page(request.GET.get('page')), 'active_section': 'access'})


@admin_required
def components(request): return render(request, 'access/components.html')


def csrf_failure(request, reason=''): return error(request, 'Обновите страницу', 'Запрос не прошёл проверку. Откройте форму снова.', 403)
def forbidden(request, exception=None): return error(request, 'Нет доступа', 'Для этого действия нужны другие права.', 403)
def not_found(request, exception=None): return error(request, 'Страница не найдена', 'Проверьте адрес или вернитесь к курсам.', 404)
def server_error(request): return error(request, 'Не удалось открыть страницу', 'Попробуйте позже. Если ошибка повторяется, сообщите администратору.', 500)
