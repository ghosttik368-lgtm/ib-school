import json
import urllib.error
import urllib.parse
import urllib.request
from django.conf import settings


class ModelError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ModelError('Ollama ответила перенаправлением. Проверьте адрес настроенного сервиса.')


def request(path, payload=None, timeout=None):
    base = settings.AUTOQUIZ_OLLAMA_URL.rstrip('/')
    url = urllib.parse.urlsplit(base)
    allowed_hosts = set(getattr(settings, 'AUTOQUIZ_OLLAMA_ALLOWED_HOSTS', ('127.0.0.1', 'localhost', '::1')))
    if url.scheme != 'http' or url.hostname not in allowed_hosts or url.username or url.password or url.query or url.fragment or url.path:
        raise ModelError('AUTOQUIZ_OLLAMA_URL должен указывать на разрешённый сервис Ollama без пути.')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=body, headers={'Content-Type': 'application/json'})
    try:
        with opener.open(req, timeout=timeout or settings.AUTOQUIZ_TIMEOUT) as response:
            raw = response.read(2*1024*1024 + 1)
            if len(raw) > 2*1024*1024:
                raise ModelError('Ответ модели слишком большой.')
            result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise ModelError(f'Ollama: HTTP {exc.code}. Проверьте установку модели командой autoquiz_check.') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ModelError('Ollama недоступна или не успела ответить. Запустите Ollama; выполните autoquiz_check. При нехватке времени увеличьте AUTOQUIZ_TIMEOUT.') from exc
    except (ValueError, UnicodeError) as exc:
        raise ModelError('Ollama вернула повреждённый ответ.') from exc
    if not isinstance(result, dict) or result.get('error'):
        raise ModelError('Ollama не смогла выполнить запрос. Проверьте модель и свободную память.')
    return result


def chat(model, messages, schema):
    result = request('/api/chat', {'model': model, 'messages': messages, 'format': schema,
        'stream': False, 'keep_alive': 0,
        'options': {'temperature': .25, 'num_ctx': 8192, 'num_predict': 1600,
                    'num_thread': settings.AUTOQUIZ_THREADS, 'num_gpu': 0}})
    if result.get('done_reason') == 'length':
        raise ModelError('Ответ модели оборвался. Уменьшите размер фрагмента лекции.')
    try:
        return json.loads(result['message']['content'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelError('Модель не вернула ожидаемый JSON.') from exc


def unload(model):
    return request('/api/generate', {'model': model, 'keep_alive': 0}, timeout=30)
