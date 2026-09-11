import copy
import io
import json
import tempfile
from pathlib import Path
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.urls import reverse
from django.core.exceptions import ValidationError
from accounts.models import User
from access.services import security_for
from courses.models import Course, Direction, Module, Lesson, Material, Quiz, Question, AnswerChoice, Enrollment, LessonProgress, ScoreAward
from .models import Draft, Asset, Release, PublishedAsset
from .content import blank, uid, normalize, problems
from .services import import_course, import_legacy
from learning.models import BlockProgress
from learning.services import open_block


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], DEV_DISABLE_MFA=True)
class StudioTests(TestCase):
    def setUp(self):
        self.teacher=User.objects.create_user('teacher',password='Safe!River824',role='teacher')
        self.other=User.objects.create_user('other',password='Safe!River824',role='teacher')
        self.student=User.objects.create_user('student',password='Safe!River824')
        self.admin=User.objects.create_superuser('owner',password='Safe!River824')
        self.direction=Direction.objects.create(name='Программирование')
        self.client=self.auth(self.teacher)
        self.draft=Draft.objects.create(owner=self.teacher,data=blank())
        self.temp=tempfile.TemporaryDirectory()
        self.media=override_settings(MEDIA_ROOT=self.temp.name);self.media.enable()
        self.addCleanup(self.temp.cleanup);self.addCleanup(self.media.disable)

    def auth(self,user):
        client=Client();client.force_login(user)
        session=client.session;session['access_version']=security_for(user).version;session['mfa_verified']=False;session.save()
        return client

    def post(self,name,data=None,client=None,pk=None):
        return (client or self.client).post(reverse('studio:'+name,args=[pk or self.draft.pk]),json.dumps(data or {}),content_type='application/json')

    def valid(self):
        data=blank();data.update(title='Основы C++',description='Научиться понимать программы',direction=self.direction.pk)
        lesson={'id':uid(),'title':'Урок 1','summary':'Введение','steps':[{'id':uid(),'title':'Статья','kind':'text','html':'<p>Прочитайте материал.</p>','required':True}]}
        data['sections'][0]['lessons']=[lesson]
        return data

    def store(self,data):
        self.draft.refresh_from_db()
        response=self.post('data',{'revision':self.draft.revision,'data':data})
        self.assertEqual(response.status_code,200,response.content)
        self.draft.refresh_from_db()
        return response

    def publish(self):
        self.draft.refresh_from_db()
        response=self.post('publish',{'revision':self.draft.revision})
        self.assertEqual(response.status_code,200,response.content)
        self.draft.refresh_from_db()
        return self.draft.latest_course

    def add_quiz(self,data,kind='single'):
        q={'id':uid(),'type':kind,'text':'Выберите результат','explanation':'Разбор выполненного задания','answers':['Hello'], 'case_sensitive':False,'choices':[{'text':'Правильно','correct':True},{'text':'Неверно','correct':False}]}
        step={'id':uid(),'title':'Тест','kind':'quiz','required':True,'points':5,'passing':100,'questions':[q]}
        data['sections'][0]['lessons'][0]['steps'].append(step)
        return step

    def test_editor_pages_and_create(self):
        response=self.client.post(reverse('studio:create'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(Draft.objects.get(pk=2).owner,self.teacher)
        for url in ['/management/',reverse('studio:editor',args=[self.draft.pk])]:
            self.assertEqual(self.client.get(url).status_code,200,url)
        self.store(self.valid())
        self.assertEqual(self.client.get(reverse('studio:preview',args=[self.draft.pk])).status_code,200)

    def test_student_and_other_teacher_cannot_read_or_write_draft(self):
        for user in [self.student,self.other]:
            client=self.auth(user)
            for route in ['editor','data','preview']:
                self.assertEqual(client.get(reverse('studio:'+route,args=[self.draft.pk])).status_code,403)
            for route in ['data','validate','publish','archive','upload']:
                self.assertEqual(self.post(route,client=client).status_code,403)

    def test_save_roundtrip_and_stale_revision_conflict(self):
        data=self.valid();result=self.store(data)
        stale=self.draft.revision-1
        data['title']='Из другой вкладки'
        self.assertEqual(self.post('data',{'revision':stale,'data':data}).status_code,409)
        self.draft.refresh_from_db();self.assertEqual(self.draft.data['title'],'Основы C++')
        self.assertEqual(self.client.get(reverse('studio:data',args=[self.draft.pk])).json()['revision'],result.json()['revision'])

    def test_unchanged_save_and_publish_are_idempotent(self):
        self.store(self.valid());revision=self.draft.revision
        self.store(self.draft.data);self.assertEqual(self.draft.revision,revision)
        first=self.publish();second=self.publish()
        self.assertEqual(first.pk,second.pk)
        self.assertEqual(Release.objects.filter(draft=self.draft).count(),1)

    def test_publication_blocks_incomplete_course(self):
        result=self.post('publish',{'revision':1})
        self.assertEqual(result.status_code,400)
        self.assertTrue(result.json()['errors'])
        self.assertEqual(Course.objects.count(),0)

    def test_new_release_preserves_enrollment_progress_and_old_content(self):
        self.store(self.valid());old=self.publish()
        lesson=Lesson.objects.get(module__course=old)
        enrollment=Enrollment.objects.create(user=self.student,course=old,progress_percent=100)
        LessonProgress.objects.create(user=self.student,lesson=lesson,completed=True)
        data=copy.deepcopy(self.draft.data);data['title']='Новая программа';data['sections'][0]['lessons'][0]['steps'][0]['html']='<p>Новый текст</p>'
        self.store(data)
        self.assertEqual(Course.objects.get(pk=old.pk).title,'Основы C++')
        new=self.publish();old.refresh_from_db();enrollment.refresh_from_db()
        self.assertFalse(old.is_listed);self.assertTrue(new.is_listed)
        self.assertEqual(old.status,'published');self.assertEqual(enrollment.progress_percent,100)
        self.assertIn('Прочитайте',Material.objects.get(lesson=lesson).text)
        c=self.auth(self.student)
        response=c.post(reverse('courses:enroll_course',args=[new.slug]))
        self.assertEqual(response.url,old.get_absolute_url())
        self.assertEqual(Enrollment.objects.filter(user=self.student).count(),1)
        self.assertEqual(c.get(reverse('courses:lesson_detail',args=[lesson.pk])).status_code,200)
        home=c.get('/');self.assertContains(home,'Новая программа');self.assertContains(home,old.get_absolute_url())

    def test_archive_hides_catalog_but_preserves_learning(self):
        self.store(self.valid());course=self.publish()
        Enrollment.objects.create(user=self.student,course=course)
        response=self.post('archive',{'revision':self.draft.revision});self.assertEqual(response.status_code,200)
        course.refresh_from_db();self.assertFalse(course.is_listed);self.assertEqual(course.status,'published')
        newcomer=User.objects.create_user('newcomer',password='Anything!728')
        self.assertEqual(self.auth(newcomer).post(reverse('courses:enroll_course',args=[course.slug])).status_code,403)
        self.assertContains(self.auth(self.student).get('/library/'),course.title)

    def test_multiple_and_short_answers_award_only_once(self):
        for kind in ['multiple','short']:
            with self.subTest(kind=kind):
                if kind=='short':self.draft=Draft.objects.create(owner=self.teacher,data=blank())
                data=self.valid();step=self.add_quiz(data,kind)
                if kind=='multiple':step['questions'][0]['choices'].append({'text':'Тоже правильно','correct':True})
                self.store(data);course=self.publish();quiz=Quiz.objects.get(material__lesson__module__course=course);question=quiz.questions.get()
                Enrollment.objects.create(user=self.student,course=course)
                client=self.auth(self.student)
                open_block(self.student, quiz.material)
                answers=[' hello '] if kind=='short' else [str(c.pk) for c in question.choices.filter(is_correct=True)]
                for _ in range(2):
                    result=client.post(reverse('courses:submit_quiz',args=[quiz.pk]),{f'question_{question.pk}':answers})
                    self.assertEqual(result.status_code,302)
                awards=BlockProgress.objects.filter(user=self.student,material=quiz.material,completed_at__isnull=False)
                self.assertEqual(awards.count(),1)
                self.assertFalse(ScoreAward.objects.filter(user=self.student,quiz=quiz).exists())

    def test_partial_multiple_answer_does_not_pass(self):
        data=self.valid();step=self.add_quiz(data,'multiple');step['questions'][0]['choices'][1]['correct']=True
        self.store(data);course=self.publish();quiz=Quiz.objects.get(material__lesson__module__course=course);q=quiz.questions.get()
        Enrollment.objects.create(user=self.student,course=course)
        open_block(self.student, quiz.material)
        self.auth(self.student).post(reverse('courses:submit_quiz',args=[quiz.pk]),{f'question_{q.pk}':str(q.choices.first().pk)})
        self.assertFalse(ScoreAward.objects.exists())
        self.assertFalse(BlockProgress.objects.filter(completed_at__isnull=False).exists())

    def test_configurable_passing_and_one_block_point(self):
        data=self.valid();step=self.add_quiz(data);step['passing']=50;step['points']=8
        q2=copy.deepcopy(step['questions'][0]);q2['id']=uid();step['questions'].append(q2)
        self.store(data);course=self.publish();quiz=Quiz.objects.get(material__lesson__module__course=course);q=quiz.questions.first()
        Enrollment.objects.create(user=self.student,course=course)
        open_block(self.student, quiz.material)
        self.auth(self.student).post(reverse('courses:submit_quiz',args=[quiz.pk]),{f'question_{q.pk}':str(q.choices.filter(is_correct=True).get().pk)})
        self.assertEqual(BlockProgress.objects.filter(user=self.student,material=quiz.material,completed_at__isnull=False).count(),1)
        self.assertFalse(ScoreAward.objects.filter(user=self.student,quiz=quiz).exists())

    def test_sanitization_removes_active_markup(self):
        data=self.valid();data['sections'][0]['lessons'][0]['steps'][0]['html']='<p onclick="bad()">Текст</p><script>bad()</script><a href="javascript:bad()">x</a><img src="https://tracker.test/x" onerror="bad()"><iframe src="https://evil.test"></iframe>'
        self.store(data);html=self.draft.data['sections'][0]['lessons'][0]['steps'][0]['html']
        for value in ['<script','onclick','onerror','javascript:','tracker.test','<iframe']:self.assertNotIn(value,html)
        self.assertIn('<p>Текст</p>',html)

    def test_cannot_reference_another_drafts_asset(self):
        other=Draft.objects.create(owner=self.other,data=blank())
        asset=Asset.objects.create(draft=other,file='private.pdf',name='private.pdf')
        data=self.valid();data['sections'][0]['lessons'][0]['steps'][0].update(kind='pdf',asset=asset.pk)
        self.assertEqual(self.post('data',{'revision':1,'data':data}).status_code,400)

    def test_code_constructor_publishes_and_preview_hides_secrets(self):
        data=self.valid();data['sections'][0]['lessons'][0]['steps'].append({'id':uid(),'kind':'code','title':'Сумма','code':{'statement':'Сложите числа','starter':'int main() {}','solution':'SECRET_REFERENCE_SOLUTION','tests':[{'input':'PRIVATE_TEST_123','output':'42'}]}})
        self.store(data)
        response=self.post('publish',{'revision':self.draft.revision})
        self.assertEqual(response.status_code,200)
        from practice.models import Task
        self.assertEqual(Task.objects.get().statement,'Сложите числа')
        response=self.client.get(reverse('studio:preview',args=[self.draft.pk]))
        self.assertNotContains(response,'SECRET_REFERENCE_SOLUTION');self.assertNotContains(response,'PRIVATE_TEST_123')

    def test_preview_never_changes_progress_or_awards(self):
        data=self.valid();self.add_quiz(data);self.store(data)
        response=self.client.get(reverse('studio:preview',args=[self.draft.pk]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(Enrollment.objects.count(),0);self.assertEqual(ScoreAward.objects.count(),0)
        self.assertNotContains(response,'Разбор выполненного задания')

    def test_upload_and_private_range_access(self):
        response=self.client.post(reverse('studio:upload',args=[self.draft.pk]),{'file':SimpleUploadedFile('lecture.mp4',b'0123456789',content_type='video/mp4')})
        self.assertEqual(response.status_code,200)
        url=response.json()['url'];asset_id=response.json()['id']
        self.assertEqual(self.auth(self.other).get(url).status_code,404)
        self.assertEqual(Client().get(url).status_code,302)
        response=self.client.get(url,HTTP_RANGE='bytes=2-5')
        self.assertEqual(response.status_code,206);self.assertEqual(b''.join(response.streaming_content),b'2345')
        self.assertEqual(response['Content-Range'],'bytes 2-5/10')
        self.assertEqual(self.client.get(url,HTTP_RANGE='bytes=20-30').status_code,416)
        data=self.valid();data['sections'][0]['lessons'][0]['steps'][0].update(kind='video',asset=asset_id,html='')
        self.store(data);course=self.publish()
        self.assertEqual(self.auth(self.student).get(url).status_code,404)
        Enrollment.objects.create(user=self.student,course=course)
        response=self.auth(self.student).get(url);self.assertEqual(response.status_code,200);response.close()

    def test_shared_file_access_from_new_release_and_pdf_frame_header(self):
        response=self.client.post(reverse('studio:upload',args=[self.draft.pk]),{'file':SimpleUploadedFile('note.pdf',b'%PDF-1.7\nexample')})
        data=self.valid();data['sections'][0]['lessons'][0]['steps'][0].update(kind='pdf',asset=response.json()['id'])
        self.store(data);old=self.publish()
        data=copy.deepcopy(self.draft.data);data['title']='Обновлённый';self.store(data);new=self.publish()
        Enrollment.objects.create(user=self.student,course=new)
        material=Material.objects.get(lesson__module__course=new)
        response=self.auth(self.student).get(material.file.url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['X-Frame-Options'],'SAMEORIGIN');response.close()

    def test_image_validation_and_non_image_cover_rejected(self):
        bad=self.client.post(reverse('studio:upload',args=[self.draft.pk]),{'file':SimpleUploadedFile('fake.png',b'<html>')})
        self.assertEqual(bad.status_code,400)
        stream=io.BytesIO();Image.new('RGB',(10,10)).save(stream,format='PNG')
        good=self.client.post(reverse('studio:upload',args=[self.draft.pk]),{'file':SimpleUploadedFile('cover.png',stream.getvalue())})
        self.assertEqual(good.status_code,200)
        data=self.valid();data['cover']=good.json()['id'];self.store(data)

    def test_hidden_lesson_stays_in_draft_without_public_file_access(self):
        upload=self.client.post(reverse('studio:upload',args=[self.draft.pk]),{'file':SimpleUploadedFile('hidden.pdf',b'%PDF-1.7 hidden')}).json()
        data=self.valid()
        data['sections'][0]['lessons'].append({'id':uid(),'title':'Скрытый урок','active':False,'steps':[{'id':uid(),'title':'Закрытый документ','kind':'pdf','asset':upload['id']}]})
        self.store(data);course=self.publish()
        Enrollment.objects.create(user=self.student,course=course)
        self.assertEqual(self.auth(self.student).get(upload['url']).status_code,404)
        self.assertFalse(Lesson.objects.get(module__course=course,title='Скрытый урок').is_active)
        self.assertNotContains(self.client.get(reverse('studio:preview',args=[self.draft.pk])),'Скрытый урок')

    def test_legacy_import_is_idempotent_and_preserves_ids(self):
        course=Course.objects.create(title='Старый курс',direction=self.direction,created_by=self.teacher,status='published',points_per_test=9)
        module=Module.objects.create(course=course,title='Раздел');lesson=Lesson.objects.create(module=module,title='Старый урок')
        material=Material.objects.create(lesson=lesson,title='Старый тест',kind='quiz')
        quiz=Quiz.objects.create(material=material,points=9);q=Question.objects.create(quiz=quiz,text='Вопрос')
        AnswerChoice.objects.create(question=q,text='Да',is_correct=True);AnswerChoice.objects.create(question=q,text='Нет')
        Enrollment.objects.create(user=self.student,course=course,progress_percent=100)
        ScoreAward.objects.create(user=self.student,course=course,quiz=quiz,points=9)
        draft=import_course(course);same=import_course(course)
        self.assertEqual(draft.pk,same.pk);self.assertEqual(draft.data['sections'][0]['lessons'][0]['steps'][0]['points'],9)
        self.assertTrue(Lesson.objects.filter(pk=lesson.pk).exists());self.assertEqual(ScoreAward.objects.get().points,9)

    def test_deprecated_editor_cannot_mutate_publication(self):
        self.store(self.valid());course=self.publish()
        response=self.client.post(reverse('courses:course_delete',args=[course.pk]))
        self.assertEqual(response.status_code,410);self.assertTrue(Course.objects.filter(pk=course.pk).exists())

    def test_publish_stale_revision_and_csrf(self):
        self.store(self.valid())
        self.assertEqual(self.post('publish',{'revision':1}).status_code,409)
        client=Client(enforce_csrf_checks=True);client.force_login(self.teacher)
        session=client.session;session['access_version']=security_for(self.teacher).version;session.save()
        response=client.post(reverse('studio:data',args=[self.draft.pk]),'{}',content_type='application/json')
        self.assertEqual(response.status_code,403)


class UpgradeTests(TransactionTestCase):
    def test_m1_database_upgrade_preserves_rewards_and_progress(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        executor=MigrationExecutor(connection)
        latest=executor.loader.graph.leaf_nodes()
        legacy = ('courses', '0002_question_alter_lesson_options_alter_course_cover_and_more')
        baseline = legacy if legacy in executor.loader.graph.nodes else ('courses', '0001_initial')
        try:
            executor.migrate([('studio',None),baseline])
            executor=MigrationExecutor(connection)
            apps=executor.loader.project_state([baseline]).apps
            OldUser=apps.get_model('accounts','User')
            OldDirection=apps.get_model('courses','Direction')
            OldCourse=apps.get_model('courses','Course')
            OldModule=apps.get_model('courses','Module')
            OldLesson=apps.get_model('courses','Lesson')
            OldMaterial=apps.get_model('courses','Material')
            OldQuiz=apps.get_model('courses','Quiz')
            OldEnrollment=apps.get_model('courses','Enrollment')
            OldAward=apps.get_model('courses','ScoreAward')
            user=OldUser.objects.create(username='legacy-student')
            direction=OldDirection.objects.create(name='Реверс',slug='reverse')
            course=OldCourse.objects.create(direction=direction,title='Существующий курс',slug='existing',status='published',points_per_test=9)
            module=OldModule.objects.create(course=course,title='Основы')
            lesson=OldLesson.objects.create(module=module,title='Урок 1')
            material=OldMaterial.objects.create(lesson=lesson,title='Тест',kind='quiz')
            quiz=OldQuiz.objects.create(material=material)
            OldEnrollment.objects.create(user=user,course=course,progress_percent=100)
            OldAward.objects.create(user=user,course=course,quiz=quiz,points=9)
            MigrationExecutor(connection).migrate(latest)
            self.assertEqual(Quiz.objects.get(pk=quiz.pk).points,9)
            self.assertEqual(Enrollment.objects.get(user_id=user.pk).progress_percent,100)
            self.assertEqual(ScoreAward.objects.get(user_id=user.pk).points,9)
            self.assertTrue(Lesson.objects.filter(pk=lesson.pk).exists())
            draft=import_course(Course.objects.get(pk=course.pk))
            self.assertEqual(draft.latest_course_id,course.pk)
        finally:
            MigrationExecutor(connection).migrate(latest)
