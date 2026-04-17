from django.apps import AppConfig


class MqttBrokerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mqtt_broker'
    verbose_name = 'MQTT Broker – Self Hosted'
