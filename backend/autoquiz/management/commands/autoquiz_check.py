import importlib
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from autoquiz import ollama
from autoquiz.models import WorkerLease


class Command(BaseCommand):
    help = 'Проверить зависимости, Whisper, Ollama и очередь без загрузки лекции.'

    def add_arguments(self, parser):
        parser.add_argument('--probe', action='store_true', help='Проверить загрузку Whisper и реальный JSON-ответ Ollama')

    def handle(self, *args, **options):
        for package in ['faster_whisper', 'ctranslate2', 'av', 'onnxruntime']:
            try:
                importlib.import_module(package)
            except (ImportError, OSError) as exc:
                raise CommandError(f'{package}: не загружается. Установите requirements-autoquiz.txt и Visual C++ Redistributable x64.') from exc
        self.stdout.write('Зависимости распознавания: OK')
        folder = settings.AUTOQUIZ_MODEL_DIR / settings.AUTOQUIZ_WHISPER
        if not (folder / 'model.bin').exists():
            raise CommandError('Whisper не скачан. Выполните autoquiz_prepare.')
        try:
            names = {m['name'] for m in ollama.request('/api/tags', timeout=10).get('models', [])}
            if settings.AUTOQUIZ_MODEL not in names:
                raise CommandError(f'Нет модели {settings.AUTOQUIZ_MODEL}. Выполните: ollama pull {settings.AUTOQUIZ_MODEL}')
            self.stdout.write('Ollama и модель Qwen: OK')
            if options['probe']:
                ollama.unload(settings.AUTOQUIZ_MODEL)
                self.stdout.write('Загружаем Whisper для проверки…')
                from faster_whisper import WhisperModel
                model = WhisperModel(str(folder), device='cpu', compute_type='int8', cpu_threads=settings.AUTOQUIZ_THREADS, local_files_only=True)
                del model
                import gc
                gc.collect()
                self.stdout.write('Whisper загружается. Проверяем ответ Qwen…')
                result = ollama.chat(settings.AUTOQUIZ_MODEL,
                    [{'role': 'user', 'content': 'Верни JSON с единственным полем status и значением ok.'}],
                    {'type': 'object', 'required': ['status'], 'properties': {'status': {'type': 'string', 'enum': ['ok']}}, 'additionalProperties': False})
                if result != {'status': 'ok'}:
                    raise CommandError('Модель не вернула ожидаемый JSON.')
                self.stdout.write('Реальный ответ Qwen: OK')
        except ollama.ModelError as exc:
            raise CommandError(str(exc)) from exc
        available = WorkerLease.objects.filter(name='autoquiz', expires_at__gt=timezone.now()).exists()
        self.stdout.write('Очередь: ' + ('обработчик запущен' if available else 'запустите autoquiz_worker в отдельном терминале'))
        self.stdout.write(self.style.SUCCESS('Проверка завершена. Качество вопросов проверяется на вашей лекции.'))
