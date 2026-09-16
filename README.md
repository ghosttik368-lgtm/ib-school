# ИБ — обучающая платформа

Курсы, видео, документы, тесты, C++, чат, рейтинг и аналитика. **AI по умолчанию выключен. GPU, Ollama и Whisper для обычной работы не нужны.** Загрузка видео только сохраняет файл, без распознавания.

## Сервер кафедры (Linux)

Нужны Docker Engine с Compose v2. Python на хосте не требуется. Из папки проекта:

    sh compose.sh init --mode server --site learn.example.org --ai off --cpp off
    sh compose.sh up -d --build

Замените домен своим. Сайт открывается по HTTPS. На этом этапе запускаются веб-платформа и PostgreSQL. **Исполнение C++ подключается через отдельную VM с Docker**; ей GPU также не нужна. Подготовка VM, включение C++, импорт аккаунтов: [docs/SERVER_RU.md](docs/SERVER_RU.md).

Если HTTPS уже обслуживает другой proxy на этом же хосте, добавьте --behind-proxy согласно серверной инструкции.

Порты снаружи: **80/TCP, 443/TCP**. Django 8000 и PostgreSQL 5432 доступны только внутри Docker. C++ использует SSH к VM, обычно 22/TCP. [Полная таблица портов](docs/PORTS_RU.md).

## Локально на Windows

Нужны Docker Desktop с WSL 2 и Python 3.10+. Из корня проекта:

    py tools/ib.py start

Или START.cmd. Сайт: **http://localhost:8080**. Сайт, PostgreSQL и C++ работают в Docker. Модели не скачиваются, виртуальное окружение не требуется. При первом запуске нужен интернет для Docker-образов и пакетов.

Локально на Linux без Python:

    sh compose.sh init
    sh compose.sh up -d --build

Образ песочницы C++ автоматически собирается Compose. Этот режим доступен только на localhost; не публикуйте его наружу.

## Аккаунты

Прежний приватный архив IB_ACCOUNTS_1000_PRIVATE.zip совместим: 850 студентов, 100 преподавателей, 50 администраторов. В новой пустой установке:

    py tools/ib.py import-accounts "D:\IB_ACCOUNTS_1000_PRIVATE\accounts.json"

Для Linux без Python команда приведена в SERVER_RU.md. Вход: admin001, пароль из credentials.csv. При первом входе каждый пользователь меняет выданный пароль. Импорт не перезаписывает существующих пользователей. Docker использует PostgreSQL и accounts.json; SQLite-файл не нужно копировать в Docker.

## Обновление

Сначала резервная копия: **sh compose.sh backup** на Linux или **py tools/backup_compose.py** на Windows. Дождитесь Backup complete.

Linux:

    git pull --ff-only
    sh compose.sh init --ai off
    sh compose.sh up -d --build

На предыдущем выпуске compose.sh ещё нет: сначала сделайте копию прежней командой python3 tools/backup_compose.py, затем обновляйте Git.

Windows:

    git pull --ff-only
    py tools/ib.py start --build

AI выключится, старые AI-контейнеры остановятся. Модели, курсы, очереди, ключи и настройки C++ сохраняются. Не меняйте имя Compose-проекта и не удаляйте .env.deploy. **Не выполняйте down -v: это удаляет тома с данными.**

## Управление

    py tools/ib.py status
    py tools/ib.py check
    py tools/ib.py stop

Проверка не требует нейросетей при AI=off. Linux: sh compose.sh ps -a, sh compose.sh logs --tail 100, sh compose.sh stop. Статус initialize/runner-image Exited (0) нормален: это одноразовые служебные контейнеры.

## AI и флешка

AI включается только явно: **py tools/ib.py start --with-ai**. [Отдельная инструкция](docs/AI_OPTIONAL_RU.md).

    py tools/ib.py export-usb "D:\IB_USB"

При выключенном AI комплект содержит исходники и образы без весов моделей. На новой подготовленной машине из IB_USB/project: py tools/ib.py import-usb "..". Аккаунты передаются отдельно. [Перенос без интернета](docs/USB_RU.md).

[Оформление по брендбуку](docs/BRAND_RU.md). Старые инструкции M1–M6 хранятся в docs/history.
