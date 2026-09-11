from django.core.management.base import BaseCommand
from django.utils import timezone
from access.models import RateBucket
class Command(BaseCommand):
    def handle(self, *args, **options):
        count, _ = RateBucket.objects.filter(expires_at__lt=timezone.now()).delete()
        self.stdout.write(f'Удалено просроченных ограничителей: {count}')
