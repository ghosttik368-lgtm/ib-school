"""Optional AI first-start downloads, entirely inside Compose."""
import json
import subprocess
import sys
import urllib.request
import django

django.setup()
from django.conf import settings
request = urllib.request.Request('http://ollama:11434/api/pull',
    data=json.dumps({'name':settings.AUTOQUIZ_MODEL, 'stream':False}).encode(),
    headers={'Content-Type':'application/json'})
print('Downloading/checking Qwen in the Ollama volume...', flush=True)
with urllib.request.urlopen(request, timeout=3600) as response:
    result = json.load(response)
if result.get('error') or result.get('status') != 'success':
    raise RuntimeError('Ollama model preparation failed: '+str(result))
subprocess.run([sys.executable,'backend/manage.py','autoquiz_prepare'],check=True)
print('Qwen and Whisper ready. Starting the queue worker.',flush=True)
