import importlib
import tempfile
import uuid
from types import SimpleNamespace
from pathlib import Path
from django.apps import apps
from django.test import TestCase, Client, override_settings
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.urls import reverse
from accounts.models import User
from access.services import security_for
from courses.models import ChatMessage
from .models import Room, Member, Message
from . import services


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],DEV_DISABLE_MFA=True)
class MessengerTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        setting = override_settings(MEDIA_ROOT=self.tmp.name)
        setting.enable(); self.addCleanup(setting.disable)
        self.a = User.objects.create_user('alice', password='Example!234')
        self.b = User.objects.create_user('bob', password='Example!234')
        self.c = User.objects.create_user('carol', password='Example!234',role='admin')
        self.room = services.create_room(self.a,'direct','',[self.b.pk])
        self.client = self.auth(self.a)

    def auth(self,user,csrf=False):
        c=Client(enforce_csrf_checks=csrf);c.force_login(user);s=c.session;s['access_version']=security_for(user).version;s.save();return c

    def send(self,user=None,**kwargs):
        return services.send(user or self.a,self.room.pk,kwargs.pop('text','Привет'),kwargs.pop('key',uuid.uuid4()),**kwargs)

    def test_direct_chat_unique_in_both_directions(self):
        r=services.create_room(self.b,'direct','',[self.a.pk])
        self.assertEqual(r.pk,self.room.pk)
        self.assertEqual(Member.objects.filter(room=r).count(),2)

    def test_idempotent_send_and_reject_changed_retry(self):
        key=uuid.uuid4();a=self.send(key=key);b=self.send(key=key)
        self.assertEqual(a.pk,b.pk)
        with self.assertRaises(ValidationError):self.send(key=key,text='Подмена')
        self.assertEqual(Message.objects.filter(room=self.room).count(),1)

    def test_admin_cannot_read_someone_elses_private_chat_or_attachment(self):
        m=self.send(upload=SimpleUploadedFile('example.cpp',b'int main(){}'))
        stranger=self.auth(self.c)
        for name,pk in [('history',self.room.pk),('file',m.pk)]:
            self.assertEqual(stranger.get(reverse('messenger:'+name,args=[pk])).status_code,404)
        self.assertEqual(stranger.post(reverse('messenger:send',args=[self.room.pk]),{'text':'intrude','key':uuid.uuid4()}).status_code,404)

    def test_attachment_is_download_only_and_not_accessible_via_media(self):
        m=self.send(upload=SimpleUploadedFile('note.txt',b'<script>alert(1)</script>'))
        response=self.auth(self.b).get(reverse('messenger:file',args=[m.pk]))
        self.assertEqual(response.status_code,200)
        self.assertIn('attachment',response['Content-Disposition'])
        self.assertEqual(response['Content-Type'],'application/octet-stream')
        response.close()
        self.assertEqual(self.client.get('/media/'+m.attachment.name).status_code,404)

    def test_file_type_size_and_quota_validation(self):
        for name,content in [('bad.html',b'x'),('bad.exe',b'MZ'),('empty.txt',b''),('big.txt',b'a'*(10*1024*1024+1))]:
            with self.assertRaises(ValidationError):self.send(upload=SimpleUploadedFile(name,content))
        m=self.send();Message.objects.filter(pk=m.pk).update(size=100*1024*1024)
        with self.assertRaises(ValidationError):self.send(upload=SimpleUploadedFile('more.txt',b'x'))

    def test_reply_must_belong_to_same_room(self):
        other=services.create_room(self.b,'direct','',[self.c.pk])
        m=services.send(self.b,other.pk,'secret',uuid.uuid4())
        response=self.client.post(reverse('messenger:send',args=[self.room.pk]),{'text':'reply','reply':m.pk,'key':uuid.uuid4()})
        self.assertEqual(response.status_code,404)

    def test_edits_delete_and_reply_previews_are_in_incremental_history(self):
        m=self.send(text='old');reply=self.send(self.b,reply_id=m.pk)
        services.change_message(self.a,m.pk,1,text='new')
        changes=self.client.get(reverse('messenger:history',args=[self.room.pk]),{'since':2}).json()
        self.assertEqual({m['id'] for m in changes['messages']},{m.pk,reply.pk})
        self.assertEqual(next(x for x in changes['messages'] if x['id']==reply.pk)['reply']['text'],'new')
        with self.assertRaises(ValidationError):services.change_message(self.a,m.pk,1,text='stale')
        with self.assertRaises(PermissionDenied):services.change_message(self.b,m.pk,2,text='spoof')
        services.change_message(self.a,m.pk,2,delete=True)
        h=self.client.get(reverse('messenger:history',args=[self.room.pk])).json()
        self.assertTrue(next(x for x in h['messages'] if x['id']==m.pk)['deleted'])

    def test_removing_member_revokes_file_and_history_access(self):
        self.room=services.create_room(self.a,'group','Практика',[self.b.pk,self.c.pk])
        m=self.send(upload=SimpleUploadedFile('note.txt',b'private'))
        services.manage_members(self.a,self.room.pk,'remove',self.b.pk)
        client=self.auth(self.b)
        self.assertEqual(client.get(reverse('messenger:history',args=[self.room.pk])).status_code,404)
        self.assertEqual(client.get(reverse('messenger:file',args=[m.pk])).status_code,404)
        self.assertEqual(client.post(reverse('messenger:send',args=[self.room.pk]),{'text':'x','key':uuid.uuid4()}).status_code,404)

    def test_owner_transfer_then_leave(self):
        self.room=services.create_room(self.a,'group','Группа',[self.b.pk])
        with self.assertRaises(ValidationError):services.manage_members(self.a,self.room.pk,'leave')
        with self.assertRaises(PermissionDenied):services.manage_members(self.b,self.room.pk,'rename',title='hijack')
        services.manage_members(self.a,self.room.pk,'transfer',self.b.pk)
        services.manage_members(self.a,self.room.pk,'leave')
        services.manage_members(self.b,self.room.pk,'rename',title='Новое имя')
        self.room.refresh_from_db();self.assertEqual(self.room.title,'Новое имя')

    def test_unread_is_per_user_and_muting_only_changes_notifications(self):
        a=self.send();b=self.send(self.b)
        self.assertEqual(self.client.get(reverse('messenger:notifications')).json()['chat_count'],1)
        self.client.post(reverse('messenger:read',args=[self.room.pk]),{'last':a.pk})
        self.assertEqual(self.client.get(reverse('messenger:notifications')).json()['chat_count'],1)
        services.manage_members(self.a,self.room.pk,'mute')
        self.assertEqual(self.client.get(reverse('messenger:notifications')).json()['chat_count'],0)
        self.client.post(reverse('messenger:read',args=[self.room.pk]),{'last':b.pk})
        self.client.post(reverse('messenger:read',args=[self.room.pk]),{'last':a.pk})
        self.assertEqual(Member.objects.get(user=self.a,room=self.room).last_read_id,b.pk)

    def test_csrf_and_anonymous_requests_are_rejected(self):
        url=reverse('messenger:send',args=[self.room.pk])
        self.assertEqual(Client().post(url,{'text':'x'}).status_code,302)
        self.assertEqual(self.auth(self.a,csrf=True).post(url,{'text':'x','key':uuid.uuid4()}).status_code,403)

    def test_old_chat_import_preserves_text_dates_and_is_idempotent(self):
        old=ChatMessage.objects.create(user=self.a,text='До обновления')
        fn=importlib.import_module('messenger.migrations.0002_import_common_chat').import_chat
        fn(apps,SimpleNamespace(connection=connection));fn(apps,SimpleNamespace(connection=connection))
        new=Message.objects.get(legacy_id=old.pk)
        self.assertEqual(new.text,old.text);self.assertEqual(new.created_at,old.created_at)
        self.assertTrue(ChatMessage.objects.filter(pk=old.pk).exists())

    def test_chat_page_and_search_render_without_private_profile_data(self):
        self.a.email='private@example.org';self.a.save()
        self.assertContains(self.client.get(reverse('messenger:home')),'chat-compose')
        response=self.auth(self.b).get(reverse('messenger:people'),{'q':'alice'})
        self.assertEqual(response.json()['users'][0]['name'],'alice')
        self.assertNotContains(response,'private@example.org')

    def test_history_paginates_more_than_fifty_messages(self):
        Message.objects.bulk_create([Message(room=self.room,sender=self.a,text=str(i),change_seq=i+1) for i in range(65)])
        self.room.version=65;self.room.save()
        response=self.client.get(reverse('messenger:history',args=[self.room.pk])).json()
        self.assertEqual(len(response['messages']),50);self.assertTrue(response['has_older'])
        older=self.client.get(reverse('messenger:history',args=[self.room.pk]),{'before':response['messages'][0]['id']}).json()
        self.assertEqual(len(older['messages']),15)

    def test_deleted_attachment_removed_after_commit(self):
        m=self.send(upload=SimpleUploadedFile('note.txt',b'data'));path=m.attachment.path
        with self.captureOnCommitCallbacks(execute=True):services.change_message(self.a,m.pk,1,delete=True)
        self.assertFalse(Path(path).exists())
        self.assertEqual(self.client.get(reverse('messenger:file',args=[m.pk])).status_code,404)
