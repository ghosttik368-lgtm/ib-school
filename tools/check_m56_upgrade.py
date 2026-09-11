"""Verify M3/M4 -> M5/M6 on a separate disposable SQLite database."""
import os
import sys
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')


def main():
    from django.conf import settings
    with tempfile.TemporaryDirectory(prefix='ib-m56-check-') as temp:
        settings.DATABASES = {'default':{'ENGINE':'django.db.backends.sqlite3','NAME':str(Path(temp)/'check.sqlite3'),'OPTIONS':{'timeout':20}}}
        settings.MEDIA_ROOT = Path(temp)/'media'
        import django
        django.setup()
        from django.db import connection, connections, close_old_connections
        from django.db.migrations.executor import MigrationExecutor
        from django.utils import timezone
        try:
            executor = MigrationExecutor(connection)
            leaves = executor.loader.graph.leaf_nodes()
            old_targets = [n for n in leaves if n[0] not in ('messenger','teaching')]
            executor.migrate(old_targets)
            old = executor.loader.project_state(old_targets).apps
            User=old.get_model('accounts','User');Course=old.get_model('courses','Course');Direction=old.get_model('courses','Direction')
            teacher=User.objects.create(username='teacher',role='teacher');a=User.objects.create(username='a',role='student');b=User.objects.create(username='b',role='student')
            course=Course.objects.create(title='Existing course',slug='existing',status='published',created_by_id=teacher.pk,direction=Direction.objects.create(name='Coding',slug='coding'))
            module=old.get_model('courses','Module').objects.create(course=course,title='Module')
            lesson=old.get_model('courses','Lesson').objects.create(module=module,title='Lesson')
            material=old.get_model('courses','Material').objects.create(lesson=lesson,title='Existing block',kind='text')
            e=old.get_model('courses','Enrollment').objects.create(user=a,course=course,progress_percent=100)
            p=old.get_model('learning','BlockProgress').objects.create(user=a,material=material,completed_at=timezone.now(),verdict='negative',elapsed_ms=1000)
            old.get_model('learning','BlockReview').objects.create(progress=p,reviewer=teacher,verdict='positive',note='Verified before update')
            chat=old.get_model('courses','ChatMessage').objects.create(user=a,text='Message before update')
            executor=MigrationExecutor(connection);executor.migrate(executor.loader.graph.leaf_nodes())
            from accounts.models import User
            from courses.models import Enrollment
            from learning.models import BlockProgress
            from teaching.models import ReviewEvent
            from messenger.models import Message, Room
            from messenger.services import create_room, send
            assert Enrollment.objects.get(pk=e.pk).progress_percent==100
            assert BlockProgress.objects.get(pk=p.pk).effective_verdict=='positive'
            assert ReviewEvent.objects.get(progress_id=p.pk).note=='Verified before update'
            assert Message.objects.get(legacy_id=chat.pk).created_at==chat.created_at
            a=User.objects.get(pk=a.pk);b=User.objects.get(pk=b.pk)
            room=create_room(a,'direct','',[b.pk]);key=uuid.uuid4();barrier=Barrier(4)
            def worker(i):
                close_old_connections()
                try:
                    person=User.objects.get(pk=a.pk if i<2 else b.pk)
                    barrier.wait(timeout=15)
                    return send(person,room.pk,'duplicate' if i<2 else f'other-{i}',key if i<2 else uuid.uuid4()).pk
                finally:
                    connections.close_all()
            with ThreadPoolExecutor(max_workers=4) as pool:
                result=list(pool.map(worker,range(4)))
            assert result[0]==result[1]
            assert Message.objects.filter(room=room).count()==3
            assert Room.objects.get(pk=room.pk).version==3
            print('OK: M3/M4 data preserved; chat and reviews imported; concurrent messages saved once.')
        finally:
            connections.close_all()


if __name__=='__main__':
    main()
