"""Docker settings; the existing Windows settings and migrations stay in use."""
import os
from .settings import *  # noqa: F403

ROOT_URLCONF = 'config.container_urls'
MIDDLEWARE = [MIDDLEWARE[0], 'config.proxy.ProxyClientIPMiddleware', *MIDDLEWARE[1:]]
if os.environ.get('DB_ENGINE') != 'postgresql':
    raise RuntimeError('Docker deployment requires DB_ENGINE=postgresql.')

# Gunicorn is reachable only through our proxy, which overwrites this header.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
if 'localhost' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, 'localhost']
SECURE_REDIRECT_EXEMPT = [r'^healthz/$']
SECURE_HSTS_PRELOAD = False
AUTOQUIZ_OLLAMA_ALLOWED_HOSTS = ('127.0.0.1', 'localhost', '::1', 'ollama')
AUTOQUIZ_MODEL_DIR = PROJECT_ROOT / '.autoquiz_models'
MEDIA_ROOT = BASE_DIR / 'media'
STATIC_ROOT = BASE_DIR / 'staticfiles'

if os.environ.get('DEPLOY_MODE') == 'local':
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_SSL_REDIRECT = False
    SECURE_HSTS_SECONDS = 0
else:
    if DEBUG:
        raise RuntimeError('DJANGO_DEBUG must be 0 on the server.')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True

LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
}
