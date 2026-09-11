from django.contrib import admin

from .models import (
    AnswerChoice,
    ChatMessage,
    Course,
    Direction,
    Enrollment,
    Lesson,
    LessonProgress,
    Material,
    Module,
    Question,
    Quiz,
    QuizAttempt,
    ScoreAward,
    UserAchievement,
)


admin.site.register(Direction)
class ContentReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False

for model in [Course,Module,Lesson,Material,Quiz,Question,AnswerChoice]:
    admin.site.register(model,ContentReadOnlyAdmin)
admin.site.register(Enrollment)
admin.site.register(LessonProgress)
admin.site.register(QuizAttempt)
admin.site.register(ScoreAward)
admin.site.register(UserAchievement)
admin.site.register(ChatMessage)
