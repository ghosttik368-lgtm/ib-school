"""M5/M6 -> autoquiz, in a disposable DB. Never opens the working database."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def main():
    from django.conf import settings
    with tempfile.TemporaryDirectory(prefix='ib-autoquiz-upgrade-') as folder:
        settings.DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(Path(folder)/'check.sqlite3'), 'OPTIONS': {'timeout': 20}}}
        settings.MEDIA_ROOT = Path(folder)/'media'
        import django
        django.setup()
        from django.db import connection, connections
        from django.db.migrations.executor import MigrationExecutor
        from django.utils import timezone
        try:
            executor = MigrationExecutor(connection)
            leaves = executor.loader.graph.leaf_nodes()
            old_targets = [n for n in leaves if n[0] != 'autoquiz']
            executor.migrate(old_targets)
            old = executor.loader.project_state(old_targets).apps
            User = old.get_model('accounts', 'User')
            teacher = User.objects.create(username='teacher', role='teacher')
            student = User.objects.create(username='student', role='student')
            direction = old.get_model('courses', 'Direction').objects.create(name='Programming', slug='programming')
            course = old.get_model('courses', 'Course').objects.create(title='Existing course', slug='existing', status='published', created_by=teacher, direction=direction)
            module = old.get_model('courses', 'Module').objects.create(course=course, title='Module')
            lesson = old.get_model('courses', 'Lesson').objects.create(module=module, title='Lesson')
            material = old.get_model('courses', 'Material').objects.create(lesson=lesson, title='Article', kind='text')
            old.get_model('courses', 'Enrollment').objects.create(user=student, course=course, progress_percent=100)
            progress = old.get_model('learning', 'BlockProgress').objects.create(user=student, material=material, completed_at=timezone.now(), verdict='positive', elapsed_ms=40000)
            old.get_model('learning', 'BlockReview').objects.create(progress=progress, reviewer=teacher, verdict='positive', note='Reviewed before update')
            snapshot = {name: old.get_model(*name.split('.')).objects.count() for name in ['accounts.User', 'courses.Course', 'courses.Material', 'courses.Enrollment', 'learning.BlockProgress', 'learning.BlockReview', 'messenger.Room', 'teaching.StudyGroup']}
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
            from django.apps import apps
            for name, count in snapshot.items():
                assert apps.get_model(name).objects.count() == count, name
            assert apps.get_model('courses.Enrollment').objects.get(user_id=student.pk).progress_percent == 100
            assert apps.get_model('learning.BlockProgress').objects.get(pk=progress.pk).elapsed_ms == 40000
            assert apps.get_model('autoquiz.Generation').objects.count() == 0
            print('OK: autoquiz migration preserves users, courses, progress, reviews, chat and groups.')
        finally:
            connections.close_all()


if __name__ == '__main__':
    main()
