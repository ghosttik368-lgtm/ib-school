import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
from django.db.models import F, Q
from django.utils import timezone
from .models import Generation, WorkerLease
from .services import ACTIVE, video_in
from .validation import segments_checked
from .generator import generate
from .ollama import ModelError, unload

log = logging.getLogger(__name__)


class LostJob(Exception):
    pass


@transaction.atomic
def acquire():
    token = uuid.uuid4()
    now = timezone.now()
    WorkerLease.objects.get_or_create(name='autoquiz')
    changed = WorkerLease.objects.filter(name='autoquiz').filter(Q(expires_at__lte=now) | Q(expires_at__isnull=True)).update(
        token=token, expires_at=now+timedelta(seconds=60))
    if not changed:
        return None
    Generation.objects.filter(state__in=['transcribing', 'generating']).update(state='failed', token=None,
        error='Предыдущий обработчик был прерван. Нажмите «Повторить».', revision=F('revision')+1, updated_at=now)
    return token


class Heartbeat:
    def __init__(self, token):
        self.token, self.stop = token, threading.Event()
        self.lost = False
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        while not self.stop.wait(10):
            try:
                close_old_connections()
                if not WorkerLease.objects.filter(name='autoquiz', token=self.token).update(expires_at=timezone.now()+timedelta(seconds=60)):
                    self.lost = True
                    return
            except Exception:
                self.lost = True
                return
            finally:
                close_old_connections()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=3)
        WorkerLease.objects.filter(name='autoquiz', token=self.token).update(expires_at=timezone.now())


def claim(token):
    job = Generation.objects.filter(state='queued').order_by('created_at').first()
    if not job:
        return None
    if Generation.objects.filter(pk=job.pk, state='queued').update(state='transcribing', token=token,
            error='', phase='Подготавливаем видео', revision=F('revision')+1, updated_at=timezone.now()):
        job.refresh_from_db()
        return job


def recognition(job, report):
    model_dir = settings.AUTOQUIZ_MODEL_DIR / job.whisper_model
    if not (model_dir / 'model.bin').is_file():
        raise ModelError('Модель Whisper не скачана. Выполните python backend/manage.py autoquiz_prepare.')
    # The previous LLM is unloaded before recognition to fit a 16 GB machine.
    unload(job.model)
    with tempfile.TemporaryDirectory(prefix='ib-autoquiz-') as folder:
        output = Path(folder)/'transcript.json'
        command = [sys.executable, str(Path(__file__).with_name('asr_process.py')),
            '--video', job.asset.file.path, '--model', str(model_dir), '--output', str(output),
            '--threads', str(settings.AUTOQUIZ_THREADS)]
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started = time.monotonic()
        try:
            while child.poll() is None:
                report('Распознаём речь · это может занять дольше самого видео')
                if time.monotonic()-started > 12*3600:
                    raise ModelError('Распознавание не завершилось за 12 часов. Разделите видео или выберите Whisper small.')
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            if not output.exists() or output.stat().st_size > 4*1024*1024:
                raise ModelError('Обработчик речи завершился без результата. Проверьте память и autoquiz_check.')
            value = json.loads(output.read_text(encoding='utf-8'))
            if value.get('error'):
                raise ModelError(value['error'])
            return segments_checked(value.get('segments'))
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)


def process(job, token, alive=lambda: True):
    def report(phase, **extra):
        if not alive():
            raise LostJob()
        # Replacing a file/closing the draft/cancelling invalidates running work.
        job.draft.refresh_from_db(fields=['data', 'archived'])
        try:
            video_in(job.draft, job.video_key, job.asset_id)
        except ValidationError:
            Generation.objects.filter(pk=job.pk, token=token).update(state='stale', token=None, revision=F('revision')+1)
            raise LostJob()
        changed = Generation.objects.filter(pk=job.pk, token=token, state__in=ACTIVE).update(
            phase=phase, updated_at=timezone.now(), **extra)
        if not changed:
            raise LostJob()
    try:
        report('Подготавливаем расшифровку')
        segments = segments_checked(job.segments) if job.segments else recognition(job, report)
        report('Речь распознана. Составляем тест', segments=segments, state='generating')
        result = generate(segments, job.model, report, old=job.questions, replace_index=job.replace_index)
        report('10 вопросов готовы к проверке', state='ready', questions=result,
               replace_index=None, reviewed_revision=0, revision=F('revision')+1, token=None)
    except LostJob:
        return
    except (ValidationError, ModelError) as exc:
        message = '; '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
        Generation.objects.filter(pk=job.pk, token=token, state__in=ACTIVE).update(state='failed', token=None,
            error=message[:1500], revision=F('revision')+1, updated_at=timezone.now())
    except Exception:
        log.exception('autoquiz job %s failed', job.pk)
        Generation.objects.filter(pk=job.pk, token=token, state__in=ACTIVE).update(state='failed', token=None,
            error='Ошибка обработки. Подробности в терминале autoquiz_worker. Расшифровка и старые вопросы сохранены.',
            revision=F('revision')+1, updated_at=timezone.now())
