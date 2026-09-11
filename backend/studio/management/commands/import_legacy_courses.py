from django.core.management.base import BaseCommand
from studio.services import import_legacy
from studio.models import Draft
class Command(BaseCommand):
    help='Добавить существующие курсы в новый редактор без изменения данных обучения.'
    def handle(self,*args,**kwargs):
        before=Draft.objects.count()
        import_legacy()
        self.stdout.write(f'Добавлено в редактор: {Draft.objects.count()-before}. Исходные уроки и результаты сохранены.')
