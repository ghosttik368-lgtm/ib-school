"""A small, cross-platform wrapper around Docker Compose, not a replacement."""
import os
from pathlib import Path
import subprocess
import sys
from deploy_env import read_env

ROOT = Path(__file__).resolve().parent.parent


def command():
    values = read_env(ROOT / '.env.deploy')
    if not values:
        raise RuntimeError('Run tools/deploy_env.py first.')
    if values.get('DEPLOY_MODE') == 'local' and values.get('BIND_IP') != '127.0.0.1':
        raise RuntimeError('Local mode must bind to 127.0.0.1.')
    args = ['docker', 'compose', '--env-file', str(ROOT / '.env.deploy'), '-f', str(ROOT / 'compose.yaml')]
    if values.get('DEPLOY_MODE') == 'local':
        args.extend(['-f', str(ROOT / 'compose.local.yaml')])
    env = dict(os.environ)
    env.update(values)
    return args, env


def run(args, **kwargs):
    cmd, env = command()
    return subprocess.run([*cmd, *args], cwd=ROOT, env=env, **kwargs)


if __name__ == '__main__':
    try:
        result = run(sys.argv[1:] or ['ps'])
        sys.exit(result.returncode)
    except (RuntimeError, ValueError, OSError) as exc:
        sys.exit(f'Compose: {exc}')
