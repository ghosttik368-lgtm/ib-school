"""Consistent backup: stop writers, dump PostgreSQL and media, resume same services."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
from dc import ROOT, run


def main():
    backup = ROOT / 'backups' / ('docker_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
    backup.mkdir(parents=True, mode=0o700)
    running = run(['ps', '--services', '--status', 'running'], capture_output=True, text=True, check=True).stdout.splitlines()
    writers = [s for s in running if s in {'web', 'judge', 'judge-local', 'autoquiz'}]
    if 'db' not in running:
        sys.exit('Database must be running for backup.')
    try:
        if writers: run(['stop', '--timeout', '45', *writers], check=True)
        with (backup / 'database.dump').open('wb') as stream:
            run(['exec', '-T', 'db', 'sh', '-c', 'exec pg_dump --format=custom --no-owner -U "$POSTGRES_USER" "$POSTGRES_DB"'], stdout=stream, check=True)
        with (backup / 'media.tar.gz').open('wb') as stream:
            run(['run', '--rm', '--no-deps', '-T', 'web', 'python', 'deploy/media_archive.py', 'pack'], stdout=stream, check=True)
        shutil.copy2(ROOT / '.env.deploy', backup / '.env.deploy')
        manifest = {}
        for path in backup.iterdir():
            if path.is_file():
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''): digest.update(chunk)
                manifest[path.name] = {'sha256': digest.hexdigest(), 'size': path.stat().st_size}
                if os.name != 'nt': path.chmod(0o600)
        (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(f'Backup complete: {backup}')
        print('It contains private data and keys. Copy it to separate protected storage, not Git.')
    finally:
        if writers: run(['start', *writers], check=True)


if __name__ == '__main__':
    main()
