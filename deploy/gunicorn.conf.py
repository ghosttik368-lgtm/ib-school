import os

bind = '0.0.0.0:8000'
workers = int(os.environ.get('WEB_WORKERS', '2'))
worker_class = 'gthread'
threads = int(os.environ.get('WEB_THREADS', '4'))
timeout = 180
graceful_timeout = 30
keepalive = 5
max_requests = 1500
max_requests_jitter = 150
worker_tmp_dir = '/tmp'
errorlog = '-'
# Do not log query strings: invitation/reset URLs may contain tokens.
accesslog = None
capture_output = True
forwarded_allow_ips = '*'
