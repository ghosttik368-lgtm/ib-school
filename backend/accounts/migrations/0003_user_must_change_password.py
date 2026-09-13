from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0002_user_study_year_alter_user_avatar_and_more')]
    operations = [migrations.AddField(
        model_name='user', name='must_change_password',
        field=models.BooleanField(default=False, db_default=False, verbose_name='Сменить выданный пароль при входе'),
    )]
