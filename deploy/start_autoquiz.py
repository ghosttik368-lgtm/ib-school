"""Do not consume queued videos before both models are installed."""
import os
import sys
import time
import django

django.setup()
from django.conf import settings
from autoquiz import ollama

while True:
    try:
        folder = settings.AUTOQUIZ_MODEL_DIR / settings.AUTOQUIZ_WHISPER
        ready = (folder / 'model.bin').is_file()
        names = {m['name'] for m in ollama.request('/api/tags', timeout=10).get('models', [])}
        if ready and settings.AUTOQUIZ_MODEL in names:
            break
        print('Waiting for models. Follow the AI setup steps in DEPLOY_GUIDE_RU.md.', flush=True)
    except ollama.ModelError:
        print('Waiting for Ollama.', flush=True)
    time.sleep(15)
os.execv(sys.executable, [sys.executable, 'backend/manage.py', 'autoquiz_worker'])
