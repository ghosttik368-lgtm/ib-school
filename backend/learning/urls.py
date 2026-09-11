from django.urls import path
from . import views

app_name = 'learning'
urlpatterns = [
    path('blocks/<int:pk>/', views.block, name='block'),
    path('blocks/<int:pk>/open/', views.start, name='start'),
    path('blocks/<int:pk>/complete/', views.complete, name='complete'),
    path('rating/data/', views.public_data, name='public_data'),
    path('rating/students/<int:pk>/', views.public_student, name='public_student'),
    path('analytics/', views.analytics, name='analytics'),
    path('analytics/data/', views.private_data, name='private_data'),
    path('analytics/students/<int:pk>/', views.private_student, name='private_student'),
    path('analytics/blocks/<int:pk>/review/', views.review, name='review'),
]
