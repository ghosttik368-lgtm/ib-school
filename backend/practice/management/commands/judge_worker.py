import time
import uuid
from django.core.management.base import BaseCommand, CommandError
from practice.engine import check_docker, RunnerError
from practice.models import Worker
from practice.services import process_one


class Command(BaseCommand):
    help = 'Обработчик очереди C++ через Docker. Оставьте терминал открытым.'
    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
    def handle(self, *args, **options):
        try: check_docker()
        except RunnerError as exc: raise CommandError(str(exc))
        name = uuid.uuid4().hex
        self.stdout.write('Обработчик C++ запущен. Остановка: Ctrl+C.')
        try:
            while True:
                processed = process_one(name)
                if options['once']: break
                if not processed: time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write('Обработчик остановлен.')
        finally:
            Worker.objects.filter(name=name).delete()
