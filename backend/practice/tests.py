import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from access.services import security_for
from courses.models import Course, Direction, Module, Lesson, Material, Enrollment
from learning.models import BlockProgress
from learning.services import open_block
from .models import Task, Submission, Workspace, Worker
from .services import enqueue, process_one, claim, commit_result
from .engine import judge, RunnerError


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],DEV_DISABLE_MFA=True)
class PracticeTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('student',password='Example!728')
        self.other=User.objects.create_user('other',password='Example!728')
        self.course=Course.objects.create(title='C++',direction=Direction.objects.create(name='Coding'),status='published')
        self.lesson=Lesson.objects.create(module=Module.objects.create(course=self.course,title='Module'),title='Lesson')
        self.material=Material.objects.create(lesson=self.lesson,title='Sum',kind='code')
        self.task=Task.objects.create(material=self.material,statement='Add',starter='int main(){}',solution='SECRET_SOLUTION',tests=[{'input':'SECRET_INPUT','output':'SECRET_OUTPUT'}])
        self.enrollment=Enrollment.objects.create(user=self.user,course=self.course)
        Worker.objects.create(name='test',heartbeat=timezone.now())
        self.client=self.auth(self.user)
        open_block(self.user,self.material,now=timezone.now()-timedelta(seconds=30),practice=True)

    def auth(self,user):
        c=Client();c.force_login(user);s=c.session;s['access_version']=security_for(user).version;s['mfa_verified']=False;s.save();return c

    def job(self,mode='check',code='int main(){}'):
        return enqueue(self.user,self.task,code,'',mode,uuid.uuid4())

    def post(self,name,data,pk=None):
        return self.client.post(reverse('practice:'+name,args=[pk or self.material.pk]),json.dumps(data),content_type='application/json')

    def test_public_task_hides_answers_and_initializes_starter(self):
        response=self.client.get(reverse('learning:block',args=[self.material.pk]))
        self.assertContains(response,'source-code')
        self.assertContains(response,'int main(){}')
        for secret in ['SECRET_SOLUTION','SECRET_INPUT','SECRET_OUTPUT']:
            self.assertNotContains(response,secret)
        self.assertEqual(Workspace.objects.get().code,'int main(){}')

    def test_draft_roundtrip_and_stale_revision_conflict(self):
        self.client.get(reverse('learning:block',args=[self.material.pk]))
        data={'type':'code','code':'// saved','stdin':'12','revision':0}
        self.assertEqual(self.post('save',data).json()['revision'],1)
        self.assertEqual(self.post('save',{**data,'code':'overwrite'}).status_code,409)
        self.assertEqual(Workspace.objects.get().code,'// saved')
        response=self.client.get(reverse('learning:block',args=[self.material.pk]))
        self.assertContains(response,'// saved')

    def test_video_save_does_not_complete_or_reset_timer(self):
        video=Material.objects.create(lesson=self.lesson,title='Video',kind='video')
        p=open_block(self.user,video)
        self.assertEqual(self.post('save',{'type':'video','position':42.5,'revision':0},video.pk).status_code,200)
        self.assertEqual(self.post('save',{'type':'video','position':50,'revision':0},video.pk).status_code,409)
        p.refresh_from_db();self.assertIsNone(p.completed_at)
        self.assertEqual(Workspace.objects.get(material=video).video_position,42.5)
        self.assertEqual(self.post('save',{'type':'video','position':float('nan'),'revision':1},video.pk).status_code,400)

    def test_request_id_prevents_duplicates_and_checks_payload(self):
        key=uuid.uuid4()
        a=enqueue(self.user,self.task,'int main(){}','','check',key)
        b=enqueue(self.user,self.task,'int main(){}','','check',key)
        self.assertEqual(a.pk,b.pk)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):enqueue(self.user,self.task,'different','','check',key)

    def test_offline_worker_rejects_new_jobs_and_keeps_draft(self):
        Worker.objects.all().delete()
        response=self.post('submit',{'mode':'check','code':'int main(){}','key':str(uuid.uuid4())})
        self.assertEqual(response.status_code,400)
        self.assertFalse(Submission.objects.exists())

    def test_accept_awards_once_and_uses_original_submission_time(self):
        job=self.job(code='int main(){} // comment')
        with patch('practice.services.judge',return_value={'status':'accepted','passed_tests':1}):process_one('test')
        p=BlockProgress.objects.get(user=self.user,material=self.material)
        self.assertIsNotNone(p.completed_at)
        self.assertEqual(p.submitted_at,job.submitted_at)
        self.assertEqual(p.verdict,'negative');self.assertEqual(p.attempts,1)
        self.enrollment.refresh_from_db();self.assertEqual(self.enrollment.progress_percent,100)
        self.job()
        with patch('practice.services.judge',return_value={'status':'accepted','passed_tests':1}):process_one('test')
        self.assertEqual(BlockProgress.objects.filter(completed_at__isnull=False).count(),1)
        p.refresh_from_db();self.assertEqual(p.attempts,1)

    def test_run_and_failed_checks_do_not_award_points(self):
        for mode,status in [('run','run_ok'),('check','wrong_answer'),('check','compile_error')]:
            self.job(mode)
            with patch('practice.services.judge',return_value={'status':status,'stdout':'hello'}):process_one('test')
        self.assertFalse(BlockProgress.objects.filter(completed_at__isnull=False).exists())
        self.assertEqual(BlockProgress.objects.get().attempts,2)

    def test_cancelled_job_ignores_late_acceptance(self):
        self.job();claimed=claim()
        self.post('cancel',{},claimed.pk)
        commit_result(claimed,{'status':'accepted','passed_tests':1})
        self.assertFalse(BlockProgress.objects.filter(completed_at__isnull=False).exists())

    def test_stale_worker_token_and_incomplete_result_cannot_award(self):
        self.job();claimed=claim()
        claimed.claim_token=uuid.uuid4()
        commit_result(claimed,{'status':'accepted','passed_tests':1})
        self.assertFalse(BlockProgress.objects.filter(completed_at__isnull=False).exists())
        claimed=Submission.objects.get(pk=claimed.pk)
        commit_result(claimed,{'status':'accepted','passed_tests':0})
        claimed.refresh_from_db();self.assertEqual(claimed.status,'error')

    def test_client_cannot_claim_success_or_get_other_users_source(self):
        response=self.post('submit',{'mode':'check','code':'int main(){}','key':str(uuid.uuid4()),'passed':True,'status':'accepted'})
        self.assertEqual(response.json()['status'],'queued')
        self.assertFalse(BlockProgress.objects.filter(completed_at__isnull=False).exists())
        c=self.auth(self.other)
        job=Submission.objects.get()
        self.assertEqual(c.get(reverse('practice:source',args=[job.pk])).status_code,404)
        self.assertEqual(c.post(reverse('practice:cancel',args=[job.pk])).status_code,404)
        self.assertEqual(c.get(reverse('practice:history',args=[self.material.pk])).status_code,403)

    def test_hidden_test_stdout_is_not_exposed(self):
        self.job()
        with patch('practice.services.judge',return_value={'status':'wrong_answer','stdout':'SECRET_INPUT'}):process_one('test')
        response=self.client.get(reverse('practice:history',args=[self.material.pk]))
        self.assertNotContains(response,'SECRET_INPUT')

    def test_resume_ignores_other_students_completed_blocks(self):
        Enrollment.objects.create(user=self.other,course=self.course)
        BlockProgress.objects.create(user=self.other,material=self.material,completed_at=timezone.now())
        Workspace.objects.create(user=self.user,material=self.material,code='int main(){}')
        response=self.client.get(reverse('practice:resume',args=[self.enrollment.pk]))
        self.assertEqual(response.url,reverse('learning:block',args=[self.material.pk]))
        self.assertContains(self.client.get('/library/'),'Продолжить')


class EngineTests(SimpleTestCase):
    def test_expected_answer_never_enters_sandbox_and_whitespace_comparison(self):
        calls=[]
        def fake(payload,cancelled):
            calls.append(payload)
            return {'status':'ok','binary':'YmluYXJ5'} if payload['mode']=='compile' else {'status':'ok','stdout':' 42\n 7\t'}
        with patch('practice.engine.sandbox',side_effect=fake):
            result=judge('code',[{'input':'input','output':'42 7'}],2,128)
        self.assertEqual(result['status'],'accepted')
        self.assertNotIn('output',calls[1]);self.assertNotIn('tests',calls[1])

    def test_hidden_runtime_diagnostic_is_not_returned(self):
        with patch('practice.engine.sandbox',side_effect=[{'status':'ok','binary':'YQ=='},{'status':'runtime_error','stdout':'SECRET','stderr':'SECRET'}]):
            result=judge('code',[{'input':'secret','output':'answer'}],2,128)
        self.assertNotIn('SECRET',str(result))

    def test_missing_docker_does_not_fall_back_to_host(self):
        from practice.engine import check_docker
        with patch('practice.engine.subprocess.run',side_effect=FileNotFoundError):
            with self.assertRaises(RunnerError):check_docker()
