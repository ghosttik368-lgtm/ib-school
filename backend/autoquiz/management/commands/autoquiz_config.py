from pathlib import Path
import os
import re
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Настроить скорость локального AI, сохранив остальные значения .env.'

    def add_arguments(self, parser):
        parser.add_argument('--whisper', choices=['small', 'medium'], default=None)
        parser.add_argument('--threads', type=int, choices=range(1, 9), default=None)
        parser.add_argument('--timeout', type=int, choices=range(60, 1801), default=None)

    def handle(self, *args, **options):
        target = settings.PROJECT_ROOT / '.env'
        value = target.read_text(encoding='utf-8-sig')
        changed = False
        for option, key in [('whisper', 'AUTOQUIZ_WHISPER'), ('threads', 'AUTOQUIZ_THREADS'), ('timeout', 'AUTOQUIZ_TIMEOUT')]:
            if options[option] is None:
                continue
            replacement = f'{key}={options[option]}'
            pattern = re.compile(r'^\s*' + key + r'\s*=.*$', re.MULTILINE)
            value = pattern.sub(replacement, value) if pattern.search(value) else value.rstrip()+'\n'+replacement+'\n'
            changed = True
        if changed:
            temp = target.with_suffix('.env.autoquiz.tmp')
            temp.write_text(value, encoding='utf-8')
            os.replace(temp, target)
            self.stdout.write('Настройки сохранены. Перезапустите runserver и autoquiz_worker. При смене Whisper выполните autoquiz_prepare; новые параметры применятся к новым задачам.')
        else:
            self.stdout.write(f'Whisper: {settings.AUTOQUIZ_WHISPER}; потоков CPU: {settings.AUTOQUIZ_THREADS}; ожидание Qwen: {settings.AUTOQUIZ_TIMEOUT} сек.')
