import json
from pathlib import Path
import subprocess
import sys
import django

subprocess.run([sys.executable, 'deploy/initialize.py'], check=True)
django.setup()
from django.contrib.auth import get_user_model
from django.core.management import call_command
User = get_user_model()
if not User.objects.exists():
    package = Path('/import/accounts.json')
    if package.is_file():
        call_command('import_accounts', str(package))
    else:
        cfg = json.loads(Path('/run/ib/settings.json').read_text())
        User.objects.create_superuser(username='admin', password=cfg['ADMIN_PASSWORD'], role='admin', must_change_password=True)
        print('Admin created. Read password: docker compose exec web cat /run/ib/admin-password')
else:
    print('Existing users preserved; initial account import skipped.')
