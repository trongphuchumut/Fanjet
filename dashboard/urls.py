from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    # ── Pages ────────────────────────────────────────────────────
    path('',                           views.home_view,        name='home'),
    path('units/',                     views.units_view,       name='units'),
    path('units/add/',                 views.unit_add_view,    name='unit_add'),
    path('units/<str:unit_id>/',       views.unit_detail_view, name='unit_detail'),
    path('units/<str:unit_id>/edit/',  views.unit_edit_view,   name='unit_edit'),
    path('units/<str:unit_id>/delete/',views.unit_delete_view, name='unit_delete'),
    path('monitor/',                   views.monitor_view,     name='monitor'),
    path('chatbot/',                   views.chatbot_view,     name='chatbot'),
    path('analytics/',                 views.analytics_view,   name='analytics'),
    path('settings/',                  views.settings_view,    name='settings'),

    # ── JSON API ─────────────────────────────────────────────────
    path('api/telemetry/',                         views.api_telemetry,      name='api_telemetry'),
    path('api/units/<str:unit_id>/command/',        views.api_command,        name='api_command'),
    path('api/units/<str:unit_id>/profile/',        views.api_profile_save,   name='api_profile'),
    path('api/units/<str:unit_id>/history/',        views.api_history,        name='api_history'),
    path('api/chat/',                              views.api_chat,           name='api_chat'),
    path('api/ollama/models/',                     views.api_ollama_models,  name='api_ollama_models'),
]
