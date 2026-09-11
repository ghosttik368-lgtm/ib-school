from datetime import timedelta
from unittest.mock import patch
from importlib import import_module
from django.test import TestCase, SimpleTestCase, TransactionTestCase, Client, override_settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from access.services import security_for
from courses.models import Course, Direction, Module, Lesson, Material, Quiz, Question, AnswerChoice, Enrollment, QuizAttempt, ScoreAward, LessonProgress
from .models import BlockProgress, BlockReview
from .services import open_block, complete_information, submit_test, complete_verified_practice
from .rules import evaluate, zone, cpp_comment_count


class RuleTests(SimpleTestCase):
    def test_threshold_boundaries(self):
        for kind, threshold in [('text', 10000), ('video', 10000), ('quiz', 7000), ('code', 20000)]:
            for elapsed, expected in [(0, 'negative'), (threshold, 'negative'), (threshold+1, 'positive')]:
                self.assertEqual(evaluate(kind, elapsed, 'int main(){}')[0], expected)
        self.assertEqual(evaluate('quiz', 4000)[0], 'negative')

    def test_missing_data_is_not_positive(self):
        self.assertEqual(evaluate('text', None)[0], 'unknown')
        self.assertEqual(evaluate('quiz', -1)[0], 'unknown')
        self.assertEqual(evaluate('code', 50000)[0], 'unknown')

    def test_cpp_comments_and_literal_exclusions(self):
        self.assertEqual(cpp_comment_count('int main(){ /* note */ return 0; } // end'), 2)
        source = 'auto a="https://example.test"; auto b="/* no */"; auto c=R"tag(// no /* no */)tag";'
        self.assertEqual(cpp_comment_count(source), 0)
        self.assertEqual(cpp_comment_count("int n=1'000; // real"), 1)
        self.assertEqual(cpp_comment_count("auto c=L'a'; // real"), 1)
        self.assertEqual(cpp_comment_count('auto s = "quote \\\" // literal"; // real'), 1)
        self.assertEqual(cpp_comment_count('/\\\n/ comment\nint x;'), 1)

    def test_two_reasons_one_negative(self):
        verdict, reasons, count = evaluate('code', 20000, 'int main(){} // text')
        self.assertEqual((verdict, len(reasons), count), ('negative', 2, 1))

    def test_fractional_zones_without_gaps(self):
        for n, total, expected in [(11, 36, 'green'), (33, 100, 'green'), (331, 1000, 'orange'), (66, 100, 'orange'), (661, 1000, 'red'), (1, 1, 'red')]:
            self.assertEqual(zone(n, total)[1], expected)
        self.assertEqual(zone(11, 36)[0], 30.56)
        self.assertEqual(zone(0, 0), (None, 'unknown'))


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], DEV_DISABLE_MFA=True)
class LearningTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user('student', password='Example!882')
        self.teacher = User.objects.create_user('teacher', password='Example!882', role='teacher')
        self.other = User.objects.create_user('other', password='Example!882', role='teacher')
        self.admin = User.objects.create_superuser('admin', password='Example!882')
        self.direction = Direction.objects.create(name='Программирование')
        self.course = Course.objects.create(title='Основы', direction=self.direction, created_by=self.teacher, status='published')
        self.module = Module.objects.create(course=self.course, title='Раздел')
        self.lesson = Lesson.objects.create(module=self.module, title='Урок 1')
        self.text = Material.objects.create(lesson=self.lesson, title='Статья', kind='text', text='SECRET-BLOCK-CONTENT')
        self.material = Material.objects.create(lesson=self.lesson, title='Тест', kind='quiz', order=2)
        self.quiz = Quiz.objects.create(material=self.material, passing_score=100, points=5)
        self.question = Question.objects.create(quiz=self.quiz, text='Вопрос?')
        self.choice = AnswerChoice.objects.create(question=self.question, text='Да', is_correct=True)
        AnswerChoice.objects.create(question=self.question, text='Нет', is_correct=False)
        self.enrollment = Enrollment.objects.create(user=self.student, course=self.course)
        self.client = self.auth(self.student)

    def auth(self, user, csrf=False):
        client = Client(enforce_csrf_checks=csrf)
        client.force_login(user)
        session = client.session
        session['access_version'] = security_for(user).version
        session['mfa_verified'] = False
        session.save()
        return client

    def complete_text(self, seconds=11):
        end = timezone.now()
        open_block(self.student, self.text, now=end-timedelta(seconds=seconds))
        complete_information(self.student, self.text, end)
        return BlockProgress.objects.get(user=self.student, material=self.text)

    def test_lesson_is_only_outline_and_first_open_is_explicit(self):
        self.assertNotContains(self.client.get(reverse('courses:lesson_detail', args=[self.lesson.pk])), 'SECRET-BLOCK-CONTENT')
        self.assertFalse(BlockProgress.objects.exists())
        self.assertNotContains(self.client.get(reverse('learning:block', args=[self.text.pk])), 'SECRET-BLOCK-CONTENT')
        self.client.post(reverse('learning:start', args=[self.text.pk]))
        self.assertContains(self.client.get(reverse('learning:block', args=[self.text.pk])), 'SECRET-BLOCK-CONTENT')
        self.assertIsNotNone(BlockProgress.objects.get().opened_at)

    def test_clock_does_not_reset_across_reopening_or_login(self):
        opened = timezone.now()-timedelta(days=1)
        open_block(self.student, self.text, now=opened)
        another_session = self.auth(self.student)
        another_session.post(reverse('learning:start', args=[self.text.pk]))
        self.assertEqual(BlockProgress.objects.get().opened_at, opened)

    def test_completion_requires_open_and_cannot_complete_quiz_as_information(self):
        self.assertEqual(self.client.post(reverse('learning:complete', args=[self.text.pk])).status_code, 409)
        self.assertEqual(self.client.post(reverse('courses:submit_quiz', args=[self.quiz.pk])).status_code, 409)
        open_block(self.student, self.material)
        self.assertEqual(self.client.post(reverse('learning:complete', args=[self.material.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('courses:complete_lesson', args=[self.lesson.pk])).status_code, 410)
        self.assertFalse(BlockProgress.objects.filter(completed_at__isnull=False).exists())

    def test_one_point_repeat_does_not_change_verdict_or_time(self):
        p = self.complete_text(seconds=2)
        snapshot = (p.completed_at, p.elapsed_ms, p.verdict, p.attempts)
        for _ in range(3):
            self.client.post(reverse('learning:complete', args=[self.text.pk]), {'elapsed': 999999, 'verdict': 'positive'})
        p.refresh_from_db()
        self.assertEqual((p.completed_at, p.elapsed_ms, p.verdict, p.attempts), snapshot)
        self.assertEqual(self.client.get('/rating/data/').json()['rows'][0]['points'], 1)
        self.assertFalse(ScoreAward.objects.exists())

    def test_time_over_boundary_not_rounded_down(self):
        self.assertEqual(self.complete_text(seconds=10.0001).verdict, 'positive')

    def test_failed_quiz_then_pass_uses_first_open(self):
        start = timezone.now()-timedelta(seconds=20)
        open_block(self.student, self.material, now=start)
        url = reverse('courses:submit_quiz', args=[self.quiz.pk])
        self.client.post(url, {})
        p = BlockProgress.objects.get(material=self.material)
        self.assertEqual(p.attempts, 1); self.assertIsNone(p.completed_at)
        self.client.post(url, {f'question_{self.question.pk}': self.choice.pk})
        p.refresh_from_db()
        self.assertEqual(p.attempts, 2); self.assertEqual(p.verdict, 'positive')
        self.assertGreaterEqual(p.elapsed_ms, 20000)
        self.assertEqual(QuizAttempt.objects.count(), 2)
        self.enrollment.refresh_from_db(); self.assertEqual(self.enrollment.progress_percent, 50)
        self.assertFalse(LessonProgress.objects.get(user=self.student, lesson=self.lesson).completed)
        self.complete_text()
        self.enrollment.refresh_from_db(); self.assertEqual(self.enrollment.progress_percent, 100)
        self.assertTrue(LessonProgress.objects.get(user=self.student, lesson=self.lesson).completed)

    def test_two_attachments_do_not_create_extra_points(self):
        attachment = Material.objects.create(lesson=self.lesson, title='PDF версия', kind='pdf', attachment_of=self.text)
        self.complete_text()
        self.enrollment.refresh_from_db(); self.assertEqual(self.enrollment.progress_percent, 50)
        self.assertEqual(self.client.post(reverse('learning:start', args=[attachment.pk])).status_code, 404)

    def test_unauthorized_draft_hidden_and_unenrolled_blocks(self):
        stranger = User.objects.create_user('stranger')
        c = self.auth(stranger)
        self.assertEqual(c.post(reverse('learning:start', args=[self.text.pk])).status_code, 403)
        self.course.status = 'draft'; self.course.save()
        self.assertEqual(self.client.post(reverse('learning:start', args=[self.text.pk])).status_code, 403)
        self.course.status = 'published'; self.course.save()
        self.lesson.is_active = False; self.lesson.save()
        self.assertEqual(self.client.get(reverse('learning:block', args=[self.text.pk])).status_code, 403)

    def test_private_endpoints_deny_students_and_other_teachers(self):
        p = self.complete_text()
        for url in ['/analytics/', '/analytics/data/', f'/analytics/students/{self.student.pk}/']:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(f'/analytics/blocks/{p.pk}/review/', {'verdict': 'positive', 'note': 'x'}).status_code, 403)
        c = self.auth(self.other)
        self.assertEqual(c.get('/analytics/data/').json()['rows'], [])
        self.assertEqual(c.get(f'/analytics/students/{self.student.pk}/').status_code, 403)
        self.assertEqual(c.get(f'/analytics/data/?course={self.course.pk}').status_code, 404)
        self.assertEqual(c.post(f'/analytics/blocks/{p.pk}/review/', {'verdict': 'positive', 'note': 'x'}).status_code, 403)

    def test_public_json_and_html_never_contain_analytics(self):
        self.complete_text(seconds=1)
        for url in ['/rating/data/', f'/rating/students/{self.student.pk}/']:
            data = self.client.get(url).content.decode()
            for secret in ['negative', 'verdict', 'reasons', 'zone', 'elapsed', 'attempts', 'review']:
                self.assertNotIn(secret, data)
        block = self.client.get(reverse('learning:block', args=[self.text.pk]))
        self.assertContains(block, 'Пройден')
        self.assertNotContains(block, 'Успешная отправка за')
        self.assertNotContains(block, '/analytics/')
        self.assertIn('no-store', block['Cache-Control'])

    def test_review_changes_private_counts_not_public_points(self):
        p = self.complete_text(seconds=1)
        c = self.auth(self.teacher)
        self.assertEqual(c.get('/analytics/data/').json()['rows'][0]['zone'], 'red')
        url = f'/analytics/blocks/{p.pk}/review/'
        self.assertEqual(c.post(url, {'verdict': 'positive', 'note': 'Объяснил решение на беседе'}).status_code, 200)
        row = c.get('/analytics/data/').json()['rows'][0]
        self.assertEqual((row['positive'], row['negative'], row['points'], row['zone']), (1, 0, 1, 'green'))
        p.refresh_from_db(); self.assertEqual(p.verdict, 'negative')
        self.assertEqual(c.post(url, {'verdict': 'reset', 'note': 'Повторная проверка'}).status_code, 200)
        self.assertFalse(BlockReview.objects.exists())
        self.assertEqual(c.get('/analytics/data/').json()['rows'][0]['zone'], 'red')

    def test_unknown_is_excluded_from_denominator(self):
        self.complete_text(seconds=1)
        BlockProgress.objects.create(user=self.student, material=self.material, completed_at=timezone.now(), imported=True)
        row = self.auth(self.admin).get('/analytics/data/').json()['rows'][0]
        self.assertEqual((row['points'], row['unknown'], row['percent']), (2, 1, 100))

    def test_teacher_only_sees_own_course_details(self):
        self.complete_text(seconds=1)
        other_course = Course.objects.create(title='SECRET-OTHER-COURSE', direction=self.direction, created_by=self.other, status='published')
        Enrollment.objects.create(user=self.student, course=other_course)
        c = self.auth(self.teacher)
        data = c.get(f'/analytics/students/{self.student.pk}/')
        self.assertNotContains(data, 'SECRET-OTHER-COURSE')
        self.assertEqual(len(data.json()['courses']), 1)
        self.assertEqual(len(self.auth(self.admin).get(f'/analytics/students/{self.student.pk}/').json()['courses']), 2)

    def test_pages_filters_and_profiles_render(self):
        self.complete_text()
        for user in [self.student, self.teacher, self.admin]:
            c = self.auth(user)
            for url in ['/rating/', '/accounts/profile/']:
                self.assertEqual(c.get(url).status_code, 200)
            if user.can_manage_courses:
                self.assertEqual(c.get('/analytics/').status_code, 200)
        data = self.client.get(f'/rating/data/?direction={self.direction.pk}&course={self.course.pk}').json()
        self.assertEqual(data['rows'][0]['points'], 1)
        self.assertEqual(self.client.get('/rating/data/?page=999').json()['page'], 1)

    def test_csrf_and_methods(self):
        c = self.auth(self.student, csrf=True)
        self.assertEqual(c.post(reverse('learning:start', args=[self.text.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('learning:start', args=[self.text.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse('learning:complete', args=[self.text.pk])).status_code, 405)
        self.assertEqual(self.client.post('/rating/data/').status_code, 405)

    def test_code_is_not_executed_and_practice_result_requires_trusted_service(self):
        code = Material.objects.create(lesson=self.lesson, title='C++', kind='code')
        self.assertEqual(self.client.post(reverse('learning:start', args=[code.pk])).status_code, 409)
        self.assertEqual(self.client.post(reverse('learning:complete', args=[code.pk]), {'passed': True, 'code': 'int main(){}'}).status_code, 409)

    def test_failure_rolls_back_point_and_quiz_attempt(self):
        open_block(self.student, self.material)
        answers = QueryDict('', mutable=True)
        answers[f'question_{self.question.pk}'] = str(self.choice.pk)
        with patch('learning.services.recalculate', side_effect=RuntimeError('Simulated failure')):
            with self.assertRaises(RuntimeError):
                submit_test(self.student, self.quiz, answers, timezone.now())
        self.assertFalse(QuizAttempt.objects.exists())
        p = BlockProgress.objects.get(material=self.material)
        self.assertIsNone(p.completed_at)
        self.assertEqual(p.attempts, 0)

    def test_practice_hook_uses_submission_time_and_preserves_first_result(self):
        code = Material.objects.create(lesson=self.lesson, title='C++', kind='code')
        start = timezone.now()-timedelta(minutes=1)
        open_block(self.student, code, now=start, practice=True)
        # Trusted judge result: delay of compilation is NOT counted.
        complete_verified_practice(self.student, code, start+timedelta(seconds=20), 'int main(){} // comment')
        p = BlockProgress.objects.get(material=code)
        self.assertEqual((p.verdict, p.elapsed_ms, len(p.reasons)), ('negative', 20000, 2))
        complete_verified_practice(self.student, code, timezone.now(), 'int main(){}')
        p.refresh_from_db(); self.assertEqual(p.verdict, 'negative')


class MigrationTests(TransactionTestCase):
    def test_upgrade_imports_once_keeps_legacy_awards_and_marks_unknown(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([('learning', None), ('courses', '0003_preserve_quiz_rewards')])
            state = MigrationExecutor(connection).loader.project_state([('courses', '0003_preserve_quiz_rewards'), ('studio', '0001_initial')]).apps
            user = state.get_model('accounts', 'User').objects.create(username='old')
            direction = state.get_model('courses', 'Direction').objects.create(name='Old', slug='old')
            course = state.get_model('courses', 'Course').objects.create(title='Old', slug='old', direction=direction, status='published')
            module = state.get_model('courses', 'Module').objects.create(course=course, title='M')
            lesson = state.get_model('courses', 'Lesson').objects.create(module=module, title='L')
            materials = state.get_model('courses', 'Material')
            article = materials.objects.create(lesson=lesson, title='Article', kind='text')
            material = materials.objects.create(lesson=lesson, title='Quiz', kind='quiz')
            quiz = state.get_model('courses', 'Quiz').objects.create(material=material, points=5)
            state.get_model('courses', 'ScoreAward').objects.create(user=user, course=course, quiz=quiz, points=5)
            state.get_model('courses', 'QuizAttempt').objects.create(user=user, quiz=quiz, passed=True, score_percent=100)
            state.get_model('courses', 'LessonProgress').objects.create(user=user, lesson=lesson, completed=True)
            state.get_model('courses', 'Enrollment').objects.create(user=user, course=course, progress_percent=100)
            MigrationExecutor(connection).migrate(latest)
            self.assertEqual(BlockProgress.objects.count(), 2)
            self.assertEqual(BlockProgress.objects.filter(verdict='unknown', opened_at__isnull=True, imported=True).count(), 2)
            self.assertEqual(ScoreAward.objects.get(user_id=user.pk).points, 5)
            self.assertEqual(Enrollment.objects.get(user_id=user.pk).progress_percent, 100)
            # Re-running import is idempotent and cannot turn unknown into positive.
            forward = import_module('learning.migrations.0002_import_m2_progress').forwards
            with connection.schema_editor() as editor:
                forward(MigrationExecutor(connection).loader.project_state(latest).apps, editor)
            self.assertEqual(BlockProgress.objects.count(), 2)
        finally:
            MigrationExecutor(connection).migrate(latest)
