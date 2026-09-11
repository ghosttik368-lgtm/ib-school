"""Create/update .env.deploy without third-party Python packages or secret output."""
import argparse
import ast
import base64
import os
from pathlib import Path
import re
import secrets
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def read_env(path):
    values = {}
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.partition('=')
            if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
                raise ValueError(f'Unsupported configuration line in {path.name}.')
            value = value.strip()
            values[key] = ast.literal_eval(value) if value.startswith(('\"', "'")) else value
            if not isinstance(values[key], str):
                raise ValueError(f'Expected string value for {key}.')
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['local', 'server'])
    parser.add_argument('--site', help='Public hostname, for example learn.example.org')
    parser.add_argument('--ai', choices=['on', 'off'])
    parser.add_argument('--cpp', choices=['on', 'off'])
    parser.add_argument('--runner', help='ssh://judge@10.10.0.20')
    parser.add_argument('--behind-proxy', action='store_true')
    parser.add_argument('--import-keys', type=Path, help='Keep signing/MFA keys when importing existing data')
    args = parser.parse_args()
    target = ROOT / '.env.deploy'
    values = read_env(target)
    if not values:
        if not args.mode:
            parser.error('First run needs --mode local or --mode server --site HOSTNAME.')
        values = {
            'DEPLOY_MODE': args.mode,
            'COMPOSE_PROJECT_NAME': 'ib-school-local' if args.mode == 'local' else 'ib-school',
            'COMPOSE_PROFILES': '',
            'DJANGO_SECRET_KEY': secrets.token_urlsafe(60),
            'MFA_ENCRYPTION_KEY': base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
            'POSTGRES_DB': 'ib_school', 'POSTGRES_USER': 'ib_school',
            'POSTGRES_PASSWORD': secrets.token_urlsafe(40),
            'DB_ENGINE': 'postgresql', 'POSTGRES_HOST': 'db', 'POSTGRES_PORT': '5432',
            'DJANGO_DEBUG': '1' if args.mode == 'local' else '0',
            'DEV_DISABLE_MFA': '1', 'CADDY_CONFIG': 'Caddyfile',
            'AUTOQUIZ_MODEL': 'qwen3:4b-instruct-2507-q4_K_M',
            'AUTOQUIZ_WHISPER': 'medium', 'AUTOQUIZ_THREADS': '4', 'AUTOQUIZ_TIMEOUT': '600',
            'WEB_WORKERS': '2', 'WEB_THREADS': '4',
        }
    mode = values.get('DEPLOY_MODE')
    if args.mode and args.mode != mode:
        parser.error('Use a separate checkout for local/server mode; keep the existing .env.deploy and volumes.')
    if args.import_keys:
        existing = read_env(args.import_keys)
        for key in ('DJANGO_SECRET_KEY', 'MFA_ENCRYPTION_KEY'):
            if not existing.get(key):
                parser.error(f'{args.import_keys.name} is missing {key}.')
        values.update({key: existing[key] for key in ('DJANGO_SECRET_KEY', 'MFA_ENCRYPTION_KEY')})
    if mode == 'local':
        if args.site or args.behind_proxy or args.runner:
            parser.error('Local mode uses localhost; site/proxy/runner options are server-only.')
        values.update(SITE_ADDRESS='http://:80', BIND_IP='127.0.0.1', HTTP_PORT='8080', HTTPS_PORT='8443',
                      DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1',
                      CSRF_TRUSTED_ORIGINS='http://localhost:8080,http://127.0.0.1:8080')
    else:
        host = args.site or values.get('DJANGO_ALLOWED_HOSTS', '').split(',')[0]
        if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', host) or '.' not in host:
            parser.error('--site needs a hostname without https://, port or path.')
        values.update(SITE_ADDRESS=host, DJANGO_ALLOWED_HOSTS=host,
                      CSRF_TRUSTED_ORIGINS=f'https://{host}', DJANGO_DEBUG='0')
        behind = args.behind_proxy or values.get('CADDY_CONFIG') == 'Caddyfile.behind-proxy'
        values.update(BIND_IP='127.0.0.1' if behind else '0.0.0.0',
                      HTTP_PORT='8080' if behind else '80', HTTPS_PORT='8443' if behind else '443',
                      CADDY_CONFIG='Caddyfile.behind-proxy' if behind else 'Caddyfile')
    profiles = set(filter(None, values.get('COMPOSE_PROFILES', '').split(',')))
    for option, profile in ((args.ai, 'ai'), (args.cpp, 'cpp-local' if mode == 'local' else 'cpp')):
        if option == 'on': profiles.add(profile)
        if option == 'off': profiles.discard(profile)
    if args.runner:
        url = urlsplit(args.runner)
        if (url.scheme != 'ssh' or not url.hostname or not url.username or url.password or
                url.path or url.query or url.fragment or not re.fullmatch(r'[a-zA-Z0-9_.@:/\[\]-]+', args.runner)):
            parser.error('--runner needs ssh://USER@HOST[:PORT], without a password or path.')
        values['JUDGE_DOCKER_HOST'] = args.runner
    if mode == 'server' and 'cpp' in profiles and not values.get('JUDGE_DOCKER_HOST'):
        parser.error('Enable C++ with --cpp on --runner ssh://judge@RUNNER_IP after preparing the runner VM.')
    values['COMPOSE_PROFILES'] = ','.join(sorted(profiles))
    if any('\n' in v or '\r' in v for v in values.values()):
        parser.error('Configuration values must be single-line strings.')
    fd, temporary = tempfile.mkstemp(dir=ROOT, prefix='.env.deploy.tmp-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write('# Generated by tools/deploy_env.py. Keep this file private.\n')
            for key, value in values.items():
                quoted = value.replace('\\', '\\\\').replace("'", "\\'")
                stream.write(f"{key}='{quoted}'\n")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    print(f'{target.name} ready. Mode: {mode}. Profiles: {values["COMPOSE_PROFILES"] or "base"}.')
    print('Existing secrets are kept. This command does not change database contents.')


if __name__ == '__main__':
    main()
