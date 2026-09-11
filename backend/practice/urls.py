from django.urls import path
from . import views
app_name='practice'
urlpatterns=[
    path('workspace/<int:pk>/save/',views.save_workspace,name='save'),
    path('practice/<int:pk>/submit/',views.submit,name='submit'),
    path('practice/<int:pk>/history/',views.history,name='history'),
    path('submissions/<uuid:pk>/source/',views.source,name='source'),
    path('submissions/<uuid:pk>/cancel/',views.cancel,name='cancel'),
    path('continue/<int:pk>/',views.resume,name='resume'),
]
