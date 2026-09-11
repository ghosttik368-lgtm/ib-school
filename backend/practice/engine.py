"""Docker-only execution. Never falls back to a host compiler or host execution."""
import json
import subprocess
import tempfile
import time
import uuid

IMAGE = 'ib-cpp-runner:m34'


class RunnerError(Exception):
    pass


class Cancelled(Exception):
    pass


def check_docker():
    try:
        p = subprocess.run(['docker', 'image', 'inspect', IMAGE], capture_output=True, timeout=15)
        if p.returncode: raise RunnerError('На Docker-узле проверки не найден образ ib-cpp-runner:m34. Проверьте соединение и соберите runner/Dockerfile.')
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RunnerError('Docker недоступен. Проверьте Docker Desktop либо соединение с сервером проверки.') from exc


def sandbox(payload, cancelled=lambda: False):
    name = 'ib-job-' + uuid.uuid4().hex
    compile_mode = payload['mode'] == 'compile'
    memory = 896 if compile_mode else payload['memory']+64
    command = ['docker', 'run', '--rm', '--pull=never', '--name', name,
        '--network=none', '--ipc=none', '--read-only', '--cap-drop=ALL',
        '--security-opt=no-new-privileges:true', '--pids-limit=64', '--cpus=1',
        f'--memory={memory}m', f'--memory-swap={memory}m', '--ulimit=nofile=64:64',
        '--user=65534:65534', '--tmpfs=/work:rw,exec,nosuid,size=64m,mode=1777',
        '--tmpfs=/tmp:rw,noexec,nosuid,size=16m,mode=1777', '-i', IMAGE]
    timeout = 45 if compile_mode else payload['time']+15
    try:
        with tempfile.TemporaryFile() as inp, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            inp.write(json.dumps(payload).encode()); inp.seek(0)
            process = subprocess.Popen(command, stdin=inp, stdout=out, stderr=err)
            try:
                started = time.monotonic()
                while process.poll() is None:
                    if cancelled(): raise Cancelled()
                    if time.monotonic()-started > timeout: raise RunnerError('Контейнер не завершился вовремя.')
                    if out.tell()+err.tell() > 4*1024**2: raise RunnerError('Превышен размер ответа контейнера.')
                    time.sleep(.1)
                out.seek(0); err.seek(0)
                if process.returncode:
                    raise RunnerError('Контейнер завершился с ошибкой. Проверьте память Docker и журнал worker.')
                result = json.loads(out.read(4*1024**2))
                if not isinstance(result, dict): raise RunnerError('Неверный ответ контейнера.')
                return result
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise RunnerError('Не удалось выполнить запрос Docker.') from exc
    finally:
        try: subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired): pass


def judge(code, tests, time_limit, memory_limit, cancelled=lambda: False, run_input=None):
    built = sandbox({'mode':'compile', 'code':code}, cancelled)
    if built.get('status') != 'ok':
        return {'status':'compile_error', 'diagnostic':built.get('stderr', '')[:65536]}
    binary = built.get('binary')
    if not isinstance(binary, str) or len(binary)>2800000: raise RunnerError('Неверный исполняемый файл.')
    if run_input is not None:
        result = sandbox({'mode':'run', 'binary':binary, 'stdin':run_input, 'time':time_limit, 'memory':memory_limit}, cancelled)
        return {'status':'run_ok' if result.get('status')=='ok' else result.get('status','error'), 'stdout':str(result.get('stdout',''))[:65536], 'diagnostic':str(result.get('stderr',''))[:65536]}
    if not tests: raise RunnerError('Нет проверочных тестов.')
    for index, test in enumerate(tests):
        # Expected output stays exclusively in trusted worker memory, never inside a container.
        result = sandbox({'mode':'run', 'binary':binary, 'stdin':test['input'], 'time':time_limit, 'memory':memory_limit}, cancelled)
        if result.get('status') != 'ok':
            return {'status': result.get('status','error'), 'passed_tests':index, 'diagnostic':'Ошибка выполнения на скрытом тесте. Проверьте решение на своём вводе.'}
        if str(result.get('stdout', '')).split() != test['output'].split():
            return {'status':'wrong_answer', 'passed_tests':index, 'diagnostic':'Ответ не совпал на скрытом тесте.'}
    return {'status':'accepted', 'passed_tests':len(tests)}
