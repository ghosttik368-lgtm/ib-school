#!/bin/sh
set -eu
rm -f /tmp/runner-ready
dockerd-entrypoint.sh &
daemon=$!
trap 'kill -TERM "$daemon" 2>/dev/null || true; wait "$daemon" || true' TERM INT EXIT
until docker -H unix:///var/run/docker.sock info >/dev/null 2>&1; do
    kill -0 "$daemon" 2>/dev/null || exit 1
    sleep 1
done
# Client certificates are mounted only in the trusted judge container.
chmod 644 /certs/client/*.pem
docker -H unix:///var/run/docker.sock build -t ib-cpp-runner:m34 /opt/ib-runner
touch /tmp/runner-ready
wait "$daemon"
