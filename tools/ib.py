"""One entry point: start, stop, status, check, import accounts, export/import USB bundle.

Host requirements: Python 3.10+ (standard library only), Docker with Compose v2.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from deploy_env import read_env
import dc

ROOT = Path(__file__).resolve().parent.parent
HELPER_IMAGE = 'python:3.12-slim-bookworm'


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], cwd=ROOT, check=True, **kwargs)


def compose(*args, **kwargs):
    return dc.run(list(args), check=True, **kwargs)


def docker_ready():
    run(['docker', 'info'], stdout=subprocess.DEVNULL)
    run(['docker', 'compose', 'version'], stdout=subprocess.DEVNULL)


def configure():
    values = read_env(ROOT / '.env.deploy')
    # Never change an existing installation's secrets, addresses or deployment mode.
    if not values:
        run([sys.executable, ROOT / 'tools/deploy_env.py', '--mode', 'local', '--ai', 'on', '--cpp', 'on'])
    else:
        run([sys.executable, ROOT / 'tools/deploy_env.py', '--ai', 'on', '--cpp', 'on'])
    return read_env(ROOT / '.env.deploy')


def require_local(values):
    if values.get('DEPLOY_MODE') != 'local':
        raise RuntimeError('USB-перенос рассчитан на локальную установку. Для сервера используйте DEPLOY_GUIDE_RU.md и штатную резервную копию.')


def has_image(name):
    return subprocess.run(['docker', 'image', 'inspect', name], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def source_revision():
    return digest(ROOT / 'source-manifest.json')


def image_revision(name):
    result = subprocess.run(['docker', 'image', 'inspect', '--format', '{{ index .Config.Labels "org.opencontainers.image.revision" }}', name],
                            cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ''


def wait_ollama(timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = dc.run(['exec', '-T', 'ollama', 'ollama', 'list'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError('Ollama не запустилась. Выполните py tools/dc.py logs --tail 80 ollama')


def models_ready(values, offline):
    wait_ollama()
    model = values['AUTOQUIZ_MODEL']
    found = dc.run(['exec', '-T', 'ollama', 'ollama', 'show', model], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not found:
        if offline:
            raise RuntimeError('В переносном комплекте нет нужной Qwen. Повторите export-usb на исходной машине.')
        compose('exec', '-T', 'ollama', 'ollama', 'pull', model)
    code = "import os,pathlib; p=pathlib.Path('/app/.autoquiz_models')/os.environ['AUTOQUIZ_WHISPER']; raise SystemExit(not all((p/f).is_file() for f in ('model.bin','config.json','tokenizer.json')))"
    ready = dc.run(['run', '--rm', '--no-deps', '-T', 'autoquiz', 'python', '-c', code]).returncode == 0
    if not ready:
        if offline:
            raise RuntimeError('В переносном комплекте нет полной Whisper. Повторите export-usb на исходной машине.')
        compose('run', '--rm', '--no-deps', '-T', 'autoquiz', 'python', 'backend/manage.py', 'autoquiz_prepare')


def start(build=False, offline=False):
    docker_ready()
    values = configure()
    local = values['DEPLOY_MODE'] == 'local'
    tag = values.get('IB_IMAGE_TAG', 'local')
    services = ['web', 'autoquiz', 'judge-local' if local else 'judge']
    images = ['ib-school-web:' + tag, 'ib-school-autoquiz:' + tag, 'ib-school-judge:' + tag]
    revision = source_revision()
    stale = any(image_revision(name) != revision for name in images)
    if offline:
        required = images + ['postgres:17-bookworm', 'caddy:2-alpine', 'ollama/ollama:0.34.0']
        if local:
            required.append('ib-cpp-runner:m34')
        missing = [name for name in required if not has_image(name)]
        if missing:
            raise RuntimeError('Не загружены Docker-образы: ' + ', '.join(missing))
        if stale:
            raise RuntimeError('Docker-образы не соответствуют этому выпуску исходников. Нужен свежий USB-комплект.')
    elif build or stale:
        compose('build', '--build-arg', 'IB_SOURCE_REVISION=' + revision, *services)
    if local and not offline and (build or stale or not has_image('ib-cpp-runner:m34')):
        run(['docker', 'build', '-t', 'ib-cpp-runner:m34', ROOT / 'runner'])
    policy = ['--pull', 'never'] if offline else []
    compose('up', '-d', '--no-build', *policy, 'db', 'initialize', 'ollama')
    models_ready(values, offline)
    compose('up', '-d', '--no-build', *policy)
    print('\nЗапущено. Сайт: ' + ('http://localhost:' + values.get('HTTP_PORT', '8080') if local else 'https://' + values['DJANGO_ALLOWED_HOSTS'].split(',')[0]))
    print('Проверка: py tools/ib.py check | Остановка: py tools/ib.py stop')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def volume_names():
    # Derive actual volume names from Compose; do not assume a directory-name prefix.
    result = compose('config', '--format', 'json', capture_output=True, text=True)
    config = json.loads(result.stdout)
    return {key: config['volumes'][key]['name'] for key in ('ollama_models', 'whisper_models')}


def copy_public_source(target):
    manifest = json.loads((ROOT / 'source-manifest.json').read_text(encoding='utf-8'))
    for relative, expected in manifest['files'].items():
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts:
            raise RuntimeError('Неверный путь в source-manifest.json')
        src = ROOT / path
        if src.is_symlink() or not src.is_file() or digest(src) != expected:
            raise RuntimeError(f'Изменён файл {relative}. Обновите source-manifest.json: py tools/source_manifest.py')
        dst = target / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    shutil.copyfile(ROOT / 'source-manifest.json', target / 'source-manifest.json')


def export_usb(destination):
    docker_ready()
    values = read_env(ROOT / '.env.deploy')
    require_local(values)
    if destination.exists():
        raise RuntimeError('Выберите новую пустую папку для USB-комплекта.')
    destination = destination.resolve()
    destination.mkdir(parents=True)
    try:
        # Finish downloads and verify the actual models before exporting.
        models_ready(values, offline=True)
        if not has_image(HELPER_IMAGE):
            run(['docker', 'pull', HELPER_IMAGE])
        tag = values.get('IB_IMAGE_TAG', 'local')
        images = ['ib-school-web:' + tag, 'ib-school-autoquiz:' + tag, 'ib-school-judge:' + tag,
                  'ib-cpp-runner:m34', 'postgres:17-bookworm', 'caddy:2-alpine', 'ollama/ollama:0.34.0', HELPER_IMAGE]
        if any(image_revision(name) != source_revision() for name in images[:3]):
            raise RuntimeError('Сначала пересоберите текущие исходники: py tools/ib.py start --build')
        arch = run(['docker', 'info', '--format', '{{.Architecture}}'], capture_output=True, text=True).stdout.strip()
        copy_public_source(destination / 'project')
        run(['docker', 'image', 'save', '-o', destination / 'images.tar', *images])
        volumes = volume_names()
        for key, volume in volumes.items():
            member = 'models' if key == 'ollama_models' else values['AUTOQUIZ_WHISPER']
            if not re.fullmatch(r'[a-zA-Z0-9_-]+', member):
                raise RuntimeError('Неверное имя папки модели.')
            run(['docker', 'run', '--rm', '--network', 'none', '--user', '0:0',
                 '--mount', f'type=volume,source={volume},target=/source,readonly',
                 '--mount', f'type=bind,source={destination},target=/out', HELPER_IMAGE,
                 'tar', '-czf', '/out/' + key + '.tar.gz', '-C', '/source', member])
        files = {p.relative_to(destination).as_posix(): digest(p) for p in destination.rglob('*') if p.is_file()}
        info = {'format': 'ib-usb-v1', 'architecture': arch, 'models': {k: values[k] for k in ('AUTOQUIZ_MODEL', 'AUTOQUIZ_WHISPER')},
                'image_tag': tag, 'files': files}
        (destination / 'usb-manifest.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception:
        print('Экспорт не завершён. Папка оставлена для диагностики; не используйте её для развёртывания.', file=sys.stderr)
        raise
    print(f'Готово: {destination}. Пользователей и курсов в этом комплекте нет; переносите их отдельным архивом.')


def import_usb(source):
    docker_ready()
    source = source.resolve()
    info = json.loads((source / 'usb-manifest.json').read_text(encoding='utf-8'))
    if info.get('format') != 'ib-usb-v1':
        raise RuntimeError('Неверный формат USB-комплекта.')
    current_arch = run(['docker', 'info', '--format', '{{.Architecture}}'], capture_output=True, text=True).stdout.strip()
    if current_arch != info['architecture']:
        raise RuntimeError('Архитектура Docker отличается от исходной машины. Нужна одинаковая архитектура CPU.')
    for name, expected in info['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or not (source / relative).is_file() or digest(source / relative) != expected:
            raise RuntimeError(f'Повреждён или отсутствует файл комплекта: {name}')
    if (ROOT / '.env.deploy').exists():
        raise RuntimeError('USB-импорт выполняется только в свежей копии проекта без .env.deploy. Существующая установка не изменена.')
    # Refuse a machine with existing volumes under the default project name.
    existing = run(['docker', 'volume', 'ls', '-q', '--filter', 'label=com.docker.compose.project=ib-school-local'], capture_output=True, text=True).stdout.strip()
    if existing:
        raise RuntimeError('На этой машине уже есть данные ib-school-local. Импорт не будет их перезаписывать.')
    run(['docker', 'image', 'load', '-i', source / 'images.tar'])
    values = configure()
    # Keep source model selection and image tags without carrying deployment secrets.
    env_path = ROOT / '.env.deploy'
    extra = {**info['models'], 'IB_IMAGE_TAG': info['image_tag']}
    if any(not re.fullmatch(r'[A-Za-z0-9_.:/-]+', str(v)) for v in extra.values()):
        raise RuntimeError('Неверные имена моделей или тег образа.')
    lines = env_path.read_text(encoding='utf-8').splitlines()
    lines = [line for line in lines if line.partition('=')[0] not in extra]
    lines.extend(f"{key}='{value}'" for key, value in extra.items())
    env_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    for key, volume in volume_names().items():
        run(['docker', 'volume', 'create', '--label', 'com.docker.compose.project=ib-school-local',
             '--label', 'com.docker.compose.volume=' + key, volume], stdout=subprocess.DEVNULL)
        # Python tar extraction rejects paths, links and special files before writing.
        code = "import tarfile,pathlib,os; t=tarfile.open('/in/' + __import__('sys').argv[1]); ms=t.getmembers(); assert all(m.isfile() or m.isdir() for m in ms), 'Special archive entry'; t.extractall('/target', filter='data'); [os.chown(p,10001,10001) for p in [pathlib.Path('/target'),*pathlib.Path('/target').rglob('*')]]"
        run(['docker', 'run', '--rm', '--network', 'none', '--user', '0:0',
             '--mount', f'type=volume,source={volume},target=/target',
             '--mount', f'type=bind,source={source},target=/in,readonly', HELPER_IMAGE,
             'python', '-c', code, key + '.tar.gz'])
    start(offline=True)


def import_accounts(path):
    path = path.resolve()
    if not path.is_file() or path.name != 'accounts.json':
        raise RuntimeError('Укажите accounts.json из отдельного архива аккаунтов.')
    # A one-off container mounts only that file; plaintext credentials never enter a web container.
    compose('run', '--rm', '--no-deps', '-T', '--volume', f'{path}:/private/accounts.json:ro',
            'web', 'python', 'backend/manage.py', 'import_accounts', '/private/accounts.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('start'); p.add_argument('--build', action='store_true'); p.add_argument('--offline', action='store_true')
    for name in ('stop', 'status', 'check'):
        sub.add_parser(name)
    for name in ('import-accounts', 'export-usb', 'import-usb'):
        p = sub.add_parser(name); p.add_argument('path', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'start': start(args.build, args.offline)
        elif args.action == 'stop': compose('stop')
        elif args.action == 'status': compose('ps', '-a')
        elif args.action == 'check':
            compose('exec', '-T', 'web', 'python', 'backend/manage.py', 'check')
            compose('exec', '-T', 'autoquiz', 'python', 'backend/manage.py', 'autoquiz_check', '--probe')
            judge = 'judge-local' if read_env(ROOT / '.env.deploy').get('DEPLOY_MODE') == 'local' else 'judge'
            compose('exec', '-T', judge, 'python', 'backend/manage.py', 'check_runner')
            compose('ps', '-a')
        elif args.action == 'import-accounts': import_accounts(args.path)
        elif args.action == 'export-usb': export_usb(args.path)
        elif args.action == 'import-usb': import_usb(args.path)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Операция остановлена: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
