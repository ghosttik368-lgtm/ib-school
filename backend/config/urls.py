from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from access import views as access_views
from access.media import protected_media
from studio.views import dashboard as studio_dashboard


urlpatterns = [
    path('autoquiz/', include('autoquiz.urls')),
    path('', include('messenger.urls')),
    path('', include('teaching.urls')),
    path('', include('practice.urls')),
    path('', include('learning.urls')),
    path('management/', studio_dashboard),
    path('studio/', include('studio.urls')),
    path("admin/login/", access_views.sign_in),
    path("admin/", admin.site.urls),
    path("accounts/login/", access_views.sign_in, name="login"),
    path("accounts/logout/", access_views.sign_out, name="logout"),
    path("accounts/register/", access_views.register, name="register"),
    path("accounts/password_change/", access_views.change_password, name="password_change"),
    path("access/", include("access.urls")),
    path("accounts/", include("accounts.urls")),
    path("", include("core.urls")),
    path("", include("courses.urls")),
]

urlpatterns += [path('media/<path:path>', protected_media)]
handler403 = 'access.views.forbidden'
handler404 = 'access.views.not_found'
handler500 = 'access.views.server_error'
