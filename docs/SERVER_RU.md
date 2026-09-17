# Запуск одной командой

После получения проекта нужны только Docker Engine/Desktop с Compose 2.24+ и Linux containers. В папке с compose.yaml:

```bash
docker compose up -d --build
```

Сайт: http://IP-СЕРВЕРА или http://localhost. Никаких предварительных init, pip, SSH и второй VM. Все зависимости устанавливаются внутри контейнеров автоматически. Первый запуск требует доступа к Docker Hub, PyPI и Debian-репозиториям. Компилятор бесплатный.

Статус: `docker compose ps -a`. bootstrap и initialize со статусом Exited (0) — нормальный результат. У runner первая сборка может занять несколько минут; judge запускается после его готовности.

## Устройство

- bootstrap создаёт уникальные ключи и пароли в постоянном томе runtime.
- db — PostgreSQL, initialize — миграции, статика и начальные аккаунты.
- web и proxy — сайт.
- runner — собственный Docker daemon, автоматически собирающий образ GNU C++.
- judge — очередь проверки, обращается к runner по TLS внутри Docker.

runner использует **privileged Docker-in-Docker**. Это явный компромисс односерверной установки: контейнеры делят ядро хоста, такая изоляция не равна отдельной VM. Docker-сокет хоста, домашние каталоги и база в runner не монтируются; Docker API не публикуется наружу. Каждое решение работает без сети, от непривилегированного пользователя, с ограничениями времени, памяти и процессов. Docker должен разрешать privileged-контейнеры.

## Аккаунты

В пустой установке без private/accounts.json автоматически создаётся admin. Пароль:

```bash
docker compose exec web cat /run/ib/admin-password
```

Чтобы сразу получить 1000 выданных аккаунтов, ДО первого запуска положите accounts.json в private/accounts.json. Импорт автоматический; используйте admin001 и его выданный пароль. Существующая база никогда не очищается. Если уже созданы пользователи, импорт пропускается; не удаляйте ради него базу с курсами.

## Переход со старой установки

Сделайте прежнюю резервную копию до git pull. Для старого выпуска: `sh compose.sh backup`.

Сохраните .env.deploy. Для прежнего серверного проекта ib-school:

```bash
git pull --ff-only
docker compose --env-file .env.deploy up -d --build --remove-orphans
```

--remove-orphans останавливает старые worker/AI-контейнеры, отсутствующие в новой конфигурации; тома не удаляются. Имеющиеся ключи и пароль PostgreSQL импортируются из .env.deploy при первом создании runtime. Для старого локального проекта оставьте COMPOSE_PROJECT_NAME=ib-school-local в .env.deploy: предыдущая команда использует именно его тома. Пользователи, материалы и курсы сохраняются. Запускайте дальнейшие команды с тем же --env-file .env.deploy. Не переключайте имя проекта, иначе Docker создаст другой набор томов.

Если использовался нестандартный proxy, сохраняются HTTP_PORT, HTTPS_PORT, BIND_IP и CADDY_CONFIG из .env.deploy при указанном --env-file. Домен хранится в runtime; поменять его можно переменной IB_SITE.

Старая схема с SSH-VM и команды tools/ib.py, tools/dc.py, compose.sh оставлены для совместимости и используют **compose.legacy.yaml**. Для новой схемы используйте обычный docker compose. Не запускайте обе схемы одновременно под одним именем проекта.

## Последующие обновления новой установки

Сначала резервная копия, затем:

```bash
git pull --ff-only
docker compose up -d --build
```

Runtime сохраняет ключи и пароль БД. Пароль существующего admin не сбрасывается.

## Резервная копия и восстановление новой схемы

Остановите запись и сохраните базу, материалы и runtime. Команды ниже для bash/Linux; выполняются из папки проекта. Для старой установки добавляйте --env-file .env.deploy ко всем docker compose.

```bash
mkdir -p backups
docker compose stop web judge
docker compose exec -T db sh -c 'pg_dump -Fc -U "$(cat /run/ib/db-user)" "$(cat /run/ib/db-name)"' > backups/database.dump
docker compose run --rm --no-deps -T web tar -czf - -C / run/ib app/backend/media > backups/files.tar.gz
docker compose start web judge
```

Если AI включён, также остановите autoquiz через оба compose-файла до копирования и запустите после. Архив files.tar.gz содержит ключи и исходный пароль admin — храните его приватно вместе с database.dump. Не публикуйте в GitHub.

Для восстановления на НОВОЙ машине с пустыми томами (не для наложения поверх рабочих данных):

```bash
docker compose build web
docker compose run --rm --no-deps bootstrap
# Восстановить настройки ДО создания новой PostgreSQL:
docker compose run --rm --no-deps -T restore tar -xzf - -C / < backups/files.tar.gz
docker compose run --rm --no-deps bootstrap
docker compose up -d db
docker compose exec -T db sh -c 'pg_restore --clean --if-exists --no-owner --exit-on-error -U "$(cat /run/ib/db-user)" -d "$(cat /run/ib/db-name)"' < backups/database.dump
docker compose up -d --build
```

Перед pg_restore дождитесь healthy у db (`docker compose ps`). При восстановлении используйте те же имена и конфигурацию томов; для архивов прежней схемы действует прежний restore_backup.py, это другой формат. Для ручного восстановления томов обратитесь к администратору Docker.

[Все порты](PORTS_RU.md). [C++](CPP_RU.md). [Прежняя SSH-схема](SERVER_LEGACY_RU.md).
