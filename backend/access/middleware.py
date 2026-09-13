from django.contrib.auth import logout
from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.cache import patch_cache_control
from .services import security_for


class AccountGateMiddleware:
    def __init__(self, get_response): self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            sec = security_for(request.user)
            if request.session.get('access_version') != sec.version or (not settings.DEV_DISABLE_MFA and (request.user.can_manage_courses or sec.enabled) and not request.session.get('mfa_verified')):
                logout(request)
                return redirect('login')
            if request.path.startswith('/admin/') and not request.user.is_platform_admin:
                return HttpResponseForbidden('Нет доступа к технической панели.')
            if request.user.must_change_password and request.path not in {reverse('password_change'), reverse('logout')} and not request.path.startswith('/static/'):
                return redirect('password_change')
        response = self.get_response(request)
        if not request.path.startswith('/static/'):
            patch_cache_control(response, private=True, no_store=True)
        return response
