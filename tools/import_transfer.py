"""Import into an EMPTY Docker database, retaining identities and resetting sequences."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.container_settings')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    folder = args.folder.resolve()
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    required = {'data.json', 'media.tar.gz', '.env.keys'}
    if set(manifest) != required:
        sys.exit('Invalid export manifest.')
    for name in required:
        digest = hashlib.sha256()
        with (folder / name).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
        if digest.hexdigest() != manifest[name]: sys.exit(f'Export checksum mismatch: {name}')
    import django
    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.db import transaction
    from courses.models import Course
    from studio.models import Draft
    from deploy_env import read_env
    keys = read_env(folder / '.env.keys')
    if keys.get('MFA_ENCRYPTION_KEY') != settings.MFA_ENCRYPTION_KEY or keys.get('DJANGO_SECRET_KEY') != settings.SECRET_KEY:
        sys.exit('Import these keys with tools/deploy_env.py --import-keys BEFORE starting the containers.')
    media = Path(settings.MEDIA_ROOT)
    media.mkdir(parents=True, exist_ok=True)
    if any(media.iterdir()): sys.exit('Media volume must be empty.')
    if get_user_model().objects.exists() or Course.objects.exists() or Draft.objects.exists():
        sys.exit('Refusing to overwrite existing users/courses. Import only into a fresh installation.')
    try:
        with transaction.atomic():
            call_command('loaddata', str(folder / 'data.json'), verbosity=1)
            with tarfile.open(folder / 'media.tar.gz', 'r:gz') as archive:
                for member in archive:
                    dest = (media / member.name).resolve()
                    if not (member.isfile() or member.isdir()) or not dest.is_relative_to(media.resolve()) or dest == media.resolve():
                        raise ValueError('Invalid file in media archive.')
                    member.uid = member.gid = os.getuid() if hasattr(os, 'getuid') else 10001
                    member.uname = member.gname = ''
                    archive.extract(member, media, filter='data')
    except Exception:
        # This directory was checked to be empty before the import started.
        for child in media.iterdir():
            if child.is_dir() and not child.is_symlink(): shutil.rmtree(child)
            else: child.unlink()
        raise
    print('Users, courses, progress and media imported. Sign in with the existing administrator account.')


if __name__ == '__main__': main()
