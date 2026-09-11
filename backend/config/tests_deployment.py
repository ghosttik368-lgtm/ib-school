from unittest.mock import patch, MagicMock
from django.db import DatabaseError
from django.test import TestCase, SimpleTestCase, override_settings
from django.test import RequestFactory
from accounts.models import User
from autoquiz import ollama


class DockerEndpointTests(SimpleTestCase):
    def test_proxy_uses_one_valid_client_address(self):
        from config.proxy import ProxyClientIPMiddleware
        request = RequestFactory().get('/', REMOTE_ADDR='172.20.0.2', HTTP_X_IB_CLIENT_IP='198.51.100.7')
        self.assertEqual(ProxyClientIPMiddleware(lambda r: r.META['REMOTE_ADDR'])(request), '198.51.100.7')

    def test_proxy_does_not_parse_an_untrusted_address_list(self):
        from config.proxy import ProxyClientIPMiddleware
        request = RequestFactory().get('/', REMOTE_ADDR='172.20.0.2', HTTP_X_IB_CLIENT_IP='1.2.3.4,5.6.7.8')
        self.assertEqual(ProxyClientIPMiddleware(lambda r: r.META['REMOTE_ADDR'])(request), '172.20.0.2')

    @override_settings(AUTOQUIZ_OLLAMA_URL='http://ollama:11434', AUTOQUIZ_OLLAMA_ALLOWED_HOSTS=('ollama',))
    def test_internal_ollama_service_is_explicitly_allowed(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = b'{"models": []}'
        with patch('autoquiz.ollama.urllib.request.build_opener', return_value=opener):
            self.assertEqual(ollama.request('/api/tags'), {'models': []})
        self.assertEqual(opener.open.call_args.args[0].full_url, 'http://ollama:11434/api/tags')

    @override_settings(AUTOQUIZ_OLLAMA_ALLOWED_HOSTS=('ollama',))
    def test_other_hosts_credentials_and_redirects_are_rejected(self):
        for url in ['http://other:11434', 'https://ollama:11434', 'http://u:p@ollama:11434', 'http://ollama:11434/unexpected']:
            with self.subTest(url=url), override_settings(AUTOQUIZ_OLLAMA_URL=url):
                with self.assertRaises(ollama.ModelError): ollama.request('/api/tags')
        with self.assertRaises(ollama.ModelError):
            ollama.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://outside/')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DeploymentAccessTests(TestCase):
    @override_settings(DEV_DISABLE_MFA=True)
    def test_local_teacher_login_with_existing_dev_option(self):
        User.objects.create_user('teacher', password='test-password', role='teacher')
        self.client.post('/accounts/login/', {'username': 'teacher', 'password': 'test-password'})
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get('/management/').status_code, 200)

    @override_settings(DEV_DISABLE_MFA=False)
    def test_server_teacher_login_still_requires_mfa(self):
        User.objects.create_user('teacher', password='test-password', role='teacher')
        self.client.post('/accounts/login/', {'username': 'teacher', 'password': 'test-password'})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertIn('pending_user', self.client.session)

    @override_settings(ROOT_URLCONF='config.container_urls')
    def test_health_checks_database_without_disclosing_details(self):
        self.assertEqual(self.client.get('/healthz/').json(), {'status': 'ok'})
        with patch('config.container_urls.connection.cursor', side_effect=DatabaseError('private details')):
            response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unavailable'})

    @override_settings(ROOT_URLCONF='config.container_urls')
    def test_health_rejects_mutations(self):
        self.assertEqual(self.client.post('/healthz/').status_code, 405)
