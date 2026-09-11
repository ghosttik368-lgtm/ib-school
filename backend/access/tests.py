from datetime import timedelta
import pyotp
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from courses.models import Course, Direction, Module, Lesson, Material, Quiz, Question
from .models import Invitation, ResetGrant
from .services import security_for, secret_box, consume_otp, new_recovery_codes, digest, revoke_sessions

@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], DEV_DISABLE_MFA=False)
class AccessTests(TestCase):
    def setUp(self):
        self.password = 'River!Moon_8724_safe'
        self.student = User.objects.create_user('student', password=self.password)
        self.teacher = User.objects.create_user('teacher', password=self.password, role='teacher')
        self.admin = User.objects.create_superuser('owner', password=self.password)
        direction = Direction.objects.create(name='Программирование')
        self.course = Course.objects.create(title='Чужой курс', direction=direction, created_by=self.admin)
        module = Module.objects.create(course=self.course, title='Основы')
        self.lesson = Lesson.objects.create(module=module, title='Урок 1')
        self.material = Material.objects.create(lesson=self.lesson, title='Тест', kind='quiz')
        quiz = Quiz.objects.create(material=self.material)
        self.question = Question.objects.create(quiz=quiz, text='Вопрос')

    def auth(self, user):
        client = Client(); client.force_login(user)
        session = client.session
        session['access_version'] = security_for(user).version
        session['mfa_verified'] = True
        session.save()
        return client

    def mfa(self, user):
        secret = pyotp.random_base32(); sec = security_for(user)
        sec.enabled = True; sec.secret_encrypted = secret_box().encrypt(secret.encode()).decode(); sec.save()
        return secret

    def test_invitation_one_use_and_no_role_injection(self):
        Invitation.objects.create(digest=digest('invite'), expires_at=timezone.now()+timedelta(days=1))
        data={'username':'new','study_year':'1','password1':self.password,'password2':self.password,'invitation':'invite','role':'admin'}
        self.assertEqual(self.client.post(reverse('accounts:register'),data).status_code,302)
        self.assertEqual(User.objects.get(username='new').role,'student')
        data['username']='second'
        self.assertEqual(Client().post(reverse('accounts:register'),data).status_code,200)
        self.assertFalse(User.objects.filter(username='second').exists())

    def test_missing_expired_revoked_invite(self):
        data={'username':'new','study_year':'1','password1':self.password,'password2':self.password,'invitation':'invite'}
        self.client.post(reverse('accounts:register'),data)
        invitation=Invitation.objects.create(digest=digest('invite'),expires_at=timezone.now()-timedelta(seconds=1))
        self.client.post(reverse('accounts:register'),data)
        invitation.expires_at=timezone.now()+timedelta(days=1);invitation.revoked_at=timezone.now();invitation.save()
        self.client.post(reverse('accounts:register'),data)
        self.assertFalse(User.objects.filter(username='new').exists())

    def test_student_permissions(self):
        c=self.auth(self.student)
        for url in ['/management/','/access/people/','/access/invitations/','/access/audit/']:
            self.assertEqual(c.get(url).status_code,403)
        self.assertEqual(c.post(reverse('courses:course_delete',args=[self.course.pk])).status_code,403)

    def test_teacher_ownership_all_endpoints(self):
        c=self.auth(self.teacher)
        endpoints=[('course_update',self.course.pk),('course_delete',self.course.pk),('course_unpublish',self.course.pk),('lesson_create',self.course.pk),('lesson_update',self.lesson.pk),('lesson_delete',self.lesson.pk),('material_create',self.lesson.pk),('material_update',self.material.pk),('material_delete',self.material.pk),('question_create',self.material.pk),('question_delete',self.question.pk)]
        for name,pk in endpoints:
            self.assertEqual(c.post(reverse('courses:'+name,args=[pk])).status_code,403,name)
        self.assertEqual(c.post(reverse('courses:course_publish'),{'course_id':self.course.pk}).status_code,403)
        self.assertEqual(c.get('/management/',{'course':self.course.pk}).status_code,403)
        self.assertNotContains(c.get('/management/'),'Чужой курс')

    def test_mfa_setup_before_session(self):
        self.client.post(reverse('login'),{'username':'teacher','password':self.password})
        self.assertNotIn('_auth_user_id',self.client.session)
        response=self.client.get(reverse('access:setup'))
        secret=response.context['secret']
        response=self.client.post(reverse('access:setup'),{'code':pyotp.TOTP(secret).now()})
        self.assertEqual(len(response.context['codes']),8)
        self.assertTrue(self.client.session['mfa_verified'])
        self.assertNotIn(secret,security_for(self.teacher).secret_encrypted)

    def test_mfa_and_recovery_replay(self):
        secret=self.mfa(self.teacher); token=pyotp.TOTP(secret).now()
        self.assertTrue(consume_otp(self.teacher,token));self.assertFalse(consume_otp(self.teacher,token))
        code=new_recovery_codes(self.teacher)[0]
        self.assertTrue(consume_otp(self.teacher,code));self.assertFalse(consume_otp(self.teacher,code))

    def test_session_revocation(self):
        c=self.auth(self.student);revoke_sessions(self.student)
        self.assertEqual(c.get('/').status_code,302)

    @override_settings(DEV_DISABLE_MFA=True)
    def test_local_login_and_admin_actions_without_otp(self):
        self.mfa(self.admin)
        response = self.client.post(reverse('login'), {'username': 'owner', 'password': self.password})
        self.assertEqual(response.status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get('/management/').status_code, 200)
        response = self.client.post(reverse('access:person', args=[self.student.pk]), {'action': 'role', 'role': 'teacher', 'current_password': self.password})
        self.assertEqual(response.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, 'teacher')

    def test_password_change_revokes_sessions(self):
        c=self.auth(self.student);other=self.auth(self.student)
        response=c.post(reverse('password_change'),{'old_password':self.password,'new_password1':'Forest!Rain_8624','new_password2':'Forest!Rain_8624'})
        self.assertEqual(response.status_code,302)
        self.assertNotIn('_auth_user_id',c.session)
        self.assertEqual(other.get('/').status_code,302)

    def test_reset_one_use_preserves_mfa(self):
        self.mfa(self.teacher)
        ResetGrant.objects.create(user=self.teacher,digest=digest('reset'),expires_at=timezone.now()+timedelta(minutes=30))
        data={'username':'teacher','token':'reset','new_password1':'Forest!Rain_8624','new_password2':'Forest!Rain_8624'}
        self.assertEqual(self.client.post(reverse('access:reset'),data).status_code,302)
        self.assertEqual(self.client.post(reverse('access:reset'),data).status_code,200)
        self.assertTrue(security_for(self.teacher).enabled)

    def test_csrf_logout(self):
        c=Client(enforce_csrf_checks=True)
        self.assertEqual(c.post(reverse('login'),{'username':'student','password':self.password}).status_code,403)
        c=self.auth(self.student)
        self.assertEqual(c.get(reverse('logout')).status_code,405)
        c.post(reverse('logout'));self.assertNotIn('_auth_user_id',c.session)

    def test_throttling(self):
        for _ in range(10): self.client.post(reverse('login'),{'username':'student','password':'wrong'})
        self.assertEqual(self.client.post(reverse('login'),{'username':'student','password':'wrong'}).status_code,429)

    def test_templates_render(self):
        c=self.auth(self.admin)
        for url in ['/','/access/people/','/access/invitations/','/access/audit/','/access/security/','/access/components/','/accounts/profile/','/accounts/password_change/','/management/']:
            self.assertEqual(c.get(url).status_code,200,url)
        self.assertEqual(c.get(reverse('access:person',args=[self.student.pk])).status_code,200)
        for url in ['/accounts/login/','/accounts/register/','/access/reset/']:
            self.assertEqual(Client().get(url).status_code,200,url)
