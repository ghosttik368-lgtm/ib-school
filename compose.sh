#!/bin/sh
# Docker-only Linux entry point.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
docker compose version >/dev/null
if [ "$#" -eq 0 ]; then set -- up -d --build; fi
if [ "$1" = backup ]; then exec sh tools/backup_docker.sh; fi
if [ "$1" = init ]; then
    shift
    if [ "$#" -eq 0 ]; then set -- --mode local --ai off --cpp on; fi
    docker run --rm --user "$(id -u):$(id -g)" \
        --mount "type=bind,source=$PWD,target=/project" -w /project \
        python:3.12-slim-bookworm python tools/deploy_env.py "$@"
    exit 0
fi
if [ ! -f .env.deploy ]; then
    echo 'First run: sh compose.sh init (local), or see README.md for server settings.' >&2
    exit 1
fi
compose() {
    if grep -q "^DEPLOY_MODE='local'" .env.deploy; then
        docker compose --env-file .env.deploy -f compose.yaml -f compose.local.yaml "$@"
    elif grep -q "^DEPLOY_MODE='server'" .env.deploy; then
        docker compose --env-file .env.deploy -f compose.yaml "$@"
    else
        echo 'Unknown DEPLOY_MODE; see README.md.' >&2
        return 1
    fi
}
if [ "$1" = up ] && ! grep -q "^AUTOQUIZ_ENABLED='1'" .env.deploy; then
    compose --profile ai stop autoquiz ollama
fi
compose "$@"
