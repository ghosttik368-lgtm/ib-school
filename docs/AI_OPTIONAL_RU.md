# AI — дополнительная опция

Для основной платформы и C++:

    docker compose up -d --build

Для всей платформы вместе с Ollama, Qwen и Whisper:

    docker compose -f compose.yaml -f compose.ai.yaml up -d --build

Модели скачиваются автоматически контейнером ai-prepare и сохраняются в томах. GPU не обязателен; на CPU обработка может быть медленной. Сайт и C++ запускаются независимо от загрузки моделей. Проверка после подготовки:

    docker compose -f compose.yaml -f compose.ai.yaml exec autoquiz python backend/manage.py autoquiz_check --probe

Отключить AI, сохранив модели:

    docker compose -f compose.yaml -f compose.ai.yaml stop autoquiz ai-prepare ollama
    docker compose up -d --build --remove-orphans

При обычном запуске нет обращения к моделям; видео воспроизводятся и тесты создаются вручную. Готовые тесты сохраняются.
