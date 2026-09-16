import time
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from autoquiz.worker import Heartbeat, acquire, claim, process


class Command(BaseCommand):
    help = 'Локальная очередь распознавания и генерации тестов. Остановка: Ctrl+C.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Обработать одно видео и завершиться')

    def handle(self, *args, **options):
        if not settings.AUTOQUIZ_ENABLED:
            raise CommandError('AI отключён: AUTOQUIZ_ENABLED=0. Очередь не обрабатывается.')
        token = acquire()
        if not token:
            raise CommandError('Обработчик уже запущен. Если он аварийно закрыт, подождите минуту.')
        self.stdout.write('Обработчик тестов запущен. Загрузите видео в редакторе. Остановка: Ctrl+C.')
        with Heartbeat(token) as heartbeat:
            try:
                while not heartbeat.lost:
                    job = claim(token)
                    if job:
                        self.stdout.write(f'Видео {job.asset_id}: обработка {job.pk}')
                        process(job, token, alive=lambda: not heartbeat.lost)
                        job.refresh_from_db()
                        self.stdout.write(f'{job.get_state_display()}: {job.error or job.phase}')
                    if options['once']:
                        break
                    if not job:
                        time.sleep(2)
            except KeyboardInterrupt:
                self.stdout.write('Обработчик остановлен. Незавершённую задачу можно повторить после запуска.')
