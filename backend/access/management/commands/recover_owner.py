from django.core.management.base import BaseCommand, CommandError
from accounts.models import User
from access.models import AccountSecurity, RecoveryCode
from access.services import audit, revoke_sessions, security_for
from django.db import transaction

class Command(BaseCommand):
    help = 'Console-only MFA recovery for the server owner; password stays unchanged.'
    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--confirm', action='store_true')
    @transaction.atomic
    def handle(self, *args, **options):
        if not options['confirm']: raise CommandError('Укажите --confirm после проверки личности владельца.')
        user = User.objects.filter(username=options['username'], is_superuser=True, is_active=True).first()
        if not user: raise CommandError('Активный владелец не найден.')
        security_for(user)
        AccountSecurity.objects.filter(user=user).update(enabled=False, secret_encrypted='', last_counter=-1)
        RecoveryCode.objects.filter(user=user).delete()
        revoke_sessions(user)
        audit('Сброс 2FA владельца через консоль', subject=user)
        self.stdout.write('2FA сброшена; сеансы отозваны. Пароль не изменён. Подключите 2FA при входе.')
