import uuid
from datetime import timedelta
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from learning.models import BlockProgress
from learning.services import authorize, lock_user, finish
from .models import Submission, Worker
from .engine import judge, RunnerError, Cancelled

ACTIVE = ['queued', 'running']
FINAL = ['accepted','wrong_answer','compile_error','runtime_error','time_limit','output_limit','run_ok','error','cancelled']


def worker_available():
    return Worker.objects.filter(heartbeat__gte=timezone.now()-timedelta(seconds=30)).exists()


@transaction.atomic
def enqueue(user, task, code, stdin, mode, key):
    lock_user(user)
    authorize(user, task.material, practice=True)
    progress = BlockProgress.objects.filter(user=user, material=task.material, opened_at__isnull=False).first()
    if not progress: raise ValidationError('Сначала откройте задание.')
    if mode not in ['run', 'check'] or not isinstance(code, str) or not code.strip() or len(code.encode('utf-8'))>100000:
        raise ValidationError('Нужен код C++ размером до 100 КБ.')
    if not isinstance(stdin, str) or len(stdin.encode('utf-8'))>10000:
        raise ValidationError('Ввод должен быть не больше 10 КБ.')
    try: key = uuid.UUID(str(key))
    except ValueError: raise ValidationError('Неверный идентификатор отправки.')
    old = Submission.objects.filter(user=user, request_key=key).first()
    if old:
        if old.task_id != task.pk or old.code != code or old.mode != mode or old.stdin != stdin:
            raise ValidationError('Этот идентификатор уже относится к другой отправке.')
        return old
    if not worker_available(): raise ValidationError('Проверка выключена. Преподавателю нужно запустить judge_worker.')
    if Submission.objects.filter(user=user, status__in=ACTIVE).exists(): raise ValidationError('Дождитесь текущей отправки или отмените её.')
    if Submission.objects.filter(status__in=ACTIVE).count() >= 100: raise ValidationError('Очередь заполнена. Попробуйте позже.')
    if Submission.objects.filter(user=user, submitted_at__gte=timezone.now()-timedelta(minutes=1)).count()>=10:
        raise ValidationError('Не больше 10 запусков в минуту. Подождите немного.')
    return Submission.objects.create(user=user, task=task, mode=mode, code=code, stdin=stdin, request_key=key,
                                     total_tests=len(task.tests) if mode=='check' else 0)


def claim():
    now = timezone.now()
    Submission.objects.filter(status='running', lease_until__lt=now).update(status='error', diagnostic='Обработчик был прерван. Отправьте решение снова.', finished_at=now)
    candidate = Submission.objects.filter(status='queued').select_related('task').order_by('submitted_at','id').first()
    if not candidate: return None
    token = uuid.uuid4()
    duration = 90 + max(1, len(candidate.task.tests)) * (candidate.task.time_limit + 20)
    changed = Submission.objects.filter(pk=candidate.pk, status='queued').update(status='running', claim_token=token, started_at=now, lease_until=now+timedelta(seconds=duration))
    if not changed: return None
    candidate.status = 'running'; candidate.claim_token = token
    return candidate


@transaction.atomic
def commit_result(job, result):
    lock_user(job.user)
    locked = Submission.objects.select_for_update().get(pk=job.pk)
    if locked.status != 'running' or locked.claim_token != job.claim_token: return
    status = result.get('status', 'error')
    if status not in FINAL: status = 'error'
    if locked.mode == 'run' and status == 'accepted': status = 'error'
    if status == 'accepted' and (not locked.total_tests or result.get('passed_tests') != locked.total_tests):
        status = 'error'
        result = {'diagnostic':'Неполный результат проверки.'}
    try:
        authorize(job.user, job.task.material, practice=True)
    except (PermissionDenied, ValidationError):
        status='cancelled'
        result={'diagnostic':'Доступ к заданию изменился; результат не засчитан.'}
    locked.status = status
    locked.stdout = result.get('stdout','')[:65536] if locked.mode=='run' else ''
    locked.diagnostic = str(result.get('diagnostic',''))[:65536]
    locked.passed_tests = min(int(result.get('passed_tests',0)), locked.total_tests)
    locked.finished_at = timezone.now()
    locked.save()
    if locked.mode == 'check' and status not in ['error','cancelled']:
        progress = BlockProgress.objects.get(user=job.user, material=job.task.material)
        if not progress.completed_at:
            progress.attempts += 1
            progress.save(update_fields=['attempts'])
            if status == 'accepted':
                authorize(job.user, job.task.material, practice=True)
                finish(job.user, job.task.material, progress, locked.submitted_at, locked.code)


def process_one(worker_name):
    Worker.objects.update_or_create(name=worker_name, defaults={'heartbeat':timezone.now()})
    job = claim()
    if not job: return False
    last_beat = [timezone.now()]
    def cancelled():
        now = timezone.now()
        if (now-last_beat[0]).total_seconds() >= 5:
            Worker.objects.filter(name=worker_name).update(heartbeat=now)
            last_beat[0] = now
        return not Submission.objects.filter(pk=job.pk, status='running', claim_token=job.claim_token).exists()
    try:
        result = judge(job.code, job.task.tests, job.task.time_limit, job.task.memory_limit, cancelled,
                       run_input=job.stdin if job.mode=='run' else None)
    except Cancelled:
        return True
    except KeyboardInterrupt:
        Submission.objects.filter(pk=job.pk,status='running',claim_token=job.claim_token).update(status='error',diagnostic='Обработчик остановлен. Отправьте решение повторно.',finished_at=timezone.now())
        raise
    except RunnerError as exc:
        result = {'status':'error', 'diagnostic':str(exc)}
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Judge failed: %s', job.pk)
        result = {'status':'error', 'diagnostic':'Ошибка обработчика. Сообщите преподавателю.'}
    commit_result(job, result)
    return True
