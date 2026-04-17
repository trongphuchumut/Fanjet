from django.urls import path
from . import views

app_name = 'mqtt_broker'

urlpatterns = [
    # ── Pages ────────────────────────────────────────────────────
    path('',                          views.broker_dashboard_view,   name='dashboard'),
    path('config/',                   views.broker_config_view,      name='config'),
    path('users/',                    views.broker_users_view,       name='users'),
    path('users/<int:user_id>/edit/', views.broker_user_edit_view,   name='user_edit'),
    path('users/<int:user_id>/delete/', views.broker_user_delete_view, name='user_delete'),
    path('acl/',                      views.broker_acl_view,         name='acl'),
    path('acl/<int:acl_id>/delete/',  views.broker_acl_delete_view,  name='acl_delete'),
    path('logs/',                     views.broker_logs_view,        name='logs'),

    # ── API ──────────────────────────────────────────────────────
    path('api/status/',   views.api_broker_status,   name='api_status'),
    path('api/start/',    views.api_broker_start,     name='api_start'),
    path('api/stop/',     views.api_broker_stop,      name='api_stop'),
    path('api/restart/',  views.api_broker_restart,   name='api_restart'),
    path('api/logs/',     views.api_broker_logs,      name='api_logs'),
]
