import os
from pathlib import Path
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent
load_dotenv(PROJECT_ROOT / '.env')

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "",
)
if not SECRET_KEY:
    raise RuntimeError('Сначала выполните python tools/init_local.py')
MFA_ENCRYPTION_KEY = os.environ.get('MFA_ENCRYPTION_KEY', '')
if not MFA_ENCRYPTION_KEY:
    raise RuntimeError('В корневом .env нужен MFA_ENCRYPTION_KEY. Выполните tools/init_local.py')
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
DEV_DISABLE_MFA = DEBUG and os.environ.get('DEV_DISABLE_MFA', '1') == '1'
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "core",
    "courses",
    "access",
    "studio",
    "learning",
    "practice",
    "messenger",
    "teaching",
    "autoquiz",
]

AUTOQUIZ_ENABLED = os.environ.get('AUTOQUIZ_ENABLED', '0') == '1'

# Optional local AI worker. The web process never imports large AI libraries.
AUTOQUIZ_MODEL = os.environ.get('AUTOQUIZ_MODEL', 'qwen3:4b-instruct-2507-q4_K_M')
AUTOQUIZ_WHISPER = os.environ.get('AUTOQUIZ_WHISPER', 'medium')
AUTOQUIZ_MODEL_DIR = PROJECT_ROOT / '.autoquiz_models'
AUTOQUIZ_OLLAMA_URL = os.environ.get('AUTOQUIZ_OLLAMA_URL', 'http://127.0.0.1:11434')
AUTOQUIZ_THREADS = max(1, min(8, int(os.environ.get('AUTOQUIZ_THREADS', '4'))))
AUTOQUIZ_TIMEOUT = max(60, min(1800, int(os.environ.get('AUTOQUIZ_TIMEOUT', '600'))))

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "access.middleware.AccountGateMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [PROJECT_ROOT / "frontend" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [PROJECT_ROOT / "frontend" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 512 * 1024 * 1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 28800
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if x.strip()]
CSRF_FAILURE_VIEW = 'access.views.csrf_failure'
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
if os.environ.get('DB_ENGINE', 'sqlite') == 'postgresql':
    DATABASES['default'] = {'ENGINE': 'django.db.backends.postgresql', 'NAME': os.environ.get('POSTGRES_DB', 'ib_school'), 'USER': os.environ.get('POSTGRES_USER', 'ib_school'), 'PASSWORD': os.environ['POSTGRES_PASSWORD'], 'HOST': os.environ.get('POSTGRES_HOST', '127.0.0.1'), 'PORT': os.environ.get('POSTGRES_PORT', '5432'), 'CONN_MAX_AGE': 60, 'OPTIONS': {'connect_timeout': 5}}

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "1") == "1"
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    if os.environ.get('TRUST_PROXY_SSL', '0') == '1':
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
