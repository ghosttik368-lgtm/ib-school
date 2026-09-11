from django.conf import settings
from django.db import models


class StudyGroup(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='teaching_groups')
    title = models.CharField(max_length=100)
    description = models.TextField(max_length=1000, blank=True)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['owner','title'], name='teach_owner_group_title')]
        ordering = ['title','id']


class GroupMember(models.Model):
    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='study_memberships')
    joined_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['group','user'], name='teach_unique_group_member')]


class Assignment(models.Model):
    group = models.ForeignKey(StudyGroup, on_delete=models.PROTECT, related_name='assignments')
    course = models.ForeignKey('courses.Course', on_delete=models.PROTECT)
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['group','course'], name='teach_unique_assignment')]


class AssignmentStudent(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='students')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    enrollment = models.ForeignKey('courses.Enrollment', on_delete=models.PROTECT)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['assignment','user'], name='teach_unique_assigned_user')]


class Notice(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    key = models.CharField(max_length=120)
    text = models.CharField(max_length=240)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user','key'], name='teach_unique_notice')]


class ReviewEvent(models.Model):
    progress = models.ForeignKey('learning.BlockProgress', on_delete=models.PROTECT, related_name='review_events')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    before = models.CharField(max_length=12)
    after = models.CharField(max_length=12)
    action = models.CharField(max_length=12)
    note = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    imported = models.BooleanField(default=False)
    class Meta:
        ordering = ['-created_at','-id']

    @property
    def before_label(self):
        return {'positive':'Положительная','negative':'Отрицательная','unknown':'Нет данных'}.get(self.before,self.before)

    @property
    def after_label(self):
        return {'positive':'Положительная','negative':'Отрицательная','unknown':'Нет данных'}.get(self.after,self.after)


class ReportSnapshot(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=120)
    filters = models.JSONField(default=dict)
    rows = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at','-id']
