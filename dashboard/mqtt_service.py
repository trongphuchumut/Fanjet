"""
MQTT background subscriber thread.
JSON format expected from fans:
  {"co": 35.2, "speed": 72, "tripped": false, "mode": "auto"}
"""
import json
import logging
import os
import threading

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)
_mqtt_client = None          # module-level reference for publish


# ── Callbacks ────────────────────────────────────────────────────────────────

def _on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        prefix = userdata['prefix']
        topic  = f'{prefix}/+/telemetry'
        client.subscribe(topic, qos=userdata['qos'])
        logger.info(f'[MQTT] Connected. Subscribed to {topic}')
    else:
        logger.error(f'[MQTT] Connect failed: rc={reason_code}')


def _on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    logger.warning(f'[MQTT] Disconnected: rc={reason_code}')


def _on_message(client, userdata, msg):
    try:
        # Topic pattern: <prefix>/<unit_id>/telemetry
        parts   = msg.topic.split('/')
        unit_id = parts[-2]
        payload = json.loads(msg.payload.decode('utf-8'))

        co_ppm     = float(payload.get('co', 0))
        speed_pct  = int(payload.get('speed', 0))
        is_tripped = bool(payload.get('tripped', False))
        mode       = str(payload.get('mode', 'auto'))

        # Lazy imports to avoid circular import at module load time
        from django.utils import timezone
        from .models import FanUnit, FanTelemetry

        try:
            unit = FanUnit.objects.get(unit_id=unit_id, is_active=True)
        except FanUnit.DoesNotExist:
            logger.debug(f'[MQTT] Unknown unit_id: {unit_id}')
            return

        # Save to history
        FanTelemetry.objects.create(
            fan_unit=unit,
            co_ppm=co_ppm,
            speed_pct=speed_pct,
            is_tripped=is_tripped,
            mode=mode,
        )

        # Update cached "last" fields
        FanUnit.objects.filter(pk=unit.pk).update(
            last_co_ppm=co_ppm,
            last_speed_pct=speed_pct,
            last_tripped=is_tripped,
            last_seen=timezone.now(),
        )

        logger.debug(f'[MQTT] {unit_id}: co={co_ppm} speed={speed_pct}% trip={is_tripped}')

    except Exception as exc:
        logger.error(f'[MQTT] on_message error: {exc}')


# ── Public API ───────────────────────────────────────────────────────────────

def publish_command(cfg, topic: str, payload: dict) -> bool:
    """Publish a command message.  Creates a one-shot client if subscriber not available."""
    global _mqtt_client
    try:
        msg = json.dumps(payload)
        if _mqtt_client and _mqtt_client.is_connected():
            _mqtt_client.publish(topic, msg, qos=cfg.qos)
            logger.info(f'[MQTT] Published to {topic}: {msg}')
            return True
        # Fall back: one-shot client
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id=cfg.client_id + '-pub')
        if cfg.username:
            c.username_pw_set(cfg.username, cfg.password)
        c.connect(cfg.broker_host, cfg.broker_port, keepalive=10)
        c.publish(topic, msg, qos=cfg.qos)
        c.disconnect()
        logger.info(f'[MQTT] One-shot published to {topic}: {msg}')
        return True
    except Exception as exc:
        logger.error(f'[MQTT] Publish error: {exc}')
        return False


def _run_subscriber(cfg):
    global _mqtt_client
    import time

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=cfg.client_id,
    )
    client.user_data_set({'prefix': cfg.topic_prefix, 'qos': cfg.qos})
    if cfg.username:
        client.username_pw_set(cfg.username, cfg.password)

    client.on_connect    = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message    = _on_message

    _mqtt_client = client

    while True:
        try:
            client.connect(cfg.broker_host, cfg.broker_port,
                           keepalive=cfg.keep_alive)
            client.loop_forever()
        except Exception as exc:
            logger.warning(f'[MQTT] Reconnecting in 10s… ({exc})')
            time.sleep(10)


def start_mqtt_thread():
    """Called from DashboardConfig.ready() — starts background subscriber."""
    import time

    def _bootstrap():
        time.sleep(3)   # wait for Django ORM to be ready
        try:
            from .models import MQTTConfig
            cfg, _ = MQTTConfig.objects.get_or_create(pk=1)
            _run_subscriber(cfg)
        except Exception as exc:
            logger.error(f'[MQTT] Background thread error: {exc}')

    t = threading.Thread(target=_bootstrap, daemon=True, name='mqtt-subscriber')
    t.start()
    logger.info('[MQTT] Subscriber thread started')
