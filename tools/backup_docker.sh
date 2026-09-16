#!/bin/sh
# Consistent backup using Docker and POSIX shell, compatible with restore_backup.py.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
umask 077
running=$(sh compose.sh ps --services --status running)
printf '%s\n' "$running" | grep -qx db || { echo 'Database must be running.' >&2; exit 1; }
backup="backups/docker_$(date -u +%Y%m%d_%H%M%S)_$$"
mkdir -p "$backup"
writers=''
for service in $running; do
    case "$service" in web|judge|judge-local|autoquiz) writers="$writers $service" ;; esac
done
resume() {
    result=$?
    trap - 0
    if [ -n "$writers" ]; then sh compose.sh --profile ai --profile cpp --profile cpp-local start $writers || true; fi
    exit "$result"
}
trap resume 0
if [ -n "$writers" ]; then sh compose.sh --profile ai --profile cpp --profile cpp-local stop --timeout 45 $writers; fi
sh compose.sh exec -T db sh -c 'exec pg_dump --format=custom --no-owner -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$backup/database.dump"
sh compose.sh run --rm --no-deps -T web python deploy/media_archive.py pack > "$backup/media.tar.gz"
cp .env.deploy "$backup/.env.deploy"
docker run --rm --user "$(id -u):$(id -g)" --network none \
    --mount "type=bind,source=$PWD/$backup,target=/backup" python:3.12-slim-bookworm \
    python -c 'import hashlib,json,pathlib; root=pathlib.Path("/backup"); data={};
for p in root.iterdir():
 if p.is_file():
  h=hashlib.sha256()
  with p.open("rb") as f:
   for b in iter(lambda:f.read(1048576),b""):h.update(b)
  data[p.name]={"sha256":h.hexdigest(),"size":p.stat().st_size}
(root/"manifest.json").write_text(json.dumps(data,indent=2))'
echo "Backup complete: $backup (private data and keys; do not publish)."
