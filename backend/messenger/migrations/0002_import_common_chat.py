from django.conf import settings
from django.db import migrations


def import_chat(apps, schema_editor):
    alias = schema_editor.connection.alias
    Room = apps.get_model('messenger','Room')
    Member = apps.get_model('messenger','Member')
    Message = apps.get_model('messenger','Message')
    OldMessage = apps.get_model('courses','ChatMessage')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    room, _ = Room.objects.using(alias).get_or_create(key='lobby',defaults={'kind':'common','title':'Общий чат'})
    for user_id in User.objects.using(alias).values_list('pk',flat=True).iterator():
        Member.objects.using(alias).get_or_create(room=room,user_id=user_id)
    seq = room.version
    for old in OldMessage.objects.using(alias).order_by('created_at','id').iterator():
        if Message.objects.using(alias).filter(legacy_id=old.pk).exists():
            continue
        seq += 1
        msg = Message.objects.using(alias).create(room=room,sender_id=old.user_id,text=old.text,legacy_id=old.pk,change_seq=seq)
        Message.objects.using(alias).filter(pk=msg.pk).update(created_at=old.created_at)
    Room.objects.using(alias).filter(pk=room.pk).update(version=seq)
    # Prior messages are history, not new notifications after the upgrade.
    last = Message.objects.using(alias).filter(room=room).order_by('-id').values_list('id',flat=True).first() or 0
    Member.objects.using(alias).filter(room=room).update(last_read_id=last)


class Migration(migrations.Migration):
    dependencies = [('messenger','0001_initial'),('courses','0004_material_attachment_of')]
    operations = [migrations.RunPython(import_chat, migrations.RunPython.noop)]
