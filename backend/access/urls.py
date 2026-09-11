from django.urls import path
from . import views
app_name = 'access'
urlpatterns = [
    path('verify/', views.verify, name='verify'),
    path('setup/', views.setup, name='setup'),
    path('security/', views.security, name='security'),
    path('reset/', views.reset_access, name='reset'),
    path('people/', views.people, name='people'),
    path('people/<int:user_id>/', views.person, name='person'),
    path('invitations/', views.invitations, name='invitations'),
    path('invitations/<int:invite_id>/revoke/', views.revoke_invite, name='revoke_invite'),
    path('audit/', views.audit_log, name='audit'),
    path('components/', views.components, name='components'),
]
