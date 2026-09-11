"""Export local application data for a fresh Docker installation. Stop writers first."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def main():
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    folder = ROOT / 'transfer' / ('export_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
    folder.mkdir(parents=True, mode=0o700)
    call_command('dumpdata', natural_foreign=True, natural_primary=False,
                 exclude=['contenttypes', 'auth.permission', 'sessions.session', 'admin.logentry',
                          'practice.worker', 'autoquiz.workerlease', 'access.ratebucket'],
                 output=str(folder / 'data.json'), verbosity=0)
    with tarfile.open(folder / 'media.tar.gz', 'w:gz') as archive:
        media = Path(settings.MEDIA_ROOT)
        if media.exists():
            for child in sorted(media.iterdir()): archive.add(child, arcname=child.name)
    (folder / '.env.keys').write_text(
        f'DJANGO_SECRET_KEY={settings.SECRET_KEY}\nMFA_ENCRYPTION_KEY={settings.MFA_ENCRYPTION_KEY}\n',
        encoding='utf-8')
    manifest = {}
    for path in folder.iterdir():
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
        manifest[path.name] = digest.hexdigest()
        if os.name != 'nt': path.chmod(0o600)
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Export ready: {folder}')
    print('Contains accounts/password hashes, media and keys. Transfer over SSH; do not commit or share publicly.')


if __name__ == '__main__': main()
