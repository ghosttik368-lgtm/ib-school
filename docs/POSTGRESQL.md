# Проверка PostgreSQL отдельно от первого запуска

Нужен установленный Docker с Linux-контейнерами и Compose. Для обычного локального запуска SQLite он не нужен. Конфигурация PostgreSQL здесь не проверена на живом сервере.

Остановите Django. Сделайте копию базы, media и .env. Команды из корня проекта, PowerShell.

Если есть данные SQLite:

```powershell
New-Item -ItemType Directory -Force backups
$env:DB_ENGINE = "sqlite"
.\.venv\Scripts\python.exe backend\manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --exclude sessions --indent 2 --output backups\sqlite-data.json
```

JSON содержит конфиденциальные данные. Не присылайте его в чат. .env и MFA_ENCRYPTION_KEY сохраняются, media копируется отдельно.

Запуск PostgreSQL:

```powershell
docker compose --env-file .env -f deploy\compose.postgres.yml up -d
docker compose --env-file .env -f deploy\compose.postgres.yml ps
$env:DB_ENGINE = "postgresql"
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py test access
```

Ожидается healthy и успешные миграции/тесты. Затем только в новую пустую базу:

```powershell
.\.venv\Scripts\python.exe backend\manage.py loaddata backups\sqlite-data.json
.\.venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8000
```

Не создавайте нового владельца до импорта. Проверьте прежний вход, второй фактор, курсы, баллы. После успеха задайте в .env DB_ENGINE=postgresql, удалите временную переменную командой Remove-Item Env:DB_ENGINE и перезапустите Django. Для новой базы без старых данных вместо loaddata выполните createsuperuser.

Исходную SQLite сохраните. Возврат на неё не переносит новые записи из PostgreSQL. Не запускайте параллельно два рабочих сервера с разными базами. Не используйте docker compose down -v: это удаляет том с данными.

Порт PostgreSQL привязан к localhost. Compose предназначен для разработки; контейнерная роль имеет расширенные права. Перед настоящим размещением нужны ограниченная роль приложения, отдельная роль миграций и проверенные бэкапы. Если старый проект уже на PostgreSQL, этот SQLite-перенос не подходит: нужна сверка текущей схемы и обновление на восстановленной копии.
