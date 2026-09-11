"""Check the Git index/history filenames before a push; never print secret values."""
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
BLOCKED_PARTS = {'backups', 'media', 'staticfiles', 'transfer', '.venv', 'venv', '__pycache__',
                 '.autoquiz_models', '.ollama', 'node_modules', '_alpha', 'secrets'}
BLOCKED_SUFFIXES = {'.sqlite', '.sqlite3', '.db', '.dump', '.sql', '.pem', '.key', '.pfx', '.p12',
                    '.gguf', '.safetensors', '.zip', '.7z', '.rar', '.tgz', '.mp4', '.webm', '.mov', '.mkv'}


def git(*args, check=True):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, check=check).stdout


def blocked(name):
    p = PurePosixPath(name.lower())
    if p.name.endswith('.example'):
        return False
    return (bool(set(p.parts) & BLOCKED_PARTS) or p.name.startswith('.env') or '.sqlite3-' in p.name or
            p.suffix in BLOCKED_SUFFIXES or p.name.startswith(('id_ed25519', 'id_rsa')) or
            p.name == 'known_hosts')


def main():
    files = [s.decode('utf-8') for s in git('ls-files', '-z').split(b'\0') if s]
    if not files:
        sys.exit('Git index is empty. Run git add . first, then repeat this check.')
    issues = []
    secrets = []
    for env in (ROOT / '.env', ROOT / '.env.deploy'):
        if env.exists():
            for line in env.read_text(encoding='utf-8-sig').splitlines():
                key, sep, value = line.partition('=')
                value = value.strip().strip('\"\'')
                if sep and any(w in key.upper() for w in ('PASSWORD', 'SECRET', 'TOKEN', 'ENCRYPTION_KEY')) and len(value) >= 16:
                    secrets.append(value.encode())
    for name in files:
        if blocked(name):
            issues.append(f'Private/runtime file in index: {name}')
            continue
        size = int(git('cat-file', '-s', ':' + name))
        if size > 20 * 1024**2:
            issues.append(f'Large file in index: {name}')
            continue
        data = git('show', ':' + name)
        if re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----', data):
            issues.append(f'Private key in: {name}')
        if any(value in data for value in secrets):
            issues.append(f'Value from local secrets file found in: {name}')
    history = git('log', '--all', '--pretty=format:', '--name-only', check=False).decode('utf-8', errors='replace')
    for name in sorted(set(history.splitlines())):
        if name and blocked(name):
            issues.append(f'Private/runtime file remains in Git history: {name}')
    if issues:
        print('\n'.join(issues))
        sys.exit('Check failed. Do not push yet. .gitignore does not erase files from past commits.')
    print(f'Checked {len(files)} indexed files and history filenames: no listed issues.')
    print('Also inspect git diff --cached and git status. This is a focused check, not a universal secret detector.')


if __name__ == '__main__':
    try: main()
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        sys.exit(f'Git check could not finish: {type(exc).__name__}. Run from an initialized project repository.')
