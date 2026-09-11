from django.urls import path
from . import views
app_name='studio'
urlpatterns=[path('create/',views.create,name='create'),path('<int:pk>/',views.editor,name='editor'),path('<int:pk>/data/',views.save,name='data'),path('<int:pk>/validate/',views.validate,name='validate'),path('<int:pk>/publish/',views.publish_course,name='publish'),path('<int:pk>/archive/',views.archive,name='archive'),path('<int:pk>/upload/',views.upload,name='upload'),path('<int:pk>/preview/',views.preview,name='preview'),path('assets/<int:pk>/',views.asset_file,name='asset')]
