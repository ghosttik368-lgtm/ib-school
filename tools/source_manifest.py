"""Record only deployable source. Runtime data and issued accounts are never included."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRS = ('backend', 'frontend', 'tools', 'deploy', 'runner', 'docs', '.github')
EXCLUDED_PARTS = {'__pycache__', 'media', 'staticfiles', 'secrets', 'private', 'backups', 'transfer', '.git', 'node_modules', '.venv', 'venv'}
SUFFIXES = {'.py', '.html', '.css', '.js', '.svg', '.png', '.jpg', '.ico', '.ttf', '.otf', '.woff', '.woff2', '.txt', '.md', '.json', '.yaml', '.yml', '.sh', '.ps1', '.cmd'}
NAMES = {'LICENSE', 'Runner.Dockerfile', 'Dockerfile', 'Caddyfile', 'Caddyfile.behind-proxy', '.gitkeep', '.gitignore', '.dockerignore', '.gitattributes', '.env.example', '.env.deploy.example'}
ROOT_NAMES = {'README.md', 'START.txt', 'START.cmd', 'compose.sh', 'compose.yaml', 'compose.legacy.yaml', 'compose.ai.yaml', 'compose.local.yaml', 'requirements.txt', 'requirements-autoquiz.txt', 'requirements-deploy.txt', 'DEPLOY_GUIDE_RU.md', 'VALIDATION_RU.md'} | NAMES


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files():
    paths = [ROOT / name for name in ROOT_NAMES if (ROOT / name).is_file()]
    for folder in DIRS:
        for path in (ROOT / folder).rglob('*'):
            relative = path.relative_to(ROOT)
            if not path.is_file() or path.is_symlink() or EXCLUDED_PARTS.intersection(relative.parts):
                continue
            if path.name.startswith('.env') and path.name not in NAMES:
                continue
            if path.suffix in SUFFIXES or path.name in NAMES:
                paths.append(path)
    # Explicitly reject account exports even if someone misplaced one beside source code.
    return sorted(p for p in paths if p.name not in {'accounts.json', 'credentials.csv', 'credentials.json', 'passwords.txt', 'seed-result.json'})


if __name__ == '__main__':
    manifest = {'format': 'ib-source-v1', 'files': {p.relative_to(ROOT).as_posix(): digest(p) for p in source_files()}}
    (ROOT / 'source-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Манифест исходников обновлён: {len(manifest['files'])} файлов.")
