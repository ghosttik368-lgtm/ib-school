import importlib
import uuid
from types import SimpleNamespace
from datetime import timedelta
from django.apps import apps
from django.db import connection
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from access.services import security_for
from courses.models import Course, Direction, Module, Lesson, Material, Enrollment, Quiz, Question, QuizAttempt
from learning.models import BlockProgress, BlockReview
from studio.models import Draft, Release
from practice.models import Task, Submission
from .models import StudyGroup, GroupMember, Assignment, AssignmentStudent, Notice, ReviewEvent, ReportSnapshot
from . import services


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],DEV_DISABLE_MFA=True)
class TeachingTests(TestCase):
    def setUp(self):
        self.teacher=User.objects.create_user('teacher',password='Example!234',role='teacher')
        self.other=User.objects.create_user('other_teacher',password='Example!234',role='teacher')
        self.student=User.objects.create_user('student',password='Example!234')
        self.admin=User.objects.create_user('admin',password='Example!234',role='admin')
        self.course=Course.objects.create(title='C++',created_by=self.teacher,direction=Direction.objects.create(name='Coding'),status='published')
        self.foreign=Course.objects.create(title='SECRET COURSE',created_by=self.other,direction=self.course.direction,status='published')
        self.group=StudyGroup.objects.create(owner=self.teacher,title='ИБ-21')
        self.lesson=Lesson.objects.create(title='Урок',module=Module.objects.create(title='Модуль',course=self.course))
        self.material=Material.objects.create(title='Статья',kind='text',lesson=self.lesson)
        self.enrollment=Enrollment.objects.create(course=self.course,user=self.student)
        self.client=self.auth(self.teacher)

    def auth(self,user):
        c=Client();c.force_login(user);s=c.session;s['access_version']=security_for(user).version;s.save();return c

    def complete(self,verdict='negative',material=None):
        m=material or self.material
        return BlockProgress.objects.create(user=self.student,material=m,opened_at=timezone.now()-timedelta(seconds=3),submitted_at=timezone.now(),completed_at=timezone.now(),elapsed_ms=3000,verdict=verdict,attempts=1,rule_version='M2.5-v1')

    def add_and_assign(self):
        services.change_group(self.teacher,self.group.pk,'add',{'user':self.student.pk})
        services.change_group(self.teacher,self.group.pk,'assign',{'course':self.course.pk})
        return Assignment.objects.get()

    def test_students_cannot_access_teacher_pages_exports_or_rules(self):
        client=self.auth(self.student)
        for name in ['groups','reports','export','rules','snapshots']:
            self.assertEqual(client.get(reverse('teaching:'+name)).status_code,403)
        page=client.get(reverse('teaching:assigned'))
        self.assertContains(page,'Назначенные курсы')
        self.assertNotContains(page,'href="/teaching/"')

    def test_teacher_cannot_see_foreign_groups_course_filters_or_attempts(self):
        client=self.auth(self.other)
        self.assertEqual(client.get(reverse('teaching:group',args=[self.group.pk])).status_code,404)
        self.assertEqual(client.get(reverse('teaching:reports'),{'course':self.course.pk}).status_code,404)
        p=self.complete()
        self.assertEqual(client.get(reverse('teaching:attempts',args=[p.pk])).status_code,404)
        self.assertEqual(client.post(reverse('learning:review',args=[p.pk]),{'verdict':'positive','note':'wrong teacher'}).status_code,403)

    def test_group_assignment_creates_enrollment_and_notice_once(self):
        self.enrollment.delete();assignment=self.add_and_assign()
        services.change_group(self.teacher,self.group.pk,'add',{'user':self.student.pk})
        self.assertEqual(Enrollment.objects.filter(user=self.student).count(),1)
        self.assertEqual(AssignmentStudent.objects.count(),1);self.assertEqual(Notice.objects.count(),1)
        self.assertEqual(AssignmentStudent.objects.get().assignment,assignment)
        self.assertContains(self.auth(self.student).get(reverse('teaching:assigned')),'C++')

    def test_new_member_receives_existing_assignments(self):
        assignment=self.add_and_assign();new=User.objects.create_user('new')
        services.change_group(self.teacher,self.group.pk,'add',{'user':new.pk})
        self.assertTrue(AssignmentStudent.objects.filter(user=new,assignment=assignment).exists())
        self.assertTrue(Notice.objects.filter(user=new).exists())

    def test_group_removal_and_archive_preserve_learning(self):
        self.add_and_assign();self.complete()
        services.change_group(self.teacher,self.group.pk,'remove',{'user':self.student.pk})
        self.assertNotContains(self.auth(self.student).get(reverse('teaching:assigned')),'<h2>C++</h2>',html=True)
        self.assertTrue(Enrollment.objects.filter(pk=self.enrollment.pk).exists());self.assertEqual(BlockProgress.objects.count(),1)
        services.change_group(self.teacher,self.group.pk,'add',{'user':self.student.pk})
        services.change_group(self.teacher,self.group.pk,'archive',{})
        self.assertNotContains(self.auth(self.student).get(reverse('teaching:assigned')),'<h2>C++</h2>',html=True)

    def test_assignment_preserves_student_release(self):
        draft=Draft.objects.create(owner=self.teacher,title='C++')
        Release.objects.create(course=self.course,draft=draft,number=1)
        fresh=Course.objects.create(title='C++ new',created_by=self.teacher,direction=self.course.direction,status='published')
        Release.objects.create(course=fresh,draft=draft,number=2)
        GroupMember.objects.create(group=self.group,user=self.student)
        services.change_group(self.teacher,self.group.pk,'assign',{'course':fresh.pk})
        self.assertEqual(AssignmentStudent.objects.get().enrollment_id,self.enrollment.pk)
        self.assertEqual(Enrollment.objects.filter(user=self.student).count(),1)

    def test_report_filters_and_unknown_marks_denominator(self):
        self.complete('positive')
        m=Material.objects.create(title='Второй',kind='text',lesson=self.lesson);self.complete('unknown',m)
        rows=services.report_rows(self.teacher,{})
        self.assertEqual(rows[0]['blocks'],2);self.assertEqual(rows[0]['positive'],1)
        self.assertEqual(rows[0]['unknown'],1);self.assertEqual(rows[0]['percent'],0);self.assertEqual(rows[0]['zone'],'green')
        self.assertEqual(services.report_rows(self.teacher,{'zone':'red'}),[])
        self.assertEqual(services.report_rows(self.teacher,{'group':self.group.pk}),[])
        GroupMember.objects.create(group=self.group,user=self.student)
        self.assertEqual(len(services.report_rows(self.teacher,{'group':self.group.pk})),1)

    def test_review_history_preserves_every_change_and_points(self):
        p=self.complete()
        for verdict in ['positive','unknown','reset']:
            r=self.client.post(reverse('learning:review',args=[p.pk]),{'verdict':verdict,'note':'Проверено после беседы '+verdict})
            self.assertEqual(r.status_code,200)
        p.refresh_from_db();self.assertEqual(p.verdict,'negative');self.assertIsNotNone(p.completed_at)
        self.assertEqual(ReviewEvent.objects.count(),3);self.assertFalse(BlockReview.objects.exists())
        self.assertEqual(services.report_rows(self.teacher,{})[0]['blocks'],1)
        self.assertEqual(ReviewEvent.objects.first().before,'unknown');self.assertEqual(ReviewEvent.objects.first().after,'negative')

    def test_rule_preview_does_not_change_marks_and_reports_human_agreement(self):
        p=self.complete()
        services.record_review(self.teacher,p,'positive','Разобрали решение вместе')
        response=self.client.get(reverse('teaching:rules'),{'info':0})
        self.assertEqual(response.status_code,200);self.assertEqual(response.context['matrix']['np'],1)
        self.assertEqual(response.context['agreement'],0)
        self.assertEqual(response.context['simulated']['positive'],1)
        p.refresh_from_db();self.assertEqual(p.verdict,'negative');self.assertEqual(p.review.verdict,'positive')

    def test_snapshots_are_immutable_private_and_export_as_utf8(self):
        p=self.complete();rows=services.report_rows(self.teacher,{})
        snapshot=ReportSnapshot.objects.create(owner=self.teacher,title='Неделя 1',rows=rows)
        services.record_review(self.teacher,p,'positive','Проверено')
        response=self.client.get(reverse('teaching:snapshot',args=[snapshot.pk]))
        self.assertContains(response,'Неделя 1');snapshot.refresh_from_db();self.assertEqual(snapshot.rows[0]['negative'],1)
        self.assertEqual(self.auth(self.other).get(reverse('teaching:snapshot',args=[snapshot.pk])).status_code,404)
        csv=self.client.get(reverse('teaching:snapshot',args=[snapshot.pk]),{'download':1})
        self.assertTrue(csv.content.startswith(b'\xef\xbb\xbf'));self.assertIn('attachment',csv['Content-Disposition'])

    def test_csv_neutralizes_spreadsheet_formulas(self):
        self.course.title='=HYPERLINK("https://example.org")';self.course.save()
        response=self.client.get(reverse('teaching:export'))
        self.assertIn("'=HYPERLINK",response.content.decode())

    def test_notification_mark_read_scoped_to_current_user(self):
        a=Notice.objects.create(user=self.student,key='x',text='Курс')
        b=Notice.objects.create(user=self.teacher,key='x',text='Приватное')
        student=self.auth(self.student)
        r=student.get(reverse('messenger:notifications'));self.assertNotContains(r,'Приватное')
        student.post(reverse('messenger:notices_read'),{'ids':[a.pk,b.pk]})
        a.refresh_from_db();b.refresh_from_db();self.assertIsNotNone(a.read_at);self.assertIsNone(b.read_at)

    def test_existing_review_import_is_idempotent(self):
        p=self.complete();r=BlockReview.objects.create(progress=p,reviewer=self.teacher,verdict='positive',note='Ранее проверено')
        fn=importlib.import_module('teaching.migrations.0002_import_reviews').import_reviews
        fn(apps,SimpleNamespace(connection=connection));fn(apps,SimpleNamespace(connection=connection))
        event=ReviewEvent.objects.get();self.assertTrue(event.imported);self.assertEqual(event.created_at,r.updated_at)

    def test_all_teacher_pages_render_with_real_data_and_source_code(self):
        self.add_and_assign();p=self.complete();services.record_review(self.teacher,p,'positive','Обсудили')
        code=Material.objects.create(title='Задача',kind='code',lesson=self.lesson)
        task=Task.objects.create(material=code,statement='Задача',tests=[{'input':'1','output':'1'}])
        cp=self.complete('negative',code)
        Submission.objects.create(user=self.student,task=task,mode='check',code='int main(){}',status='accepted',request_key=uuid.uuid4())
        quiz_material=Material.objects.create(title='Тест',kind='quiz',lesson=self.lesson)
        quiz=Quiz.objects.create(material=quiz_material);question=Question.objects.create(quiz=quiz,text='Ответ?',kind='short',accepted_answers=['42'])
        QuizAttempt.objects.create(user=self.student,quiz=quiz,score_percent=100,passed=True,selected_answers={str(question.pk):['42']})
        qp=self.complete('positive',quiz_material)
        paths=[reverse('teaching:groups'),reverse('teaching:group',args=[self.group.pk]),reverse('teaching:reports'),reverse('teaching:rules'),reverse('teaching:snapshots'),reverse('teaching:student',args=[self.student.pk]),reverse('teaching:attempts',args=[cp.pk]),reverse('teaching:attempts',args=[qp.pk])]
        for path in paths:self.assertEqual(self.client.get(path).status_code,200,path)
        self.assertContains(self.client.get(reverse('teaching:attempts',args=[cp.pk])),'int main(){}')
        self.assertContains(self.client.get(reverse('teaching:student',args=[self.student.pk])),'Обсудили')

    def test_admin_sees_all_course_reports_but_teacher_does_not(self):
        Enrollment.objects.create(user=self.student,course=self.foreign)
        self.assertEqual(len(services.report_rows(self.admin,{})),2)
        self.assertEqual(len(services.report_rows(self.teacher,{})),1)

    def test_snapshot_comparison_uses_frozen_rows_and_checks_both_owners(self):
        before=ReportSnapshot.objects.create(owner=self.teacher,title='Before',rows=services.report_rows(self.teacher,{}))
        self.complete()
        after=ReportSnapshot.objects.create(owner=self.teacher,title='After',rows=services.report_rows(self.teacher,{}))
        response=self.client.get(reverse('teaching:snapshot',args=[after.pk]),{'compare':before.pk})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['changes'][0]['points_delta'],1)
        foreign=ReportSnapshot.objects.create(owner=self.other,title='Private',rows=[])
        self.assertEqual(self.client.get(reverse('teaching:snapshot',args=[after.pk]),{'compare':foreign.pk}).status_code,404)
