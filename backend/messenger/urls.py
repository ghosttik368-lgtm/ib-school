from django.urls import path
from . import views
app_name = 'messenger'
urlpatterns = [
    path('chat/', views.home, name='home'),
    path('chat/api/people/', views.people, name='people'),
    path('chat/api/rooms/', views.rooms, name='rooms'),
    path('chat/api/create/', views.create, name='create'),
    path('chat/api/rooms/<int:pk>/', views.history, name='history'),
    path('chat/api/rooms/<int:pk>/send/', views.send, name='send'),
    path('chat/api/rooms/<int:pk>/read/', views.read, name='read'),
    path('chat/api/rooms/<int:pk>/members/', views.members, name='members'),
    path('chat/api/messages/<int:pk>/edit/', views.edit, name='edit'),
    path('chat/files/<int:pk>/', views.file, name='file'),
    path('notifications/data/', views.notifications, name='notifications'),
    path('notifications/read/', views.notices_read, name='notices_read'),
]
