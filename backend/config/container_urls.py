from django.db import connection
from django.http import JsonResponse
from django.urls import path
from django.views.decorators.http import require_safe
from .urls import urlpatterns as application_urls


@require_safe
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        return JsonResponse({'status': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ok'})


urlpatterns = [path('healthz/', health), *application_urls]
handler403 = 'access.views.forbidden'
handler404 = 'access.views.not_found'
handler500 = 'access.views.server_error'
