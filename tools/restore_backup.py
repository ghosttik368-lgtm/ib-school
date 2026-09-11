"""Restore a backup into a freshly initialized EMPTY Docker installation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from dc import ROOT, run
from deploy_env import read_env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    folder = args.folder.resolve()
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if not {'database.dump', 'media.tar.gz', '.env.deploy'} <= set(manifest):
        sys.exit('Incomplete backup.')
    for name, meta in manifest.items():
        if Path(name).name != name: sys.exit('Invalid manifest path.')
        digest = hashlib.sha256()
        with (folder / name).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
        if digest.hexdigest() != meta['sha256']: sys.exit(f'Backup checksum mismatch: {name}')
    saved, current = read_env(folder / '.env.deploy'), read_env(ROOT / '.env.deploy')
    for key in ['MFA_ENCRYPTION_KEY', 'DJANGO_SECRET_KEY']:
        if saved.get(key) != current.get(key):
            sys.exit('Import the keys from the backup .env.deploy before starting the new installation.')
    running = run(['ps', '--services', '--status', 'running'], capture_output=True, text=True, check=True).stdout.splitlines()
    writers = [s for s in running if s in {'web', 'judge', 'judge-local', 'autoquiz'}]
    if writers: sys.exit('Stop the web and background workers before restoring into the fresh installation.')
    # This guard runs before pg_restore drops any table from the empty installation.
    guard = "from django.contrib.auth import get_user_model; from courses.models import Course; from studio.models import Draft; from django.conf import settings; from pathlib import Path; assert not get_user_model().objects.exists() and not Course.objects.exists() and not Draft.objects.exists(), 'Database must be empty'; assert not any(Path(settings.MEDIA_ROOT).iterdir()), 'Media must be empty'"
    run(['run', '--rm', '--no-deps', 'web', 'python', 'backend/manage.py', 'shell', '-c', guard], check=True)
    with (folder / 'database.dump').open('rb') as stream:
        run(['exec', '-T', 'db', 'sh', '-c', 'exec pg_restore --clean --if-exists --no-owner --exit-on-error --single-transaction -U "$POSTGRES_USER" -d "$POSTGRES_DB"'], stdin=stream, check=True)
    with (folder / 'media.tar.gz').open('rb') as stream:
        run(['run', '--rm', '--no-deps', '-T', 'web', 'python', 'deploy/media_archive.py', 'unpack'], stdin=stream, check=True)
    print('Database and media restored. Start the application with tools/dc.py up -d.')


if __name__ == '__main__': main()
