from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    db = schema_editor.connection.alias
    Material = apps.get_model('courses', 'Material')
    Asset = apps.get_model('studio', 'Asset')
    Release = apps.get_model('studio', 'Release')
    Progress = apps.get_model('learning', 'BlockProgress')
    Attempt = apps.get_model('courses', 'QuizAttempt')
    Award = apps.get_model('courses', 'ScoreAward')
    LessonProgress = apps.get_model('courses', 'LessonProgress')
    Enrollment = apps.get_model('courses', 'Enrollment')
    # M2 creates a second Material for an optional PDF rendition. It is an
    # attachment to one authored block, not a separately rewarded block.
    for release in Release.objects.using(db).all().iterator():
        snapshot = release.snapshot or {}
        lesson_number = 0
        for section in snapshot.get('sections', []):
            for lesson in section.get('lessons', []):
                lesson_number += 1
                for i, step in enumerate(lesson.get('steps', []), 1):
                    viewer = step.get('viewer')
                    if not viewer:
                        continue
                    asset = Asset.objects.using(db).filter(pk=viewer).first()
                    if not asset:
                        continue
                    base = Material.objects.using(db).filter(lesson__module__course_id=release.course_id, lesson__order=lesson_number, order=i*2, title=step.get('title', '')).first()
                    if base:
                        Material.objects.using(db).filter(lesson_id=base.lesson_id, order=i*2+1, kind='pdf', file=asset.file.name, title=base.title+' — просмотр PDF').update(attachment_of_id=base.pk)

    def record(user_id, material_id, when, attempts=0, reason='Перенесено из M2; время открытия неизвестно'):
        Progress.objects.using(db).get_or_create(user_id=user_id, material_id=material_id, defaults={
            'completed_at': when or timezone.now(), 'submitted_at': None, 'opened_at': None,
            'verdict': 'unknown', 'imported': True, 'reasons': [reason], 'attempts': attempts,
        })

    for attempt in Attempt.objects.using(db).filter(passed=True).select_related('quiz__material').order_by('created_at', 'id').iterator():
        material = attempt.quiz.material
        if material.attachment_of_id or material.kind != 'quiz':
            continue
        attempts = Attempt.objects.using(db).filter(user_id=attempt.user_id, quiz_id=attempt.quiz_id, created_at__lte=attempt.created_at).count()
        record(attempt.user_id, material.pk, attempt.created_at, attempts)
    # Some old installations retain awards but not attempts.
    for award in Award.objects.using(db).select_related('quiz__material').all().iterator():
        material = award.quiz.material
        if not material.attachment_of_id and material.kind == 'quiz':
            record(award.user_id, material.pk, award.created_at)
    for old in LessonProgress.objects.using(db).filter(completed=True).iterator():
        for material in Material.objects.using(db).filter(lesson_id=old.lesson_id, attachment_of__isnull=True).exclude(kind__in=['quiz', 'code']).iterator():
            record(old.user_id, material.pk, old.completed_at, reason='Перенесено по отметке завершённого урока M2; просмотр отдельного блока неизвестен')

    for enrollment in Enrollment.objects.using(db).all().iterator():
        materials = Material.objects.using(db).filter(lesson__module__course_id=enrollment.course_id, lesson__is_active=True, attachment_of__isnull=True).exclude(kind='code')
        total = materials.count()
        done = Progress.objects.using(db).filter(user_id=enrollment.user_id, material__in=materials, completed_at__isnull=False).count()
        percent = (min(99, round(done*100/total)) if done < total else 100) if total else 0
        Enrollment.objects.using(db).filter(pk=enrollment.pk).update(progress_percent=percent, completed_at=(enrollment.completed_at or timezone.now()) if total and done == total else None)
        for old in LessonProgress.objects.using(db).filter(user_id=enrollment.user_id, lesson__module__course_id=enrollment.course_id).iterator():
            ids = materials.filter(lesson_id=old.lesson_id)
            count = ids.count()
            complete = bool(count and Progress.objects.using(db).filter(user_id=old.user_id, material__in=ids, completed_at__isnull=False).count() == count)
            LessonProgress.objects.using(db).filter(pk=old.pk).update(completed=complete, completed_at=(old.completed_at or timezone.now()) if complete else None)


class Migration(migrations.Migration):
    dependencies = [('learning', '0001_initial'), ('studio', '0001_initial')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
