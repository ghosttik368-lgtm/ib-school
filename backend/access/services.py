import secrets
import time
from datetime import timedelta
import pyotp
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import login
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from .models import AccountSecurity, AuditEvent, RateBucket, RecoveryCode


def digest(value):
    return salted_hmac('ib-access-v1', value.strip(), algorithm='sha256').hexdigest()


def secret_box():
    return Fernet(settings.MFA_ENCRYPTION_KEY.encode())


def security_for(user):
    return AccountSecurity.objects.get_or_create(user=user)[0]


def audit(action, actor=None, subject=None, detail=''):
    AuditEvent.objects.create(action=action, actor=actor, subject=subject, detail=detail[:220])


def limited(request, scope, identifier='', limit=10, seconds=900):
    now = timezone.now()
    slot = int(now.timestamp()) // seconds
    keys = [(f"{scope}:ip:{request.META.get('REMOTE_ADDR', '')}", limit * 5)]
    if identifier:
        keys.append((f'{scope}:account:{identifier.casefold()[:150]}', limit))
    blocked = False
    for key, maximum in keys:
        bucket, _ = RateBucket.objects.get_or_create(digest=digest(f'{key}:{slot}'), defaults={'expires_at': now + timedelta(seconds=seconds)})
        RateBucket.objects.filter(pk=bucket.pk).update(count=F('count') + 1)
        bucket.refresh_from_db()
        blocked = blocked or bucket.count > maximum
    return blocked


def finish_login(request, user, verified=False):
    sec = security_for(user)
    request.session.flush()
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.session['access_version'] = sec.version
    request.session['mfa_verified'] = bool(verified)
    audit('Вход выполнен', actor=user)


def start_pending(request, user):
    request.session.flush()
    request.session['pending_user'] = user.pk
    request.session['pending_hash'] = user.get_session_auth_hash()
    request.session['pending_version'] = security_for(user).version
    request.session['pending_until'] = time.time() + 600


def pending_user(request):
    from accounts.models import User
    if request.session.get('pending_until', 0) < time.time(): return None
    user = User.objects.filter(pk=request.session.get('pending_user'), is_active=True).first()
    if not user or not constant_time_compare(request.session.get('pending_hash', ''), user.get_session_auth_hash()): return None
    if request.session.get('pending_version') != security_for(user).version: return None
    return user


def counter_for(secret, token):
    if len(token) != 6 or not token.isascii() or not token.isdigit(): return None
    now = int(time.time()) // 30
    totp = pyotp.TOTP(secret)
    for counter in (now, now - 1, now + 1):
        if constant_time_compare(totp.at(counter * 30), token): return counter
    return None


@transaction.atomic
def consume_otp(user, token):
    token = token.strip()
    sec = AccountSecurity.objects.select_for_update().get(user=user)
    if not sec.enabled: return False
    secret = secret_box().decrypt(sec.secret_encrypted.encode()).decode()
    counter = counter_for(secret, token)
    if counter is not None:
        return bool(AccountSecurity.objects.filter(pk=sec.pk, last_counter__lt=counter).update(last_counter=counter))
    return bool(RecoveryCode.objects.filter(user=user, digest=digest(token), used_at__isnull=True).update(used_at=timezone.now()))


@transaction.atomic
def new_recovery_codes(user):
    AccountSecurity.objects.select_for_update().get(user=user)
    codes = [secrets.token_hex(8) for _ in range(8)]
    RecoveryCode.objects.filter(user=user).delete()
    RecoveryCode.objects.bulk_create([RecoveryCode(user=user, digest=digest(code)) for code in codes])
    return codes


def revoke_sessions(user):
    security_for(user)
    AccountSecurity.objects.filter(user=user).update(version=F('version') + 1)
