from django.db import migrations


def import_reviews(apps, schema_editor):
    alias = schema_editor.connection.alias
    Review = apps.get_model('learning','BlockReview')
    Event = apps.get_model('teaching','ReviewEvent')
    for review in Review.objects.using(alias).select_related('progress').iterator():
        if Event.objects.using(alias).filter(progress_id=review.progress_id,imported=True).exists():
            continue
        event = Event.objects.using(alias).create(progress_id=review.progress_id,reviewer_id=review.reviewer_id,
            before=review.progress.verdict,after=review.verdict,action=review.verdict,note=review.note,imported=True)
        Event.objects.using(alias).filter(pk=event.pk).update(created_at=review.updated_at)


class Migration(migrations.Migration):
    dependencies = [('teaching','0001_initial')]
    operations = [migrations.RunPython(import_reviews,migrations.RunPython.noop)]
