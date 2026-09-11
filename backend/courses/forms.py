from django import forms

from .models import ChatMessage, Course, Lesson, Material


class StyledFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            current = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{current} form-control".strip()


class CourseWizardForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Course
        fields = (
            "direction",
            "level",
            "title",
            "short_description",
            "description",
            "points_per_test",
            "cover",
        )
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Например, Основы C++"}),
            "short_description": forms.TextInput(
                attrs={"placeholder": "Одно понятное предложение о курсе"}
            ),
            "description": forms.Textarea(
                attrs={"rows": 5, "placeholder": "Чему научится студент"}
            ),
            "points_per_test": forms.NumberInput(attrs={"min": 1, "max": 100}),
            "cover": forms.ClearableFileInput(
                attrs={"accept": "image/png,image/jpeg,image/webp"}
            ),
        }


class CourseEditForm(CourseWizardForm):
    pass


class LessonEditForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ("title", "summary", "duration_minutes", "is_active")
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Название урока"}),
            "summary": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Коротко: что будет в уроке"}
            ),
            "duration_minutes": forms.NumberInput(attrs={"min": 1, "max": 600}),
        }


class MaterialForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Material
        fields = ("kind", "title", "text", "file", "external_url")
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Название материала"}),
            "text": forms.Textarea(
                attrs={"rows": 10, "placeholder": "Введите текст статьи"}
            ),
            "file": forms.ClearableFileInput(
                attrs={
                    "accept": ".mp4,.webm,.mov,.mkv,.pdf,.ppt,.pptx,.doc,.docx,.txt,.zip"
                }
            ),
            "external_url": forms.URLInput(
                attrs={"placeholder": "https://example.com/material"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [
            choice
            for choice in Material.Kind.choices
            if choice[0] != Material.Kind.CODE
        ]


class QuestionCreateForm(StyledFormMixin, forms.Form):
    text = forms.CharField(
        label="Вопрос",
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Введите вопрос"}),
    )
    answer_1 = forms.CharField(label="Ответ 1", max_length=500)
    answer_2 = forms.CharField(label="Ответ 2", max_length=500)
    answer_3 = forms.CharField(label="Ответ 3", max_length=500)
    answer_4 = forms.CharField(label="Ответ 4", max_length=500)
    correct_answer = forms.TypedChoiceField(
        label="Правильный ответ",
        choices=((1, "Ответ 1"), (2, "Ответ 2"), (3, "Ответ 3"), (4, "Ответ 4")),
        coerce=int,
    )


class ChatMessageForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ChatMessage
        fields = ("text",)
        widgets = {
            "text": forms.Textarea(
                attrs={"rows": 2, "placeholder": "Напишите сообщение…", "maxlength": 2000}
            )
        }
