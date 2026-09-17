"""Create private persistent configuration without host Python or an init command."""
import base64
import json
import os
from pathlib import Path
import re
import secrets


def prepare(root=Path('/run/ib'), routing=Path('/run/routing')):
    root.mkdir(parents=True, exist_ok=True)
    routing.mkdir(parents=True, exist_ok=True)
    path = root / 'settings.json'
    if path.exists():
        cfg = json.loads(path.read_text())
    else:
        cfg = {
            'DJANGO_SECRET_KEY': os.environ.get('DJANGO_SECRET_KEY') or secrets.token_urlsafe(60),
            'MFA_ENCRYPTION_KEY': os.environ.get('MFA_ENCRYPTION_KEY') or base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            'POSTGRES_PASSWORD': os.environ.get('POSTGRES_PASSWORD') or secrets.token_urlsafe(40),
            'POSTGRES_USER': os.environ.get('POSTGRES_USER') or 'ib_school',
            'POSTGRES_DB': os.environ.get('POSTGRES_DB') or 'ib_school',
            'ADMIN_PASSWORD': secrets.token_urlsafe(24),
        }
    site = os.environ.get('IB_SITE') or cfg.get('SITE_ADDRESS') or os.environ.get('SITE_ADDRESS') or 'http://:80'
    if site != 'http://:80' and not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', site):
        raise ValueError('IB_SITE must be a hostname without scheme/path, or http://:80.')
    cfg['SITE_ADDRESS'] = site
    files = {
        'settings.json': json.dumps(cfg),
        'db-user': cfg['POSTGRES_USER'], 'db-name': cfg['POSTGRES_DB'],
        'db-password': cfg['POSTGRES_PASSWORD'], 'admin-password': cfg['ADMIN_PASSWORD'],
    }
    for name, value in files.items():
        p = root / name
        temp = root / (name + '.tmp')
        temp.write_text(value)
        # Database starts as root, then its entrypoint reads the password as postgres.
        temp.chmod(0o644 if name.startswith('db-') else 0o600)
        os.chown(temp, 10001, 10001)
        temp.replace(p)
    (routing / 'site').write_text(site)
    (routing / 'site').chmod(0o644)
    print('Configuration ready. Existing keys and database password preserved.')


if __name__ == '__main__':
    prepare()
