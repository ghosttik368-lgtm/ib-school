from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Однократно скачать Whisper в папку проекта. Интернет нужен только при скачивании.'

    def handle(self, *args, **options):
        if settings.AUTOQUIZ_WHISPER not in {'tiny', 'base', 'small', 'medium', 'large-v3', 'turbo'}:
            raise CommandError('AUTOQUIZ_WHISPER: выберите tiny, base, small, medium, large-v3 или turbo.')
        try:
            from faster_whisper.utils import download_model
        except ImportError as exc:
            raise CommandError('Установите requirements-autoquiz.txt.') from exc
        target = settings.AUTOQUIZ_MODEL_DIR / settings.AUTOQUIZ_WHISPER
        target.mkdir(parents=True, exist_ok=True)
        (settings.AUTOQUIZ_MODEL_DIR / '.gitignore').write_text('*\n', encoding='utf-8')
        self.stdout.write(f'Скачиваем Whisper {settings.AUTOQUIZ_WHISPER}. Не закрывайте терминал.')
        try:
            download_model(settings.AUTOQUIZ_WHISPER, output_dir=str(target))
        except Exception as exc:
            raise CommandError('Не удалось скачать модель с Hugging Face. Проверьте сеть и место; повторный запуск продолжит загрузку.') from exc
        self.stdout.write(self.style.SUCCESS('Whisper готов. Следующий шаг: autoquiz_check --probe.'))
