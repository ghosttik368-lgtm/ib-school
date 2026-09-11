from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        (
            "courses",
            "0002_question_alter_lesson_options_alter_course_cover_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="course",
            name="is_listed",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="material",
            name="required",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="material",
            name="rich_text",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="question",
            name="accepted_answers",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="question",
            name="case_sensitive",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="question",
            name="explanation",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="question",
            name="kind",
            field=models.CharField(
                choices=[
                    ("single", "Один ответ"),
                    ("multiple", "Несколько ответов"),
                    ("short", "Короткий ответ"),
                ],
                default="single",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="quiz",
            name="points",
            field=models.PositiveSmallIntegerField(default=5),
        ),
    ]