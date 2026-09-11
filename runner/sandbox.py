"""Runs ONLY inside the disposable Linux container. No database or answer keys."""
import base64
import json
import math
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

OUTPUT_LIMIT = 65536


def execute(args, stdin, seconds, memory):
    Path('/work/input').write_text(stdin, encoding='utf-8')
    def limits():
        resource.setrlimit(resource.RLIMIT_CPU, (math.ceil(seconds), math.ceil(seconds)+1))
        resource.setrlimit(resource.RLIMIT_AS, (memory*1024**2, memory*1024**2))
        resource.setrlimit(resource.RLIMIT_FSIZE, (4*1024**2, 4*1024**2))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    with open('/work/input', 'rb') as inp, open('/work/output', 'w+b') as out, open('/work/error', 'w+b') as err:
        started = time.monotonic()
        process = subprocess.Popen(args, stdin=inp, stdout=out, stderr=err, cwd='/work', start_new_session=True, preexec_fn=limits)
        status = 'ok'
        while process.poll() is None:
            if time.monotonic()-started > seconds:
                status = 'time_limit'
                break
            if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > OUTPUT_LIMIT:
                status = 'output_limit'
                break
            time.sleep(.01)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        # Remove forked children, even if the main program has already exited.
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        if os.fstat(out.fileno()).st_size + os.fstat(err.fileno()).st_size > OUTPUT_LIMIT:
            status = 'output_limit'
        if status == 'ok' and process.returncode:
            status = 'time_limit' if process.returncode == -signal.SIGXCPU else 'runtime_error'
        out.seek(0); err.seek(0)
        return {'status': status, 'stdout': out.read(OUTPUT_LIMIT).decode('utf-8', 'replace'), 'stderr': err.read(OUTPUT_LIMIT).decode('utf-8', 'replace')}


def main():
    payload = json.loads(sys.stdin.buffer.read(4*1024**2))
    if payload['mode'] == 'compile':
        Path('/work/main.cpp').write_text(payload['code'], encoding='utf-8')
        result = execute(['g++', '-std=c++20', '-O2', '-pipe', '-fmax-errors=5', '/work/main.cpp', '-o', '/work/program'], '', 25, 768)
        if result['status'] == 'ok':
            binary = Path('/work/program').read_bytes()
            if len(binary) > 2*1024**2:
                result = {'status':'compile_error', 'stderr':'Программа превышает допустимый размер.'}
            else: result['binary'] = base64.b64encode(binary).decode('ascii')
        else:
            result['status'] = 'compile_error'
    else:
        Path('/work/program').write_bytes(base64.b64decode(payload['binary'], validate=True))
        os.chmod('/work/program', 0o700)
        result = execute(['/work/program'], payload['stdin'], payload['time'], payload['memory'])
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
