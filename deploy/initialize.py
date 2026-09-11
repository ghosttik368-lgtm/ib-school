import subprocess
import sys

for args in [
    ['check'], ['makemigrations', '--check', '--dry-run'],
    ['migrate', '--noinput'], ['collectstatic', '--noinput'],
]:
    subprocess.run([sys.executable, 'backend/manage.py', *args], check=True)
print('Database and static files are ready.')
