"""
MQTT Client Service – FanJet BMS
Quản lý kết nối MQTT client (subscriber + publisher).
Hoàn toàn tách biệt với việc host MQTT broker.

JSON format expected from fans:
  {"co": 35.2, "speed": 72, "tripped": false, "mode": "auto"}
"""
import json
import logging
import threading
import time
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

# ── Module-level state ───────────────────────────────────────────────────────

_mqtt_client = None          # paho client reference
_mqtt_thread = None          # background thread
_thread_lock = threading.Lock()
_stop_event = threading.Event()

# In-memory circular buffer – giữ 200 dòng MQTT gần nhất để API polling
_msg_log: deque = deque(maxlen=200)
_msg_log_lock = threading.Lock()

# Trạng thái connection realtime
_mqtt_state = {
    'status': 'disconnected',   # connected | disconnected | connecting | error
    'broker': '',               # host:port đang kết nối
    'error': '',                # thông báo lỗi nếu có
    'connected_at': None,       # thời điểm kết nối thành công
    'messages_received': 0,     # tổng message đã nhận
}
_state_lock = threading.Lock()

# Phát hiện version paho-mqtt
try:
    _PAHO_V2 = hasattr(mqtt, 'CallbackAPIVersion')
except Exception:
    _PAHO_V2 = False


# ── State helpers ────────────────────────────────────────────────────────────

def _set_state(**kwargs):
    with _state_lock:
        _mqtt_state.update(kwargs)


def get_mqtt_status() -> dict:
    """Trả về trạng thái MQTT client hiện tại."""
    with _state_lock:
        state = dict(_mqtt_state)
    # Tính uptime
    if state['connected_at']:
        delta = (datetime.now() - state['connected_at']).total_seconds()
        state['uptime_seconds'] = int(delta)
    else:
        state['uptime_seconds'] = 0
    # Format connected_at
    if state['connected_at']:
        state['connected_at'] = state['connected_at'].strftime('%H:%M:%S %d/%m')
    return state


# ── Message log ──────────────────────────────────────────────────────────────

def get_recent_messages(since_id: int = 0):
    """Trả list các message có id > since_id (dùng cho HTTP polling)."""
    with _msg_log_lock:
        return [m for m in _msg_log if m['id'] > since_id]


def _push_log(topic: str, payload: str, direction: str = 'sub'):
    with _msg_log_lock:
        msg_id = (_msg_log[-1]['id'] + 1) if _msg_log else 1
        _msg_log.append({
            'id':      msg_id,
            'time':    datetime.now().strftime('%H:%M:%S'),
            'topic':   topic,
            'payload': payload,
            'dir':     direction,
        })


# ── Callbacks ────────────────────────────────────────────────────────────────

def _on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        prefix = userdata['prefix']
        topic  = f'{prefix}/+/telemetry'
        client.subscribe(topic, qos=userdata['qos'])
        _set_state(
            status='connected',
            error='',
            connected_at=datetime.now(),
        )
        logger.info(f'[MQTT Client] Connected. Subscribed to {topic}')
    else:
        _set_state(status='error', error=f'Connect failed: rc={reason_code}')
        logger.error(f'[MQTT Client] Connect failed: rc={reason_code}')


def _on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    # Chỉ set disconnected nếu không phải do stop_event
    if not _stop_event.is_set():
        _set_state(status='disconnected', error=f'Disconnected: rc={reason_code}')
    logger.warning(f'[MQTT Client] Disconnected: rc={reason_code}')


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
            logger.debug(f'[MQTT Client] Unknown unit_id: {unit_id}')
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

        # Increment message counter
        with _state_lock:
            _mqtt_state['messages_received'] += 1

        logger.debug(f'[MQTT Client] {unit_id}: co={co_ppm} speed={speed_pct}% trip={is_tripped}')

    except Exception as exc:
        logger.error(f'[MQTT Client] on_message error: {exc}')
    finally:
        # Luôn ghi vào log buffer kể cả unit không tồn tại
        try:
            _push_log(msg.topic, msg.payload.decode('utf-8', errors='replace'), 'sub')
        except Exception:
            pass


# ── Public API ───────────────────────────────────────────────────────────────

def publish_command(cfg, topic: str, payload: dict) -> bool:
    """Publish a command message. Tương thích paho-mqtt v1 và v2."""
    global _mqtt_client
    try:
        msg = json.dumps(payload)
        # Thử dùng client đang kết nối sẵn
        if _mqtt_client and _mqtt_client.is_connected():
            _mqtt_client.publish(topic, msg, qos=cfg.qos)
            logger.info(f'[MQTT Client] Published to {topic}: {msg}')
            _push_log(topic, msg, 'pub')
            return True
        # Fallback: one-shot client (tương thích v1 lẫn v2)
        if _PAHO_V2:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                            client_id=cfg.client_id + '-pub')
        else:
            c = mqtt.Client(client_id=cfg.client_id + '-pub')
        if cfg.username:
            c.username_pw_set(cfg.username, cfg.password)
        c.connect(cfg.broker_host, cfg.broker_port, keepalive=10)
        c.publish(topic, msg, qos=cfg.qos)
        c.loop(timeout=1.0)   # flush
        c.disconnect()
        logger.info(f'[MQTT Client] One-shot published to {topic}: {msg}')
        _push_log(topic, msg, 'pub')
        return True
    except Exception as exc:
        logger.error(f'[MQTT Client] Publish error: {exc}')
        return False


def publish_free(topic: str, payload_str: str, qos: int = 1) -> bool:
    """Publish tự do đến bất kỳ topic nào (dùng cho Monitor)."""
    global _mqtt_client
    try:
        # Ưu tiên dùng client đang connected
        if _mqtt_client and _mqtt_client.is_connected():
            _mqtt_client.publish(topic, payload_str, qos=qos)
            logger.info(f'[MQTT Client] Free publish to {topic}')
            _push_log(topic, payload_str, 'pub')
            return True

        # Fallback: one-shot
        from .models import MQTTConfig
        cfg, _ = MQTTConfig.objects.get_or_create(pk=1)
        if _PAHO_V2:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                            client_id=cfg.client_id + '-fpub')
        else:
            c = mqtt.Client(client_id=cfg.client_id + '-fpub')
        if cfg.username:
            c.username_pw_set(cfg.username, cfg.password)
        c.connect(cfg.broker_host, cfg.broker_port, keepalive=10)
        c.publish(topic, payload_str, qos=qos)
        c.loop(timeout=1.0)
        c.disconnect()
        logger.info(f'[MQTT Client] One-shot free publish to {topic}')
        _push_log(topic, payload_str, 'pub')
        return True
    except Exception as exc:
        logger.error(f'[MQTT Client] Free publish error: {exc}')
        return False


# ── Connection management ────────────────────────────────────────────────────

def _run_subscriber(cfg):
    """Main subscriber loop – runs in background thread."""
    global _mqtt_client

    _set_state(
        status='connecting',
        broker=f'{cfg.broker_host}:{cfg.broker_port}',
        error='',
    )

    if _PAHO_V2:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=cfg.client_id)
    else:
        client = mqtt.Client(client_id=cfg.client_id)

    client.user_data_set({'prefix': cfg.topic_prefix, 'qos': cfg.qos})
    if cfg.username:
        client.username_pw_set(cfg.username, cfg.password)

    client.on_connect    = _on_connect
    client.on_disconnect = _on_disconnect
    client.on_message    = _on_message

    _mqtt_client = client

    while not _stop_event.is_set():
        try:
            _set_state(status='connecting')
            client.connect(cfg.broker_host, cfg.broker_port,
                           keepalive=cfg.keep_alive)
            client.loop_start()

            # Đợi cho đến khi stop_event được set
            while not _stop_event.is_set():
                _stop_event.wait(timeout=1.0)

            # Stop loop khi nhận stop signal
            client.loop_stop()
            try:
                client.disconnect()
            except Exception:
                pass
            break

        except Exception as exc:
            _set_state(status='error', error=str(exc))
            logger.warning(f'[MQTT Client] Connection error: {exc}. Retry in 10s…')
            # Đợi 10s hoặc cho đến khi stop_event
            if _stop_event.wait(timeout=10):
                break

    _set_state(status='disconnected', connected_at=None)
    logger.info('[MQTT Client] Subscriber thread stopped')


def start_mqtt_thread():
    """Called from DashboardConfig.ready() — starts background subscriber."""
    global _mqtt_thread

    def _bootstrap():
        time.sleep(3)   # wait for Django ORM to be ready
        try:
            from .models import MQTTConfig
            cfg, _ = MQTTConfig.objects.get_or_create(pk=1)

            # Kiểm tra auto_connect
            if not cfg.auto_connect:
                logger.info('[MQTT Client] auto_connect=False, skipping.')
                _set_state(status='disconnected', broker=f'{cfg.broker_host}:{cfg.broker_port}',
                           error='Auto-connect disabled')
                return

            _run_subscriber(cfg)
        except Exception as exc:
            _set_state(status='error', error=str(exc))
            logger.error(f'[MQTT Client] Background thread error: {exc}')

    with _thread_lock:
        _stop_event.clear()
        _mqtt_thread = threading.Thread(target=_bootstrap, daemon=True,
                                         name='mqtt-subscriber')
        _mqtt_thread.start()
    logger.info('[MQTT Client] Subscriber thread started')


def disconnect_mqtt():
    """Ngắt kết nối MQTT client."""
    global _mqtt_client, _mqtt_thread

    with _thread_lock:
        _stop_event.set()

        if _mqtt_client:
            try:
                _mqtt_client.disconnect()
            except Exception:
                pass

        if _mqtt_thread and _mqtt_thread.is_alive():
            _mqtt_thread.join(timeout=5)
            _mqtt_thread = None

        _mqtt_client = None

    _set_state(status='disconnected', error='', connected_at=None)
    logger.info('[MQTT Client] Disconnected by user')


def reconnect_mqtt():
    """Disconnect và connect lại với config mới từ DB."""
    disconnect_mqtt()
    time.sleep(0.5)
    start_mqtt_thread()
    logger.info('[MQTT Client] Reconnecting with new config…')
