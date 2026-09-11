from django.urls import path
from . import views

app_name = 'autoquiz'
urlpatterns = [
    path('draft/<int:draft_id>/', views.listing, name='list'),
    path('draft/<int:draft_id>/queue/', views.queue, name='queue'),
    path('jobs/<uuid:pk>/', views.review, name='review'),
    path('jobs/<uuid:pk>/status/', views.status, name='status'),
    path('jobs/<uuid:pk>/save/', views.save, name='save'),
    path('jobs/<uuid:pk>/control/', views.control, name='control'),
    path('jobs/<uuid:pk>/apply/', views.apply, name='apply'),
    path('jobs/<uuid:pk>/transcript/', views.transcript, name='transcript'),
    path('replay/<int:question_id>/', views.replay, name='replay'),
]
