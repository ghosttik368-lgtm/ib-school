"""Optional regression check on a separate temporary SQLite database.

Run from project root: .venv/Scripts/python.exe tools/check_m25_concurrency.py
Never reads or changes the project's student database.
"""
import os
import sys
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def main():
    from django.conf import settings
    with tempfile.TemporaryDirectory(prefix='ib-m25-check-') as temp:
        settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(Path(temp) / 'test.sqlite3'), 'OPTIONS': {'timeout': 20}}}
        import django
        django.setup()
        from django.core.management import call_command
        from django.db import connections, close_old_connections
        from django.utils import timezone
        from accounts.models import User
        from courses.models import Course, Direction, Module, Lesson, Material, Enrollment
        from learning.models import BlockProgress
        from learning.services import open_block, complete_information
        try:
            call_command('migrate', verbosity=0)
            user = User.objects.create(username='concurrency-check')
            direction = Direction.objects.create(name='Check')
            course = Course.objects.create(title='Check', direction=direction, status='published')
            lesson = Lesson.objects.create(title='Check', module=Module.objects.create(course=course, title='Check'))
            material = Material.objects.create(lesson=lesson, title='Check', kind='text', text='Check')
            Enrollment.objects.create(user=user, course=course)
            def run(kind):
                barrier = Barrier(4)
                def worker(_):
                    close_old_connections()
                    try:
                        student = User.objects.get(pk=user.pk)
                        block = Material.objects.select_related('lesson__module__course').get(pk=material.pk)
                        barrier.wait(timeout=15)
                        if kind == 'open':
                            return open_block(student, block).opened_at
                        return complete_information(student, block, timezone.now())
                    finally:
                        connections.close_all()
                with ThreadPoolExecutor(max_workers=4) as pool:
                    return list(pool.map(worker, range(4)))
            opened = run('open')
            assert len(set(opened)) == 1, 'Opening timestamps differ'
            completed = run('complete')
            assert sum(completed) == 1, 'Completion was rewarded more than once'
            progress = BlockProgress.objects.get(user=user, material=material)
            assert progress.completed_at and progress.attempts == 1
            assert BlockProgress.objects.filter(user=user, completed_at__isnull=False).count() == 1
            assert Enrollment.objects.get(user=user, course=course).progress_percent == 100
            print('OK: 4 simultaneous opens + 4 completions; one timestamp, one point.')
        finally:
            connections.close_all()


if __name__ == '__main__':
    main()
