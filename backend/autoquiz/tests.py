import copy
import json
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import User
from access.services import security_for
from courses.models import Direction, Enrollment, Quiz, Course
from studio.models import Draft, Asset
from studio.content import blank, uid, normalize
from studio.services import publish
from learning.models import BlockProgress
from learning.services import open_block, submit_test
from .models import Generation, QuestionSource, WorkerLease
from .services import queue_video, edit_result, apply_result, action, Conflict
from .validation import candidate_checked, parse_subtitles, segments_checked, questions_checked
from .generator import generate
from .worker import acquire, claim, process


TOPICS = ['переменная хранит значение', 'указатель содержит адрес объекта', 'массив объединяет элементы одного типа',
          'цикл повторяет действия', 'функция принимает параметры', 'компилятор переводит исходный текст',
          'условие определяет ветвление', 'строка содержит последовательность символов',
          'структура объединяет поля', 'ссылка обозначает существующий объект']
PROMPTS = ['Что хранит переменная?', 'Как связан указатель с адресом объекта?', 'Что объединяется в массиве?',
           'Для чего применяется цикл?', 'Как функция получает входные данные?', 'Какова роль компилятора?',
           'Как программа выбирает ветвь исполнения?', 'Из чего состоит строка?',
           'Каким способом объединяют разные поля?', 'Что обозначает ссылка в программе?']


def transcript_data():
    return segments_checked([{'start': i*30, 'end': i*30+25,
        'text': f'В этой части мы разбираем основы языка C++: {topic}. Это свойство используется в примере учебной программы и объясняет её поведение.'} for i, topic in enumerate(TOPICS)])


def question_data():
    return questions_checked([{'question': PROMPTS[i], 'choices': [topic, 'Только имя файла', 'Всегда номер строки', 'Только цвет окна'],
        'correct': 0, 'explanation': 'Это объясняется в данном фрагменте лекции.', 'segment': i, 'quote': topic} for i, topic in enumerate(TOPICS)], transcript_data())


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], DEV_DISABLE_MFA=True)
class AutoquizTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user('author', password='valid', role='teacher')
        self.other = User.objects.create_user('other', password='valid', role='teacher')
        self.student = User.objects.create_user('learner', password='valid')
        self.admin = User.objects.create_superuser('admin', password='valid')
        self.direction = Direction.objects.create(name='C++')
        self.temp = tempfile.TemporaryDirectory()
        self.media = override_settings(MEDIA_ROOT=self.temp.name)
        self.media.enable()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.media.disable)
        self.draft = Draft.objects.create(owner=self.teacher, data=blank())
        self.asset = Asset.objects.create(draft=self.draft, file=SimpleUploadedFile('lecture.mp4', b'test fixture'), name='lecture.mp4')
        data = blank()
        data.update(title='Основы C++', description='Разобрать основные конструкции', direction=self.direction.pk)
        self.video_key = uid()
        data['sections'][0]['lessons'] = [{'id': uid(), 'title': 'Урок 1', 'summary': '', 'steps':
            [{'id': self.video_key, 'title': 'Видеолекция', 'kind': 'video', 'asset': self.asset.pk, 'auto_quiz': True}]}]
        self.draft.data = normalize(data, self.draft)
        self.draft.save()
        self.client = self.auth(self.teacher)

    def auth(self, user, csrf=False):
        client = Client(enforce_csrf_checks=csrf)
        client.force_login(user)
        session = client.session
        session['access_version'] = security_for(user).version
        session['mfa_verified'] = False
        session.save()
        return client

    def post(self, name, payload, pk=None, client=None):
        return (client or self.client).post(reverse('autoquiz:'+name, args=[pk or self.job.pk]), json.dumps(payload), content_type='application/json')

    def queue(self, subtitles=True):
        self.job = queue_video(self.draft.pk, self.video_key, self.teacher, transcript_data() if subtitles else None)
        return self.job

    def ready(self):
        self.queue()
        self.job.state = 'ready'
        self.job.questions = question_data()
        self.job.save()
        return self.job

    def approved(self):
        self.ready()
        self.job = edit_result(self.job.pk, self.job.revision, self.job.questions, True)
        return self.job

    def published(self):
        self.approved()
        self.draft, key = apply_result(self.job.pk, self.job.revision, self.draft.revision)
        course = publish(self.draft)
        Enrollment.objects.create(user=self.student, course=course)
        return course

    def test_autosave_creates_one_job_and_respects_opt_out(self):
        self.draft.data['summary'] = 'Правка'
        url = reverse('studio:data', args=[self.draft.pk])
        res = self.client.post(url, json.dumps({'revision': 1, 'data': self.draft.data}), content_type='application/json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(Generation.objects.count(), 1)
        self.draft.refresh_from_db()
        self.draft.data['summary'] = 'Вторая правка'
        self.client.post(url, json.dumps({'revision': self.draft.revision, 'data': self.draft.data}), content_type='application/json')
        self.assertEqual(Generation.objects.count(), 1)
        self.assertEqual(Course.objects.count(), 0)

    def test_manual_queue_is_idempotent(self):
        first = self.queue()
        second = self.queue()
        self.assertEqual(first.pk, second.pk)

    def test_legacy_videos_are_opt_out(self):
        data = copy.deepcopy(self.draft.data)
        step = data['sections'][0]['lessons'][0]['steps'][0]
        del step['auto_quiz']
        result = normalize(data, self.draft)
        self.assertFalse(result['sections'][0]['lessons'][0]['steps'][0]['auto_quiz'])

    def test_private_routes_and_mutations_are_scoped(self):
        self.ready()
        for user in [self.student, self.other]:
            client = self.auth(user)
            for name in ['review', 'status', 'transcript']:
                self.assertEqual(client.get(reverse('autoquiz:'+name, args=[self.job.pk])).status_code, 403)
            for name in ['save', 'control', 'apply']:
                self.assertEqual(self.post(name, {}, client=client).status_code, 403)
            self.assertEqual(client.get(reverse('autoquiz:list', args=[self.draft.pk])).status_code, 403)
            self.assertEqual(self.post('queue', {'video': self.video_key}, pk=self.draft.pk, client=client).status_code, 403)
        self.assertEqual(self.auth(self.admin).get(reverse('autoquiz:review', args=[self.job.pk])).status_code, 200)

    def test_csrf_is_enforced(self):
        self.ready()
        self.assertEqual(self.post('control', {'revision': self.job.revision, 'action': 'regenerate', 'index': 0}, client=self.auth(self.teacher, csrf=True)).status_code, 403)

    def test_review_template_and_transcript_download(self):
        self.ready()
        response = self.client.get(reverse('autoquiz:review', args=[self.job.pk]))
        self.assertContains(response, 'От лекции к практике')
        self.assertContains(response, 'lecture.mp4')
        subtitle = self.client.get(reverse('autoquiz:transcript', args=[self.job.pk]))
        self.assertEqual(parse_subtitles(subtitle.content.decode()), self.job.segments)

    def test_stale_job_revision_does_not_lose_teacher_edit(self):
        self.ready()
        old = self.job.revision
        updated = copy.deepcopy(self.job.questions)
        updated[0]['question'] = 'Что может храниться в переменной согласно лекции?'
        saved = edit_result(self.job.pk, old, updated, False)
        self.assertEqual(saved.questions[0]['question'], updated[0]['question'])
        with self.assertRaises(Conflict):
            edit_result(self.job.pk, old, self.job.questions, True)

    def test_source_anchor_cannot_be_forged_by_form(self):
        self.ready()
        values = copy.deepcopy(self.job.questions)
        values[0]['quote'] = self.job.segments[0]['text']
        with self.assertRaises(ValidationError):
            edit_result(self.job.pk, self.job.revision, values, True)

    def test_apply_requires_review_and_draft_revision(self):
        self.ready()
        with self.assertRaises(ValidationError):
            apply_result(self.job.pk, self.job.revision, self.draft.revision)
        self.job = edit_result(self.job.pk, self.job.revision, self.job.questions, True)
        self.draft.revision += 1
        self.draft.save()
        with self.assertRaises(Conflict):
            apply_result(self.job.pk, self.job.revision, self.draft.revision-1)

    def test_apply_inserts_after_video_once_and_preserves_content(self):
        self.approved()
        original = copy.deepcopy(self.draft.data)
        draft, key = apply_result(self.job.pk, self.job.revision, self.draft.revision)
        duplicate, duplicate_key = apply_result(self.job.pk, self.job.revision, self.draft.revision)
        self.assertEqual(key, duplicate_key)
        result = draft.data['sections'][0]['lessons'][0]['steps']
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], original['sections'][0]['lessons'][0]['steps'][0])
        self.assertEqual(result[1]['kind'], 'quiz')
        self.assertEqual(len(result[1]['questions']), 10)
        self.assertEqual(Course.objects.count(), 0)

    def test_replaced_video_rejects_apply(self):
        self.approved()
        self.draft.data['sections'][0]['lessons'][0]['steps'][0]['asset'] = None
        self.draft.save()
        with self.assertRaises(ValidationError):
            apply_result(self.job.pk, self.job.revision, self.draft.revision)

    def test_publishing_keeps_anchors_on_the_correct_release(self):
        first = self.published()
        second = publish(self.draft)
        self.assertNotEqual(first.pk, second.pk)
        for source in QuestionSource.objects.select_related('video__lesson__module', 'question__quiz__material__lesson__module'):
            self.assertEqual(source.video.lesson.module.course_id, source.question.quiz.material.lesson.module.course_id)
        self.assertEqual(QuestionSource.objects.count(), 20)

    def test_student_sees_feedback_only_after_passing_and_one_point(self):
        course = self.published()
        quiz = Quiz.objects.get(material__lesson__module__course=course)
        student = self.auth(self.student)
        open_block(self.student, quiz.material)
        before = student.get(reverse('learning:block', args=[quiz.material_id]))
        self.assertNotContains(before, 'Разбор по лекции')
        self.assertNotContains(before, 'Это объясняется')
        q = quiz.questions.first()
        self.assertEqual(student.get(reverse('autoquiz:replay', args=[q.pk])).status_code, 403)
        from django.http import QueryDict
        answers = QueryDict('', mutable=True)
        for question in quiz.questions.all():
            answers[f'question_{question.pk}'] = str(question.choices.get(is_correct=True).pk)
        submit_test(self.student, quiz, answers, timezone.now())
        submit_test(self.student, quiz, answers, timezone.now())
        self.assertEqual(BlockProgress.objects.filter(user=self.student, completed_at__isnull=False).count(), 1)
        after = student.get(reverse('learning:block', args=[quiz.material_id]))
        self.assertContains(after, 'Разбор по лекции')
        replay = student.get(reverse('autoquiz:replay', args=[q.pk]))
        self.assertEqual(replay.status_code, 302)
        self.assertIn('?t=', replay.url)
        opened = student.get(replay.url)
        self.assertEqual(opened.status_code, 200)
        self.assertContains(opened, 'name="t"')
        video = q.video_source.video
        started = student.post(reverse('learning:start', args=[video.pk]), {'t': '42.5'})
        self.assertIn('?t=42.500', started.url)
        view = student.get(started.url)
        self.assertEqual(view.context['workspace_data']['seek'], 42.5)

    def test_invalid_seek_does_not_produce_nan_json(self):
        course = self.published()
        video = course.modules.first().lessons.first().materials.get(kind='video')
        open_block(self.student, video)
        response = self.auth(self.student).get(reverse('learning:block', args=[video.pk])+'?t=nan')
        self.assertIsNone(response.context['workspace_data']['seek'])

    def test_worker_builds_ready_draft_without_mutating_course(self):
        self.queue()
        token = acquire()
        job = claim(token)
        initial = copy.deepcopy(self.draft.data)
        with patch('autoquiz.worker.generate', return_value=question_data()) as mocked:
            process(job, token)
        self.job.refresh_from_db()
        self.draft.refresh_from_db()
        self.assertEqual(self.job.state, 'ready')
        self.assertEqual(self.draft.data, initial)
        self.assertEqual(Course.objects.count(), 0)
        self.assertTrue(mocked.called)

    def test_cancelled_job_cannot_be_completed_by_old_worker(self):
        self.queue()
        token = acquire()
        job = claim(token)
        action(job.pk, job.revision, 'cancel')
        with patch('autoquiz.worker.generate') as model:
            process(job, token)
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, 'cancelled')
        model.assert_not_called()

    def test_only_one_worker_and_recovery_after_expired_lease(self):
        self.queue()
        token = acquire()
        claim(token)
        self.assertIsNone(acquire())
        WorkerLease.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertIsNotNone(acquire())
        self.job.refresh_from_db()
        self.assertEqual(self.job.state, 'failed')
        self.assertIn('прерван', self.job.error)

    def test_regeneration_keeps_other_nine_questions(self):
        self.ready()
        old = copy.deepcopy(self.job.questions)
        queued = action(self.job.pk, self.job.revision, 'regenerate', index=4)
        self.assertEqual(queued.questions, old)
        self.assertEqual(queued.replace_index, 4)
        self.assertEqual(queued.reviewed_revision, 0)


class ValidationTests(TestCase):
    def test_srt_and_vtt_timestamps(self):
        value = '1\n00:00:10,000 --> 00:00:12,500\nТекст первого фрагмента.\n\n2\n00:00:15,000 --> 00:00:18,000\nВторой фрагмент.'
        self.assertEqual(parse_subtitles(value)[0]['start'], 10)
        self.assertEqual(parse_subtitles('WEBVTT\n\n00:10.000 --> 00:12.500 align:start\nТекст первого фрагмента.')[0]['end'], 12.5)
        for invalid in ['Просто текст без времени', '1\n00:00:20 --> 00:00:10\nТекст.', '1\n00:90:00 --> 00:99:00\nТекст.']:
            with self.assertRaises(ValidationError):
                parse_subtitles(invalid)

    def test_validation_rejects_invented_quotes_duplicates_and_boolean_index(self):
        candidates = question_data()
        for key, value in [('quote', 'Такой цитаты в лекции не было'), ('correct', True), ('segment', 99999), ('choices', ['a']*4)]:
            bad = dict(candidates[0], **{key: value})
            with self.assertRaises(ValidationError):
                candidate_checked(bad, transcript_data())
        with self.assertRaises(ValidationError):
            candidate_checked(candidates[0], transcript_data(), candidates)

    def test_server_owns_time_and_handles_markup_as_text(self):
        q = question_data()[0]
        q['start'] = -100
        checked = candidate_checked(q, transcript_data())
        self.assertEqual(checked['start'], 0)
        with self.assertRaises(ValidationError):
            segments_checked([{'start': float('nan'), 'end': 10, 'text': 'hello'}])

    def test_generator_retries_bad_answers_and_returns_ten(self):
        questions = question_data()
        batches = [{'questions': [{'question': 'broken'}]}] + [{'questions': questions[i:i+2]} for i in range(0, 10, 2)]
        with patch('autoquiz.generator.ollama.chat', side_effect=batches):
            result = generate(transcript_data(), 'model', lambda message: None)
        self.assertEqual(result, questions)

    def test_generator_refuses_to_invent_missing_questions(self):
        with patch('autoquiz.generator.ollama.chat', return_value={'questions': []}) as mock:
            with self.assertRaises(ValidationError):
                generate(transcript_data(), 'model', lambda message: None)
        self.assertEqual(mock.call_count, 15)

    def test_single_regeneration_preserves_order(self):
        old = question_data()
        replacement = dict(old[3], question='Какая конструкция повторяет действия в изученной программе?')
        with patch('autoquiz.generator.ollama.chat', return_value={'questions': [replacement]}):
            result = generate(transcript_data(), 'model', lambda message: None, old, 3)
        self.assertEqual(result[:3], old[:3])
        self.assertEqual(result[4:], old[4:])
        self.assertEqual(result[3]['question'], replacement['question'])

    @override_settings(AUTOQUIZ_OLLAMA_URL='http://example.org:11434')
    def test_ollama_stays_local(self):
        from .ollama import request, ModelError
        with self.assertRaises(ModelError):
            request('/api/tags')
