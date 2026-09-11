from django.db import migrations

def preserve_rewards(apps,schema_editor):
    Quiz=apps.get_model('courses','Quiz')
    for quiz in Quiz.objects.select_related('material__lesson__module__course').all().iterator():
        quiz.points=quiz.material.lesson.module.course.points_per_test
        quiz.save(update_fields=['points'])

class Migration(migrations.Migration):
    dependencies=[('courses','0002_course_is_listed_material_required_and_more')]
    operations=[migrations.RunPython(preserve_rewards,migrations.RunPython.noop)]
