from django.urls import path
from . import views
app_name = 'teaching'
urlpatterns = [
    path('teaching/',views.dashboard,name='groups'),
    path('teaching/groups/create/',views.create_group,name='create_group'),
    path('teaching/groups/<int:pk>/',views.group,name='group'),
    path('assignments/',views.assigned,name='assigned'),
    path('teaching/reports/',views.reports,name='reports'),
    path('teaching/reports/export/',views.export,name='export'),
    path('teaching/students/<int:pk>/',views.student,name='student'),
    path('teaching/blocks/<int:pk>/attempts/',views.attempts,name='attempts'),
    path('teaching/snapshots/',views.snapshots,name='snapshots'),
    path('teaching/snapshots/<int:pk>/',views.snapshot,name='snapshot'),
    path('teaching/rules/',views.rules,name='rules'),
]
