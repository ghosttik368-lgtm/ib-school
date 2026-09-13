# syntax=docker/dockerfile:1
FROM docker:29-cli AS dockercli
FROM python:3.12-slim-bookworm AS base
ARG IB_SOURCE_REVISION=unknown
LABEL org.opencontainers.image.revision=$IB_SOURCE_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.container_settings PYTHONPATH=/app/backend \
    HOME=/home/app
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --create-home app
COPY requirements.txt requirements-deploy.txt requirements-autoquiz.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt
COPY backend/ backend/
COPY frontend/ frontend/
COPY tools/ tools/
COPY deploy/ deploy/
RUN mkdir -p backend/media backend/staticfiles .autoquiz_models /home/app/.ssh \
    && chown -R app:app backend/media backend/staticfiles .autoquiz_models /home/app
USER 10001:10001

FROM base AS web
CMD ["gunicorn", "--config", "deploy/gunicorn.conf.py", "config.wsgi:application"]

FROM base AS judge
USER root
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
USER 10001:10001
CMD ["python", "backend/manage.py", "judge_worker"]

FROM base AS autoquiz
ENV HF_HOME=/app/.autoquiz_models/.hf_cache \
    HF_XET_CACHE=/app/.autoquiz_models/.xet_cache XDG_CACHE_HOME=/tmp/cache
USER root
RUN pip install --no-cache-dir -r requirements-autoquiz.txt
USER 10001:10001
CMD ["python", "deploy/start_autoquiz.py"]
