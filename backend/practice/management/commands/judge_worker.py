import logging
import time
import uuid
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, DatabaseError
from practice.engine import check_docker, RunnerError
from practice.models import Worker
from practice.services import process_one

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Устойчивая очередь проверки C++ с восстановлением соединений.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        name = uuid.uuid4().hex
        ready = False
        self.stdout.write('Обработчик C++ запущен. Остановка: Ctrl+C.')
        try:
            while True:
                try:
                    close_old_connections()
                    if not ready:
                        check_docker()
                        ready = True
                    processed = process_one(name)
                    if options['once']:
                        break
                    if not processed:
                        time.sleep(1)
                except (RunnerError, DatabaseError) as exc:
                    ready = False
                    close_old_connections()
                    if options['once']:
                        raise CommandError(str(exc)) from exc
                    log.warning('Judge connection interrupted; retry in 5 seconds: %s', exc)
                    time.sleep(5)
        except KeyboardInterrupt:
            self.stdout.write('Обработчик остановлен.')
        finally:
            try:
                Worker.objects.filter(name=name).delete()
            except DatabaseError:
                close_old_connections()
