import json
from pathlib import Path
import tempfile
from django.contrib.auth.hashers import PBKDF2PasswordHasher
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from accounts.models import User
from access.models import AccountSecurity
from access.services import security_for


@override_settings(DEV_DISABLE_MFA=True)
class IssuanceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        h = PBKDF2PasswordHasher()
        cls.hashed = h.encode('Issued-Only-824!', h.salt())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'accounts.json'
        self.package = {'format': 'ib-accounts-v1', 'counts': {'student': 1, 'teacher': 1, 'admin': 1},
                        'accounts': [{'username': role + '001', 'password': self.hashed, 'role': role,
                                      'is_superuser': role == 'admin'} for role in ['student', 'teacher', 'admin']]}

    def write_package(self):
        self.path.write_text(json.dumps(self.package), encoding='utf-8')

    def test_import_creates_roles_hashes_and_security(self):
        self.write_package()
        call_command('import_accounts', self.path, verbosity=0)
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(AccountSecurity.objects.count(), 3)
        self.assertTrue(all(User.objects.values_list('must_change_password', flat=True)))
        self.assertFalse(User.objects.get(role='student').can_manage_courses)
        self.assertTrue(User.objects.get(role='teacher').can_manage_courses)
        self.assertTrue(User.objects.get(role='admin').is_platform_admin)
        self.assertTrue(User.objects.get(role='student').check_password('Issued-Only-824!'))

    def test_dry_run_and_repeated_import_do_not_overwrite(self):
        self.write_package()
        call_command('import_accounts', self.path, check=True, verbosity=0)
        self.assertEqual(User.objects.count(), 0)
        call_command('import_accounts', self.path, verbosity=0)
        User.objects.filter(username='student001').update(first_name='Сохранить')
        with self.assertRaises(CommandError):
            call_command('import_accounts', self.path, verbosity=0)
        self.assertEqual(User.objects.get(username='student001').first_name, 'Сохранить')

    def test_invalid_late_record_creates_nothing(self):
        self.package['accounts'][-1]['password'] = 'plaintext-not-allowed'
        self.write_package()
        with self.assertRaises(CommandError):
            call_command('import_accounts', self.path, verbosity=0)
        self.assertEqual(User.objects.count(), 0)

    def test_duplicate_and_privilege_mismatch_are_rejected(self):
        for key, value in [('username', 'student001'), ('is_superuser', True)]:
            original = self.package['accounts'][1][key]
            self.package['accounts'][1][key] = value
            self.write_package()
            with self.assertRaises(CommandError):
                call_command('import_accounts', self.path, verbosity=0)
            self.package['accounts'][1][key] = original

    def test_issued_user_must_change_password_before_courses(self):
        user = User.objects.create(username='issued001', password=self.hashed, must_change_password=True)
        self.client.post('/accounts/login/', {'username': user.username, 'password': 'Issued-Only-824!'})
        self.assertRedirects(self.client.get('/'), '/accounts/password_change/', fetch_redirect_response=False)
        response = self.client.post('/accounts/password_change/', {'old_password': 'Issued-Only-824!',
                                   'new_password1': 'Personal-Only-928!x', 'new_password2': 'Personal-Only-928!x'})
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.must_change_password)
        self.assertFalse(user.check_password('Issued-Only-824!'))
        self.assertTrue(user.check_password('Personal-Only-928!x'))
        self.client.post('/accounts/login/', {'username': user.username, 'password': 'Personal-Only-928!x'})
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_existing_account_is_not_forced_to_change(self):
        user = User.objects.create(username='existing', password=self.hashed)
        self.client.force_login(user)
        session = self.client.session
        session['access_version'] = security_for(user).version
        session.save()
        self.assertEqual(self.client.get('/').status_code, 200)
