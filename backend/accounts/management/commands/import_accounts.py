"""Import the separate, private account package into an empty installation."""
import json
import re
from collections import Counter
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, connection
from access.models import AccountSecurity


def validate_package(path):
    path = Path(path)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise CommandError('Файл аккаунтов слишком большой.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('format') != 'ib-accounts-v1':
        raise CommandError('Нужен accounts.json из отдельного архива аккаунтов.')
    rows = data.get('accounts', [])
    if not rows or len(rows) > 10000:
        raise CommandError('Некорректное количество аккаунтов.')
    names = set()
    for row in rows:
        if set(row) != {'username', 'password', 'role', 'is_superuser'}:
            raise CommandError('Некорректные поля аккаунта.')
        name = row['username']
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{2,149}', name) or name in names:
            raise CommandError('Некорректный или повторяющийся логин.')
        names.add(name)
        if row['role'] not in ('student', 'teacher', 'admin') or type(row['is_superuser']) is not bool:
            raise CommandError('Некорректная роль.')
        if row['is_superuser'] and row['role'] != 'admin':
            raise CommandError('Технический администратор должен иметь роль admin.')
        # Accept only the format we issue. Do not accept plaintext or arbitrary hash algorithms.
        password = row['password']
        if not isinstance(password, str) or not re.fullmatch(r'pbkdf2_sha256\$[0-9]{6,8}\$[A-Za-z0-9]{12,64}\$[A-Za-z0-9+/]{43}=', password):
            raise CommandError('Неверный формат хеша пароля.')
        if not 1_000_000 <= int(password.split('$')[1]) <= 10_000_000:
            raise CommandError('Неподдерживаемые параметры хеша.')
    if dict(Counter(row['role'] for row in rows)) != data.get('counts'):
        raise CommandError('Количество аккаунтов не соответствует описанию пакета.')
    return rows


class Command(BaseCommand):
    help = 'Загрузить выданные аккаунты в пустую базу, не перезаписывая существующих пользователей.'

    def add_arguments(self, parser):
        parser.add_argument('file', type=Path)
        parser.add_argument('--check', action='store_true')

    def handle(self, *args, **options):
        try:
            rows = validate_package(options['file'])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise CommandError('Не удалось прочитать пакет аккаунтов.') from exc
        User = get_user_model()
        with transaction.atomic():
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('LOCK TABLE accounts_user IN EXCLUSIVE MODE')
            if User.objects.exists():
                raise CommandError('База уже содержит пользователей. Импорт остановлен; данные не изменены. Используйте новую установку.')
            if options['check']:
                self.stdout.write(f'Пакет проверен: {len(rows)} аккаунтов. База не изменена.')
                return
            users = [User(username=row['username'], password=row['password'], role=row['role'],
                          is_superuser=row['is_superuser'], is_staff=row['is_superuser'], is_active=True,
                          must_change_password=True)
                     for row in rows]
            User.objects.bulk_create(users)
            AccountSecurity.objects.bulk_create([AccountSecurity(user=user) for user in users])
        self.stdout.write(self.style.SUCCESS(f'Импортировано {len(rows)} аккаунтов. Пароли сохранены в виде хешей.'))
