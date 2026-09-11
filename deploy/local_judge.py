"""Host Docker socket is permitted only in the explicit local test profile."""
import os
import sys

if os.environ.get('DEPLOY_MODE') != 'local' or os.environ.get('BIND_IP') != '127.0.0.1':
    sys.exit('cpp-local is for loopback-only local testing. Configure the remote judge for the server.')
os.execv(sys.executable, [sys.executable, 'backend/manage.py', 'judge_worker'])
