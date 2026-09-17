# Сервер кафедры: без GPU и обязательного AI

Нужны Linux и работающий Docker Engine с Compose v2. Python, Ollama, Whisper и g++ на хост не устанавливаются. По умолчанию сервер только хранит/отдаёт видео. Обычные тесты создаются в редакторе.

## 1. Веб-платформа

В папке с compose.yaml:

    sh compose.sh init --mode server --site learn.example.org --ai off --cpp off
    sh compose.sh up -d --build
    sh compose.sh ps -a

Замените домен своим, направленным на сервер. Для автоматического публичного сертификата Caddy нужны корректный DNS и доступные 80/443. Сайт: https://ВАШ-ДОМЕН.

Уже работают курсы, материалы, видео, обычные тесты, сообщения, рейтинги и аналитика. **Проверку C++ включает следующий шаг.** initialize со статусом Exited (0) означает успешное завершение миграций и сбора статики.

compose.sh — оболочка над стандартным Docker Compose. После init сервер можно запустить напрямую:

    docker compose --env-file .env.deploy up -d --build

Оболочка дополнительно останавливает старые AI-контейнеры, когда AI выключен.

Если HTTPS уже обслуживает proxy на этом же хосте, добавьте к init **--behind-proxy** и направьте proxy на 127.0.0.1:8080 с заголовком X-Real-IP. Для частного домена используйте доверенный сертификат на существующем proxy. Local-режим не предназначен для публикации.

## 2. C++: отдельная Linux-VM с Docker, без GPU

Существующая серверная схема исполняет чужой код на отдельной VM, отделённой от базы и сайта. На VM нужен SSH-пользователь judge с доступом к Docker. Ограничения памяти, времени, процессов и отключение сети задаёт проверяющий.

На сервере сайта, **если выделенный ключ ещё не создан**:

    mkdir -p deploy/secrets/judge
    ssh-keygen -t ed25519 -f deploy/secrets/judge/id_ed25519 -N ''
    ssh-copy-id -i deploy/secrets/judge/id_ed25519.pub judge@RUNNER_IP
    ssh -i deploy/secrets/judge/id_ed25519 -o UserKnownHostsFile=deploy/secrets/judge/known_hosts judge@RUNNER_IP docker info
    scp -i deploy/secrets/judge/id_ed25519 -o UserKnownHostsFile=deploy/secrets/judge/known_hosts -r runner judge@RUNNER_IP:~/ib-runner
    ssh -i deploy/secrets/judge/id_ed25519 -o UserKnownHostsFile=deploy/secrets/judge/known_hosts judge@RUNNER_IP 'docker build -t ib-cpp-runner:m34 ~/ib-runner'
    chmod 600 deploy/secrets/judge/id_ed25519
    chmod 644 deploy/secrets/judge/known_hosts deploy/secrets/judge/id_ed25519.pub
    sudo chown -R 10001:10001 deploy/secrets/judge
    sh compose.sh init --cpp on --runner ssh://judge@RUNNER_IP --ai off
    sh compose.sh up -d --build
    sh compose.sh exec -T judge python backend/manage.py check_runner

Замените RUNNER_IP. При первом подключении сверьте fingerprint по консоли VM. Не перезаписывайте существующий ключ; не загружайте приватный ключ в Git. Worker в Compose работает с UID 10001. Выделенный ключ без парольной фразы нужен для фонового SSH.

Теперь работает весь прежний функционал кроме отключённого AI. Без отдельной VM сайт можно запустить сразу, но компиляция останется выключенной. Docker TCP 2375 не требуется.

## 3. Аккаунты

Приватный архив прежний. Поместите accounts.json в private/accounts.json проекта; эта папка исключена из Git. До импорта база не должна содержать пользователей:

    sh compose.sh run --rm --no-deps -T --volume "$PWD/private/accounts.json:/private/accounts.json:ro" web python backend/manage.py import_accounts /private/accounts.json

Вход: admin001, пароль из приватной CSV. PostgreSQL уже подключён Compose; SQLite-файл не нужен.

## 4. Обновление

В текущем выпуске резервная копия без Python на хосте:

    sh compose.sh backup

Дождитесь Backup complete. Сохраняются PostgreSQL, материалы и ключи, запись временно останавливается. На предыдущем выпуске compose.sh ещё отсутствует: используйте прежнюю python3 tools/backup_compose.py перед обновлением. Если установка ещё не содержит данных, резервировать нечего.

Затем:

    git pull --ff-only
    sh compose.sh init --ai off
    sh compose.sh up -d --build
    sh compose.sh exec -T web python backend/manage.py check

Старые AI-контейнеры останавливаются; модели, очереди и курсы не удаляются. Не меняйте COMPOSE_PROJECT_NAME, не удаляйте .env.deploy и не выполняйте down -v. Существующий local/server режим автоматически не меняется. Перенос на новую машину: резервная копия и docs/DEPLOY_ADVANCED_RU.md.

## Управление

    sh compose.sh logs --tail 100 web initialize judge
    sh compose.sh stop
    sh compose.sh up -d

[Порты](PORTS_RU.md). [AI как отдельная опция](AI_OPTIONAL_RU.md).

Обновлённый C++: [инструкция и диагностика](CPP_RU.md).
