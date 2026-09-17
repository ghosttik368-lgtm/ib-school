"""Automatically generated Compose settings, shared by web and all workers."""
import json
import os
from pathlib import Path

cfg = json.loads(Path('/run/ib/settings.json').read_text())
for key in ('DJANGO_SECRET_KEY', 'MFA_ENCRYPTION_KEY', 'POSTGRES_PASSWORD', 'POSTGRES_USER', 'POSTGRES_DB'):
    os.environ[key] = cfg[key]
site = cfg['SITE_ADDRESS']
https = site != 'http://:80'
os.environ.update(
    DB_ENGINE='postgresql', POSTGRES_HOST='db', POSTGRES_PORT='5432',
    DJANGO_DEBUG='0', DEPLOY_MODE='server' if https else 'local',
    DJANGO_ALLOWED_HOSTS=site+',localhost' if https else '*',
    CSRF_TRUSTED_ORIGINS='https://'+site if https else '',
    AUTOQUIZ_OLLAMA_URL='http://ollama:11434',
)
from .container_settings import *  # noqa: E402,F403
