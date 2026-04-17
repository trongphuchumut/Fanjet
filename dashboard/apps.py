from django.apps import AppConfig
import os


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'
    verbose_name = 'Dashboard – FanJet BMS'

    def ready(self):
        if os.environ.get('RUN_MAIN') == 'true' or not os.environ.get('DJANGO_SETTINGS_MODULE'):
            from .mqtt_service import start_mqtt_thread
            try:
                start_mqtt_thread()
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(f'MQTT startup error: {exc}')
