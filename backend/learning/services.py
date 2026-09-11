from math import ceil
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from courses.models import Enrollment, Material, LessonProgress, QuizAttempt
from courses.services import grant_achievement
from .models import BlockProgress
from .rules import evaluate, RULE_VERSION


def course_blocks(course):
    from django.db.models import Q
    return Material.objects.filter(lesson__module__course=course, lesson__is_active=True, attachment_of__isnull=True).filter(~Q(kind='code') | Q(practice_task__isnull=False))


def lock_user(user):
    # Acquire a write lock before reads. SQLite serializes writes; PostgreSQL locks this row.
    get_user_model().objects.filter(pk=user.pk).update(last_login=F('last_login'))


def authorize(user, material, *, practice=False):
    course = material.lesson.module.course
    if not user.is_active or course.status != 'published' or not material.lesson.is_active or material.attachment_of_id:
        raise PermissionDenied
    if material.kind == 'code' and not practice:
        raise ValidationError('Запуск практических заданий появится в M3.')
    if not Enrollment.objects.filter(user=user, course=course).exists():
        raise PermissionDenied
    return course


@transaction.atomic
def open_block(user, material, now=None, *, practice=False):
    lock_user(user)
    authorize(user, material, practice=practice)
    progress, _ = BlockProgress.objects.get_or_create(user=user, material=material)
    if progress.opened_at is None and progress.completed_at is None:
        progress.opened_at = now or timezone.now()
        progress.save(update_fields=['opened_at'])
    return progress


def recalculate(user, course):
    enrollment = Enrollment.objects.get(user=user, course=course)
    blocks = course_blocks(course)
    total = blocks.count()
    done = BlockProgress.objects.filter(user=user, material__in=blocks, completed_at__isnull=False).count()
    enrollment.progress_percent = min(99, round(done * 100 / total)) if total and done < total else 100 if total else 0
    enrollment.completed_at = (enrollment.completed_at or timezone.now()) if total and done == total else None
    enrollment.save(update_fields=['progress_percent', 'completed_at', 'updated_at'])
    for lesson in course.modules.values_list('lessons__id', flat=True):
        ids = blocks.filter(lesson_id=lesson)
        n = ids.count()
        complete = n > 0 and BlockProgress.objects.filter(user=user, material__in=ids, completed_at__isnull=False).count() == n
        if lesson:
            old = LessonProgress.objects.filter(user=user, lesson_id=lesson).first()
            LessonProgress.objects.update_or_create(user=user, lesson_id=lesson, defaults={
                'completed': complete, 'completed_at': (old.completed_at if old and old.completed_at else timezone.now()) if complete else None})
    if total and done == total:
        grant_achievement(user, f'course_complete_{course.pk}', 'Курс завершён', f'Полностью пройден курс «{course.title}».')
    return enrollment


def finish(user, material, progress, submitted_at, source_code=None):
    """Internal: call inside the locked grading transaction, only after acceptance."""
    if progress.completed_at:
        return False
    if not progress.opened_at:
        raise ValidationError('Сначала откройте блок.')
    elapsed = ceil((submitted_at - progress.opened_at).total_seconds() * 1000)
    verdict, reasons, comments = evaluate(material.kind, elapsed, source_code)
    progress.submitted_at = submitted_at
    progress.completed_at = timezone.now()
    progress.elapsed_ms = max(0, elapsed)
    progress.verdict, progress.reasons, progress.comment_count = verdict, reasons, comments
    progress.rule_version = RULE_VERSION
    progress.save()
    recalculate(user, material.lesson.module.course)
    grant_achievement(user, 'first_block', 'Первый шаг', 'Пройден первый блок курса.')
    total = BlockProgress.objects.filter(user=user, completed_at__isnull=False).count()
    for threshold in [25, 100]:
        if total >= threshold:
            grant_achievement(user, f'blocks_{threshold}', f'{threshold} блоков', f'Пройдено {threshold} блоков на платформе.')
    return True


@transaction.atomic
def complete_information(user, material, submitted_at):
    lock_user(user)
    authorize(user, material)
    if material.kind in ('quiz', 'code'):
        raise PermissionDenied
    progress = BlockProgress.objects.filter(user=user, material=material).first()
    if not progress or (not progress.opened_at and not progress.completed_at):
        raise ValidationError('Сначала откройте блок.')
    if not progress.completed_at:
        progress.attempts += 1
    return finish(user, material, progress, submitted_at)


@transaction.atomic
def submit_test(user, quiz, answers, submitted_at):
    lock_user(user)
    material = quiz.material
    authorize(user, material)
    progress = BlockProgress.objects.filter(user=user, material=material).first()
    if not progress or not (progress.opened_at or progress.completed_at):
        raise ValidationError('Сначала откройте блок с тестом.')
    if progress.completed_at:
        return 100, True, False
    questions = list(quiz.questions.prefetch_related('choices'))
    if not questions:
        raise ValidationError('В тесте нет вопросов.')
    correct_count = 0
    selected = {}
    for question in questions:
        values = answers.getlist(f'question_{question.pk}')
        if len(values) > 20 or any(len(x) > 500 for x in values):
            raise ValidationError('Ответ превышает допустимый размер.')
        selected[str(question.pk)] = values
        if question.kind == 'short':
            normalize = (lambda s: s.strip()) if question.case_sensitive else (lambda s: s.strip().casefold())
            correct = len(values) == 1 and normalize(values[0]) in {normalize(s) for s in question.accepted_answers if s.strip()}
        else:
            expected = {str(c.pk) for c in question.choices.all() if c.is_correct}
            correct = bool(expected) and set(values) == expected and len(values) == len(set(values))
            if question.kind == 'single':
                correct = correct and len(values) == 1
        correct_count += bool(correct)
    score = round(correct_count * 100 / len(questions))
    passed = correct_count * 100 >= quiz.passing_score * len(questions)
    QuizAttempt.objects.create(user=user, quiz=quiz, score_percent=score, passed=passed, selected_answers=selected)
    progress.attempts += 1
    progress.save(update_fields=['attempts'])
    awarded = finish(user, material, progress, submitted_at) if passed else False
    return score, passed, awarded


@transaction.atomic
def complete_verified_practice(user, material, submitted_at, source_code):
    """M3 integration point. ONLY a trusted judge may call after tests pass.

    No HTTP route accepts passed=True from a browser. submitted_at must be the
    immutable server timestamp of the accepted submission, not judge finish time.
    M2.5 does not execute code; code blocks remain unavailable to students.
    """
    lock_user(user)
    authorize(user, material, practice=True)
    if material.kind != 'code':
        raise ValidationError('Ожидалось практическое задание.')
    progress = BlockProgress.objects.filter(user=user, material=material).first()
    if not progress or not progress.opened_at:
        raise ValidationError('Нет времени открытия задания.')
    if not progress.completed_at:
        progress.attempts += 1
    return finish(user, material, progress, submitted_at, source_code)
