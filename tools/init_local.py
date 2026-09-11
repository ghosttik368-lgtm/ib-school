from pathlib import Path
import secrets
from cryptography.fernet import Fernet
from dotenv import dotenv_values
root = Path(__file__).resolve().parent.parent
env = root / '.env'
values = dotenv_values(env) if env.exists() else {}
defaults = {'DJANGO_SECRET_KEY': secrets.token_urlsafe(48), 'MFA_ENCRYPTION_KEY': Fernet.generate_key().decode(), 'DJANGO_DEBUG': '1', 'DJANGO_ALLOWED_HOSTS': '127.0.0.1,localhost', 'DB_ENGINE': 'sqlite', 'POSTGRES_DB': 'ib_school', 'POSTGRES_USER': 'ib_school', 'POSTGRES_PASSWORD': secrets.token_urlsafe(32), 'POSTGRES_HOST': '127.0.0.1', 'POSTGRES_PORT': '5432'}
with env.open('a', encoding='utf-8') as f:
    f.write('\n')
    for key, value in defaults.items():
        if key not in values: f.write(f'{key}={value}\n')
print('Настройки готовы. Имеющиеся значения .env и база не изменены.')
