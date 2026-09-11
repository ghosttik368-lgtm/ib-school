**Обучающая платформа — закрытый Git и развёртывание через Docker Compose**

Этот гайд предназначен для текущего проекта M5/M6 с установленным AUTOQUIZ. На компьютере — Windows 11 и PowerShell; на сервере предполагается Ubuntu Server 24.04 LTS, x86-64. Для другой серверной ОС понадобится соответствующая установка Docker.

**Что подготовлено**

Название на главной странице и сопутствующие подписи заменены на «Обучающая платформа». Знак «ИБ» сохранён. Установщик также ищет полную старую фразу в текущем коде интерфейса. Содержимое загруженных преподавателем документов, видео и записей базы он не переписывает.

| Файл / папка | Назначение |
|---|---|
| `backend/` | Существующий Django: пользователи, курсы, сообщения, задания, рейтинг |
| `frontend/` | Существующие шаблоны, стили и JavaScript |
| `runner/` | Образ изолированного запуска C++ |
| `deploy/Dockerfile` | Образы сайта, обработчика C++ и обработчика автотестов |
| `compose.yaml` | PostgreSQL, сайт, HTTPS, дополнительные AI/C++ сервисы |
| `compose.local.yaml` | Проверка C++ через Docker Desktop только на локальном компьютере |
| `backend/config/container_settings.py` | Отдельные настройки контейнеров |
| `.gitignore`, `.dockerignore` | Исключение личных данных из Git и контекста Docker-сборки |
| `tools/deploy_env.py` | Создание и изменение настроек Docker без ручной генерации паролей |
| `tools/dc.py` | Короткий вызов Docker Compose с нужными файлами и настройками |
| `tools/git_check.py` | Проверка подготовленного коммита и имён файлов в истории |
| `tools/export_existing.py`, `tools/import_transfer.py` | Перенос существующих данных в новую установку |
| `tools/backup_compose.py` | Резервная копия работающей установки Docker |

Закрытый Git хранит исходники. Видео, база, пароли и веса моделей хранятся отдельно. **Приглашение в репозиторий и приглашение ученика на платформу — два разных доступа.** Ученикам доступ к Git не нужен.

**1. Установить обновление на Windows**

Останови `runserver`, `judge_worker`, `autoquiz_worker`: в каждом их терминале нажми Ctrl+C. Сам Docker Desktop закрывать не требуется.

Скачай архив `IB_GIT_DOCKER_UPDATE.zip` в «Загрузки». Открой PowerShell в VS Code:

```powershell
Set-Location "C:\Users\NIK\Desktop\cyber\_coures"
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\IB_GIT_DOCKER_UPDATE.zip" -DestinationPath "$env:USERPROFILE\Downloads\IB_GIT_DOCKER_UPDATE" -Force
.\.venv\Scripts\python.exe "$env:USERPROFILE\Downloads\IB_GIT_DOCKER_UPDATE\install_git_docker.py" --project "."
.\.venv\Scripts\python.exe backend\manage.py check
.\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
```

Ожидается `System check identified no issues` и `No changes detected`. Установщик сохраняет прежние изменяемые файлы в `backups/git_docker_...`; базу, `.env` и старые миграции не заменяет. При несовместимом файле остановится до записи. При ошибке проверки отменит свои изменения.

Полные новые файлы лежат в `payload` архива, но копировать их вручную не требуется. **Не заменяй папку `courses/migrations` архивами прежних модулей:** твоя исправленная последовательность миграций должна попасть в Git как есть.

Проверить новое название в привычном режиме:

```powershell
.\.venv\Scripts\python.exe backend\manage.py runserver
```

Открой `http://127.0.0.1:8000/`, войди и обнови страницу. После проверки останови сервер Ctrl+C, если переходишь к Docker.

**2. Создать закрытый репозиторий GitHub**

Выбираем GitHub Free: он поддерживает приватные репозитории и приглашённых участников без покупки подписки. Ограничения отдельных дополнительных функций перечислены в [описании тарифов GitHub](https://docs.github.com/en/get-started/learning-about-github/githubs-plans).

1. Войди в свой аккаунт на [GitHub](https://github.com/).
2. Нажми **+ → New repository**.
3. Название: `ib-school`.
4. Видимость: **Private**. Проверь это до создания.
5. Не добавляй на сайте README, `.gitignore` и лицензию: файлы уже подготовлены локально.
6. Нажми **Create repository**.
7. Скопируй HTTPS-адрес нового репозитория: он выглядит как `https://github.com/ТВОЙ_ЛОГИН/ib-school.git`.

GitHub хранит код, а сервер будет запускать сайт. GitHub Pages для этого Django-проекта не используется.

**3. Подготовить Git в папке проекта**

В PowerShell сначала проверь, есть ли уже репозиторий:

```powershell
Set-Location "C:\Users\NIK\Desktop\cyber\_coures"
git rev-parse --show-toplevel
```

Если ответ `fatal: not a git repository`, это нормально для первого запуска. Выполни:

```powershell
git init -b main
```

Если выведена папка `_coures`, Git уже настроен: `git init` повторно не нужен. Если выведена другая, родительская папка, не добавляй всё подряд: репозиторий сейчас охватывает больше файлов, чем проект.

Настрой имя и email автора коммитов. После каждой строки с `Read-Host` введи запрошенное значение, нажми Enter, затем выполняй следующую команду:

```powershell
$ibGitName = Read-Host "Имя автора коммитов"
$ibGitEmail = Read-Host "Email GitHub или адрес noreply из настроек GitHub"
git config --local user.name "$ibGitName"
git config --local user.email "$ibGitEmail"
git add .
.\.venv\Scripts\python.exe tools\git_check.py
git status --short
git diff --cached --stat
```

В подготовленном коммите должны быть `backend`, `frontend`, `runner`, `deploy`, `tools`, миграции и файлы зависимостей. Не должно быть `.env`, `.env.deploy`, баз, видео, резервных копий, `.venv`, скачанных моделей и SSH-ключей. Проверка не заменяет просмотр списка: старые копии проекта в произвольных папках тоже не добавляй.

Если проверка обнаружила файл **только в индексе**, например `.env`:

```powershell
git rm --cached -- .env
.\.venv\Scripts\python.exe tools\git_check.py
```

Это убирает файл из Git, сохраняя его на диске. Для ошибочно добавленной папки, например `backups`, команда — `git rm -r --cached -- backups`.

Если проверка сообщает про **Git history**, файл уже был в прошлых коммитах. Пока не отправляй историю: `.gitignore` её не очищает. Нужно отдельно очистить историю, а уже опубликованные секреты заменить; [официальная инструкция GitHub](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository). Автоматического удаления твоей истории в этом обновлении нет.

**4. Отправить код в приватный репозиторий**

Продолжай после успешной проверки:

```powershell
git commit -m "Prepare platform for Docker Compose deployment"
git branch --show-current
git remote -v
```

Для нового репозитория ветка будет `main`. Если у существующего проекта ветка называется иначе, используй её имя в команде отправки; не переименовывай чужие рабочие ветки автоматически.

Если `git remote -v` ничего не вывел, добавь адрес, скопированный на шаге 2:

```powershell
$ibRepoUrl = Read-Host "HTTPS-адрес твоего приватного репозитория"
git remote add origin "$ibRepoUrl"
git push -u origin main
```

При первой отправке Git for Windows обычно предложит вход в GitHub через браузер. Войди своим аккаунтом. Обычный пароль GitHub в терминал для HTTPS Git не подходит; используй менеджер учётных данных. Не помещай токен внутрь URL. Подробнее — [вход в Git через HTTPS](https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git).

Если `origin` уже есть, сначала проверь, что это нужный приватный репозиторий. Для правильного адреса достаточно `git push -u origin main`. Не используй `--force`, чтобы обойти сообщение об отличающейся удалённой истории.

Открой страницу репозитория: рядом с названием должна быть отметка **Private**. Убедись, что файлы появились. В приватном окне браузера без входа этот репозиторий не должен быть доступен.

**5. Дать доступ преподавателю или соавтору**

В репозитории открой **Settings → Collaborators / Manage access → Add people**, найди человека по его GitHub-логину и отправь приглашение. Человек должен принять его. Для отзыва доступа удали его из этого же списка. Порядок действий описан в [инструкции по приглашениям GitHub](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/inviting-collaborators-to-a-personal-repository).

В личном репозитории приглашённый collaborator получает возможность изменять код. Если преподавателю нужен исключительно просмотр, создай бесплатную GitHub Organization и выдай на её приватный репозиторий роль **Read**. О правах личного репозитория — [документация GitHub](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/permission-levels-for-a-personal-account-repository).

Приватность ограничивает доступ к репозиторию, но не запрещает приглашённому участнику сохранить уже доступную ему копию. Приглашай только тех, кому разрешено получить исходники.

**6. Проверить Docker на своём Windows**

Это отдельная установка с собственной PostgreSQL и собственными данными. Твоя база `backend/db.sqlite3` продолжит существовать. Docker Desktop должен работать в режиме Linux containers.

```powershell
docker version
docker compose version
.\.venv\Scripts\python.exe tools\deploy_env.py --mode local
.\.venv\Scripts\python.exe tools\dc.py config --quiet
.\.venv\Scripts\python.exe tools\dc.py up -d --build
.\.venv\Scripts\python.exe tools\dc.py ps -a
```

Первое скачивание и сборка займут время. `initialize` должен завершиться с кодом **0**; `db` и `web` — получить состояние **healthy**, `proxy` — работать. Если приложение долго не стартует:

```powershell
.\.venv\Scripts\python.exe tools\dc.py logs --tail 100 initialize web proxy
```

Для новой пустой установки создай администратора:

```powershell
.\.venv\Scripts\python.exe tools\dc.py exec web python backend/manage.py createsuperuser
```

Открой **http://localhost:8080/**. Проверь вход, новое название и создание черновика курса. Если планируешь перенести прежние аккаунты, сначала выполни шаг 11 вместо создания нового администратора.

`tools/dc.py` просто вызывает `docker compose` с `.env.deploy` и подходящими Compose-файлами. На сервере его можно вызывать системным `python3`; локальная `.venv` контейнерам не нужна. В локальном режиме публикация порта ограничена `127.0.0.1`, а режим HTTP и отключение обязательной MFA действуют только для локальной проверки.

**7. Включить AI и локальную проверку C++**

Для AI:

```powershell
.\.venv\Scripts\python.exe tools\deploy_env.py --ai on
.\.venv\Scripts\python.exe tools\dc.py up -d --build
.\.venv\Scripts\python.exe tools\dc.py exec ollama ollama pull qwen3:4b-instruct-2507-q4_K_M
.\.venv\Scripts\python.exe tools\dc.py run --rm --no-deps autoquiz python backend/manage.py autoquiz_prepare
.\.venv\Scripts\python.exe tools\dc.py run --rm --no-deps autoquiz python backend/manage.py autoquiz_check --probe
```

Модели скачиваются в Docker volumes. Уже скачанные на Windows модели автоматически туда не попадают. Пока модели не готовы, обработчик ждёт и не забирает видео из очереди. CPU-режим не требует NVIDIA/CUDA; время генерации зависит от процессора и длины лекции. Для одновременной работы платформы и AI разумно начать с 16 ГБ ОЗУ, 4 CPU и свободного места под модели, образы и видео; это ориентир, не проверенная предельная нагрузка.

Включить локальный C++:

```powershell
docker build -t ib-cpp-runner:m34 runner
.\.venv\Scripts\python.exe tools\deploy_env.py --cpp on
.\.venv\Scripts\python.exe tools\dc.py up -d --build
.\.venv\Scripts\python.exe tools\dc.py logs --tail 50 judge-local
```

Локальный обработчик получает Docker socket твоего Docker Desktop. Это административный доступ к этому Docker-движку: используй режим для собственных тестов, не для выдачи публичного доступа ученикам. Серверный вариант следующего шага работает с отдельной VM и не монтирует Docker socket сервера сайта.

Проверь через интерфейс: создай задание C++, опубликуй курс, зайди учеником, отправь верное и неверное решение. Затем загрузи короткую лекцию, дождись автотеста, проверь вопросы и добавь его в курс.

**8. Подготовить сервер**

Предлагаемая схема: VM №1 — сайт, PostgreSQL, сообщения, AI; VM №2 — только Docker для выполнения C++. Обе VM могут жить на одном физическом сервере. На VM проверки не должно быть базы платформы, её файлов, резервных копий или ключа доступа к Git. SSH к ней разрешается только с VM сайта и административного адреса; доступ из неё к внутренним ресурсам кафедры ограничивает администратор сети.

На VM сайта нужен SSH-доступ и доменное имя, например `learn.example.org`, которое выдаст кафедра. На VM проверки достаточно начать с 2 CPU и 4 ГБ памяти; проверка сейчас последовательная.

На чистой **Ubuntu 24.04** установи Docker Engine и Compose plugin. Если кафедра их уже установила, сразу проверь `docker version` и `docker compose version` и пропусти установку. Не запускай установку поверх работающих серверных контейнеров без согласования с их администратором.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git python3
sudo install -d -m 0755 /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod 0644 /etc/apt/keyrings/docker.asc
sudo python3 - <<'PY'
from pathlib import Path
import subprocess
release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
assert release['ID'].strip('"') == 'ubuntu', 'This block is for Ubuntu only'
codename = release['VERSION_CODENAME'].strip('"')
arch = subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip()
Path('/etc/apt/sources.list.d/docker.sources').write_text(
    f'Types: deb\nURIs: https://download.docker.com/linux/ubuntu\nSuites: {codename}\n'
    f'Components: stable\nArchitectures: {arch}\nSigned-By: /etc/apt/keyrings/docker.asc\n')
PY
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

Это установка через официальный подписанный репозиторий. Совместимость ОС и конфликтующие пакеты описаны в [инструкции Docker для Ubuntu](https://docs.docker.com/engine/install/ubuntu/).

Для работы текущего серверного пользователя с Docker без `sudo`:

```bash
sudo usermod -aG docker "$USER"
```

Выйди из SSH и зайди снова. Проверь `docker version`. Членство в группе `docker` даёт административные возможности на этой VM; ученикам серверные аккаунты и эту группу не выдаём.

**9. Дать серверу доступ к закрытому Git**

На VM сайта, под пользователем, который будет разворачивать проект:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/ib_school_git -C "ib-school-deploy"
cat ~/.ssh/ib_school_git.pub
```

При генерации ключа можно задать парольную фразу: тогда вводи её при `git clone` и `git pull`. Не перезаписывай уже существующий ключ, если `ssh-keygen` об этом спросит.

Скопируй **публичный** ключ с окончанием `.pub`. На GitHub открой репозиторий → **Settings → Deploy keys → Add deploy key**, название `Department server`, вставь ключ. Флажок **Allow write access** не ставь: серверу достаточно скачивать код. Такой ключ относится к одному репозиторию; [как устроены deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys).

На сервере:

```bash
export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/ib_school_git -o IdentitiesOnly=yes"
read -rp "SSH URL репозитория (git@github.com:ЛОГИН/ib-school.git): " ib_repo
git clone "$ib_repo" ~/ib-school
cd ~/ib-school
git config --local core.sshCommand "ssh -i $HOME/.ssh/ib_school_git -o IdentitiesOnly=yes"
unset GIT_SSH_COMMAND
```

При первом подключении сравни показанный SSH fingerprint с [официальными отпечатками GitHub](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints), затем подтверди доверие. Приватный ключ без `.pub` никому не отправляется и не попадает в проект.

**10. Запустить сайт на сервере**

Сначала выбери, нужна ли прежняя база. Для переноса существующих аккаунтов и курсов выполни экспорт из шага 11 **до создания нового администратора**. Для пустой новой платформы продолжай здесь.

У кафедры должен быть настроен DNS домена на сервер, а входящие TCP 80 и 443 должны доходить до него. Тогда Caddy сам получит HTTPS-сертификат:

```bash
cd ~/ib-school
read -rp "Домен платформы без https:// (например learn.example.org): " ib_domain
python3 tools/deploy_env.py --mode server --site "$ib_domain"
chmod 600 .env.deploy
python3 tools/dc.py config --quiet
python3 tools/dc.py up -d --build
python3 tools/dc.py ps -a
python3 tools/dc.py exec web python backend/manage.py createsuperuser
python3 tools/dc.py exec web python backend/manage.py check --deploy
```

Открой `https://ТВОЙ_ДОМЕН/`. В серверном режиме `DEBUG=0`, cookies передаются по HTTPS. Существующий механизм MFA для преподавателя/администратора в этом режиме действует; при первом входе настрой его и сохрани резервные коды. Твой обычный запуск на Windows этим не меняется.

Если у кафедры **уже есть HTTPS reverse proxy на этой же VM**, вместо обычной генерации настроек используй:

```bash
python3 tools/deploy_env.py --mode server --site "$ib_domain" --behind-proxy
```

В этом варианте внешний прокси должен принимать HTTPS для указанного домена, сохранять `Host`, разрешать загрузку не менее 520 МБ и пересылать запросы на `http://127.0.0.1:8080`. Он должен **перезаписывать `X-Real-IP` фактическим IP клиента**, чтобы ограничения попыток входа различали пользователей, и перенаправлять внешний HTTP на HTTPS. Встроенный Caddy доверяет именно этому локальному маршруту. Для прокси на другой VM требуется отдельно настроить адрес привязки и сетевые ограничения с администратором.

PostgreSQL, Ollama и Gunicorn не публикуют свои порты на хосте. Снаружи доступен только прокси; SSH нужен администратору. Материалы проходят через проверку доступа Django, видео сохраняет поддержку перемотки. Не добавляй публичную раздачу каталога `media` в конфигурацию внешнего прокси.

Миграции выполняет сервис `initialize`, затем запускается сайт. Используются проверки готовности БД и завершения инициализации — механизм [depends_on в Compose](https://docs.docker.com/compose/how-tos/startup-order/).

**11. Перенести текущие аккаунты, курсы и видео**

Git не переносит базу и загруженные материалы. Этот шаг нужен, если хочешь сохранить данные нынешней Windows-установки. Если начинаешь заполнение с нуля — пропусти его.

Останови на Windows все три процесса: сайт и оба обработчика. В корне проекта:

```powershell
.\.venv\Scripts\python.exe tools\export_existing.py
```

Программа напечатает папку вида `transfer\export_...`. В ней данные, материалы и ключи для сохранения доступа к MFA. Храни этот экспорт как резервную копию. Перенеси его по SSH на сервер:

```powershell
$ibExport = Read-Host "Полный путь к напечатанной папке export_..."
$ibServer = Read-Host "SSH-адрес сервера: пользователь@IP"
scp -r "$ibExport" "${ibServer}:~/ib-transfer"
```

Если `~/ib-transfer` раньше не существовала, файлы окажутся прямо внутри неё. Если существовала — проверь, не появилась ли внутри дополнительная папка `export_...`; далее нужен каталог, содержащий `data.json` и `manifest.json`.

На сервере, в корне **новой установки**, до запуска сайта:

```bash
python3 tools/deploy_env.py --mode server --site "$ib_domain" --import-keys "$HOME/ib-transfer/.env.keys"
python3 tools/dc.py build web
python3 tools/dc.py up -d db
python3 tools/dc.py run --rm initialize
chmod -R u+rwX,go-rwx ~/ib-transfer
sudo chown -R 10001:10001 ~/ib-transfer
python3 tools/dc.py run --rm --no-deps -v "$HOME/ib-transfer:/transfer:ro" web python tools/import_transfer.py /transfer
python3 tools/dc.py up -d
```

Для варианта с внешним прокси добавь `--behind-proxy` к первой команде. Если `.env.deploy` уже создан с правильным серверным режимом, можно использовать просто `python3 tools/deploy_env.py --import-keys "$HOME/ib-transfer/.env.keys"`.

Импорт проверяет контрольные суммы, совпадение ключей и отсутствие пользователей/курсов и файлов в целевой установке. При непустой базе он остановится. **Не очищай рабочую базу ради импорта.** Для неё нужен отдельный согласованный перенос.

После импорта войди прежним администратором; `createsuperuser` не нужен. Переносятся аккаунты с хешами паролей, курсы, материалы, прогресс, сообщения и настройки аккаунтов. Старые браузерные сеансы, временные ограничения запросов и записи о запущенных обработчиках не переносятся. Модели Whisper/Ollama скачиваются отдельно. Сохрани исходную Windows-установку до проверки данных на сервере.

**12. Включить генерацию тестов на сервере**

```bash
python3 tools/deploy_env.py --ai on
python3 tools/dc.py up -d --build
python3 tools/dc.py exec ollama ollama pull qwen3:4b-instruct-2507-q4_K_M
python3 tools/dc.py run --rm --no-deps autoquiz python backend/manage.py autoquiz_prepare
python3 tools/dc.py run --rm --no-deps autoquiz python backend/manage.py autoquiz_check --probe
python3 tools/dc.py logs --tail 100 autoquiz
```

После скачивания обработка выполняется локально. Облачный режим Ollama отключён. На этом этапе проверь реальную короткую лекцию через интерфейс: `--probe` проверяет загрузку моделей и ответ сервиса, но не качество конкретных вопросов. Преподаватель по-прежнему проверяет автотест перед публикацией.

**13. Подключить серверную проверку C++**

На **отдельной VM проверки** установи Docker по шагу 8. Создай отдельного системного пользователя:

```bash
sudo adduser judge
sudo usermod -aG docker judge
```

Теперь на **VM сайта**, в `~/ib-school`:

```bash
mkdir -p deploy/secrets/judge
chmod 700 deploy/secrets/judge
ssh-keygen -t ed25519 -f deploy/secrets/judge/id_ed25519 -C "ib-cpp-runner"
read -rp "IP отдельной VM проверки: " ib_runner_ip
ssh-copy-id -i deploy/secrets/judge/id_ed25519.pub "judge@$ib_runner_ip"
ssh -i deploy/secrets/judge/id_ed25519 -o UserKnownHostsFile=deploy/secrets/judge/known_hosts "judge@$ib_runner_ip" docker info
```

У этого отдельного ключа оставь passphrase пустой: фоновый процесс не сможет вводить её. Приватный ключ хранится только на VM сайта. Fingerprint VM проверки сверь с её консолью: `sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. Не отключай проверку host key.

Отправь на VM проверки только исходники runner и собери образ:

```bash
scp -i deploy/secrets/judge/id_ed25519 -o UserKnownHostsFile=deploy/secrets/judge/known_hosts -r runner "judge@$ib_runner_ip:~/ib-runner"
ssh -i deploy/secrets/judge/id_ed25519 -o UserKnownHostsFile=deploy/secrets/judge/known_hosts "judge@$ib_runner_ip" 'docker build -t ib-cpp-runner:m34 ~/ib-runner'
chmod 600 deploy/secrets/judge/id_ed25519
chmod 644 deploy/secrets/judge/id_ed25519.pub deploy/secrets/judge/known_hosts
sudo chown -R 10001:10001 deploy/secrets/judge
python3 tools/deploy_env.py --cpp on --runner "ssh://judge@$ib_runner_ip"
python3 tools/dc.py build judge
python3 tools/dc.py run --rm --no-deps judge docker info
python3 tools/dc.py up -d
python3 tools/dc.py logs --tail 100 judge
```

Ключи доступны контейнеру обработчика с UID 10001. Сам сайт их не получает. `DOCKER_HOST` направляет Docker CLI через SSH на VM проверки; доступ через SSH описан в [документации Docker](https://docs.docker.com/engine/security/protect-access/).

Код ученика запускается существующим runner без сети, без host mounts, с ограничением памяти, CPU, процессов и времени. Доступ обработчика к Docker является административным доступом **на VM проверки**. Отдельная VM ограничивает последствия ошибки в песочнице, но не является гарантией отсутствия уязвимостей. Перед выдачей доступа ученикам кафедре следует проверить ограничения на своей конфигурации. На сервере сайта не включай `cpp-local`.

**14. Проверить готовую установку**

```bash
python3 tools/dc.py ps -a
python3 tools/dc.py exec web python backend/manage.py check --deploy
python3 tools/dc.py exec web python backend/manage.py showmigrations
python3 tools/dc.py logs --tail 100 web
```

Через сайт проверь последовательно:

1. Вход администратором и создание приглашения для ученика.
2. Черновик курса: статья, видео, тест, практическое C++-задание.
3. Публикация: ученик видит курс и может записаться.
4. Верный ответ начисляет балл один раз; рейтинг и прогресс сохраняются после повторного входа.
5. Неверное решение C++ отклоняется, верное принимается; бесконечный цикл останавливается по времени.
6. Внутренний чат, вложения, разграничение доступа преподавателя и ученика.
7. Генерация вопросов из короткой лекции и ручное подтверждение преподавателем.
8. Видео перематывается; закрытые материалы не открываются без необходимого входа и доступа.

Настройки HTTPS, host names, секретов и закрытой раздачи материалов следуют подходу [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/). Проверка настроек не заменяет проверку реальных пользовательских сценариев.

**15. Где теперь находятся данные**

| Данные | Хранилище |
|---|---|
| Код и миграции | Приватный GitHub + checkout на сервере |
| Пользователи, курсы, прогресс, сообщения | Docker volume PostgreSQL |
| Загруженные видео и документы | Docker volume `media` |
| Модели Qwen и Whisper | Отдельные volumes `ollama_models`, `whisper_models` |
| Сертификаты Caddy | Volume `caddy_data` |
| Пароли БД, ключи приложения | `.env.deploy` на сервере |
| Ключ к VM проверки | `deploy/secrets/judge`, только на сервере |

Пересборка образов и обычный `down` эти volumes не удаляют. **Не выполняй `docker compose down -v`, `docker volume prune` и сброс Docker Desktop**, если там нужные данные. Git сам по себе не является резервной копией базы.

**16. Резервная копия перед обновлением**

На сервере:

```bash
python3 tools/backup_compose.py
```

Скрипт ненадолго останавливает сайт и фоновые обработчики, создаёт согласованную копию PostgreSQL, материалов и `.env.deploy`, затем запускает ранее работавшие сервисы. Путь — `backups/docker_...`. Копирование больших видео может занять время. Модели AI не архивируются: их можно скачать повторно.

Скопируй архивную папку на отдельный защищённый диск/хост. Внутри персональные данные и ключи, поэтому она исключена из Git. После аварийного отключения питания дополнительно проверь наличие `manifest.json`: незавершённую копию нельзя считать готовой.

Восстановление выполняй в **отдельную пустую установку** на новом сервере или в новом Docker-проекте; работающий сервер сохраняется до проверки восстановления. Клонируй тот коммит, которому соответствует копия, создай `.env.deploy` для нового адреса и импортируй ключи из копии:

```bash
python3 tools/deploy_env.py --mode server --site "$ib_domain" --import-keys /ПУТЬ/К/КОПИИ/.env.deploy
python3 tools/dc.py build web
python3 tools/dc.py up -d db
python3 tools/dc.py run --rm initialize
python3 tools/restore_backup.py /ПУТЬ/К/КОПИИ
python3 tools/dc.py up -d
```

Здесь `/ПУТЬ/К/КОПИИ` — настоящая папка `backups/docker_...`, перенесённая на новый сервер. Скрипт проверит контрольные суммы и пустую целевую установку. Если восстановление материалов прервалось, оставь новую установку выключенной: проверь исходную копию и повтори восстановление в другую пустую установку. На рабочую базу этот сценарий не рассчитан.

**17. Как выпускать изменения**

На Windows, после проверки работы и просмотра изменений:

```powershell
git add .
.\.venv\Scripts\python.exe tools\git_check.py
git diff --cached --stat
git commit -m "Describe the actual change"
git push
```

На сервере:

```bash
cd ~/ib-school
python3 tools/backup_compose.py
git status --short
git rev-parse HEAD
git pull --ff-only
python3 tools/dc.py build
python3 tools/dc.py stop
python3 tools/dc.py run --rm initialize
python3 tools/dc.py up -d
python3 tools/dc.py ps -a
```

Сохрани прежний хеш коммита рядом с резервной копией. Если `git pull` или инициализация завершились ошибкой, остановись на этой команде и посмотри сообщение: не выполняй следующие строки вслепую. При ошибке миграции базу не удаляй. Для отката кода после изменения схемы может понадобиться восстановление соответствующей копии БД, а не только возврат Git-коммита.

Обновление `runner/` нужно также отправить и пересобрать на VM проверки командами из шага 13. После `chown 10001` ключ читается через `sudo` или пользователем с соответствующими правами; не расширяй доступ к приватному ключу до общего чтения.

**18. Остановка, запуск и частые ошибки**

| Действие | Команда на сервере |
|---|---|
| Посмотреть сервисы | `python3 tools/dc.py ps -a` |
| Смотреть журнал сайта | `python3 tools/dc.py logs -f web` |
| Смотреть AI | `python3 tools/dc.py logs -f autoquiz` |
| Смотреть C++ | `python3 tools/dc.py logs -f judge` |
| Остановить без удаления | `python3 tools/dc.py stop` |
| Запустить снова | `python3 tools/dc.py up -d` |
| Проверить Compose без вывода секретов | `python3 tools/dc.py config --quiet` |

Ctrl+C при просмотре `logs -f` прекращает просмотр, а не работу контейнеров.

- `DisallowedHost`: домен должен совпадать с настройками `--site`. Меняй его через `deploy_env.py`, затем `tools/dc.py up -d`.
- CSRF 403: используй точный HTTPS-домен, проверь внешний прокси и `Host`. Заходить по IP вместо настроенного домена не нужно.
- HTTPS не выпущен: проверь DNS и доступность TCP 80/443 снаружи; при внешнем прокси используй соответствующий режим.
- `initialize` завершился ошибкой: `tools/dc.py logs initialize`; проверь миграции, ничего не удаляй и не применяй `--fake` наугад.
- C++ offline: проверь журнал `judge`, SSH к VM и наличие `ib-cpp-runner:m34` именно на ней. После перезапуска обработчик может восстанавливаться до минуты.
- AI ждёт модели: выполни обе команды скачивания из шага 12. Модели Windows и Docker лежат в разных хранилищах.
- После клонирования нет старых курсов: это ожидаемо без шага 11 — Git передаёт код, данные переносятся отдельно.

Архив подготавливает проект к развёртыванию. Настройка домена, серверных VM, сетевых правил и проверка на конкретном сервере выполняются вместе с кафедрой. Результаты выполненных проверок этого обновления находятся в `VALIDATION_RU.md`.
