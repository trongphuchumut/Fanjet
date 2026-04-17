"""
Service layer – tương tác với Mosquitto broker trên Windows.
Quản lý process, config file, password file, ACL file.
"""
import logging
import os
import platform
import re
import subprocess
import time

logger = logging.getLogger(__name__)

# ── Process Management ───────────────────────────────────────────────────────

def _get_mosquitto_exe(cfg=None):
    """Trả về đường dẫn đến mosquitto.exe."""
    if cfg:
        return os.path.join(cfg.mosquitto_dir, 'mosquitto.exe')
    return r'C:\Program Files\mosquitto\mosquitto.exe'


def _get_passwd_exe(cfg=None):
    """Trả về đường dẫn đến mosquitto_passwd.exe."""
    if cfg:
        return os.path.join(cfg.mosquitto_dir, 'mosquitto_passwd.exe')
    return r'C:\Program Files\mosquitto\mosquitto_passwd.exe'


def get_broker_status(cfg=None):
    """
    Kiểm tra trạng thái Mosquitto broker.
    Returns dict: {running, pid, uptime_seconds, exe_path, error}
    """
    result = {
        'running': False,
        'pid': None,
        'uptime': None,
        'exe_path': _get_mosquitto_exe(cfg),
        'error': None,
        'platform': platform.system(),
    }

    try:
        if platform.system() == 'Windows':
            # Dùng tasklist để tìm mosquitto.exe
            out = subprocess.check_output(
                ['tasklist', '/FI', 'IMAGENAME eq mosquitto.exe', '/FO', 'CSV', '/NH'],
                text=True, stderr=subprocess.DEVNULL, timeout=5
            )
            if 'mosquitto.exe' in out.lower():
                result['running'] = True
                # Parse PID từ CSV: "mosquitto.exe","1234","Console","1","12,345 K"
                parts = out.strip().split(',')
                if len(parts) >= 2:
                    pid_str = parts[1].strip().strip('"')
                    try:
                        result['pid'] = int(pid_str)
                    except ValueError:
                        pass

                # Try to get uptime via WMIC
                try:
                    wmic_out = subprocess.check_output(
                        ['wmic', 'process', 'where', 'name="mosquitto.exe"',
                         'get', 'CreationDate', '/value'],
                        text=True, stderr=subprocess.DEVNULL, timeout=5
                    )
                    match = re.search(r'CreationDate=(\d{14})', wmic_out)
                    if match:
                        from datetime import datetime
                        created = datetime.strptime(match.group(1), '%Y%m%d%H%M%S')
                        delta = datetime.now() - created
                        result['uptime'] = int(delta.total_seconds())
                except Exception:
                    pass
        else:
            # Linux fallback
            out = subprocess.check_output(
                ['pgrep', '-x', 'mosquitto'], text=True, timeout=5
            )
            if out.strip():
                result['running'] = True
                result['pid'] = int(out.strip().split('\n')[0])

    except subprocess.CalledProcessError:
        result['running'] = False
    except Exception as exc:
        result['error'] = str(exc)

    return result


def start_broker(cfg=None):
    """Khởi động Mosquitto broker."""
    try:
        exe = _get_mosquitto_exe(cfg)
        conf = cfg.config_path if cfg else r'C:\Program Files\mosquitto\mosquitto.conf'

        if not os.path.exists(exe):
            return {'ok': False, 'error': f'Không tìm thấy {exe}. Hãy cài Mosquitto trước.'}

        if platform.system() == 'Windows':
            # Thử khởi động dưới dạng Windows Service trước
            try:
                subprocess.run(
                    ['net', 'start', 'mosquitto'],
                    capture_output=True, text=True, timeout=10
                )
                time.sleep(1)
                status = get_broker_status(cfg)
                if status['running']:
                    _log_event('info', 'Broker đã khởi động (Windows Service)')
                    return {'ok': True, 'method': 'service'}
            except Exception:
                pass

            # Fallback: chạy trực tiếp
            subprocess.Popen(
                [exe, '-c', conf, '-v'],
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                [exe, '-c', conf, '-d'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        time.sleep(2)
        status = get_broker_status(cfg)
        if status['running']:
            _log_event('info', 'Broker đã khởi động thành công')
            return {'ok': True, 'method': 'process'}
        else:
            return {'ok': False, 'error': 'Broker không khởi động được. Kiểm tra log.'}

    except Exception as exc:
        _log_event('error', f'Lỗi khởi động broker: {exc}')
        return {'ok': False, 'error': str(exc)}


def stop_broker(cfg=None):
    """Dừng Mosquitto broker."""
    try:
        if platform.system() == 'Windows':
            # Thử dừng Windows Service trước
            try:
                subprocess.run(
                    ['net', 'stop', 'mosquitto'],
                    capture_output=True, text=True, timeout=10
                )
                time.sleep(1)
                status = get_broker_status(cfg)
                if not status['running']:
                    _log_event('info', 'Broker đã dừng (Windows Service)')
                    return {'ok': True}
            except Exception:
                pass

            # Fallback: taskkill
            subprocess.run(
                ['taskkill', '/F', '/IM', 'mosquitto.exe'],
                capture_output=True, text=True, timeout=10
            )
        else:
            subprocess.run(
                ['pkill', '-x', 'mosquitto'],
                capture_output=True, text=True, timeout=10
            )

        time.sleep(1)
        _log_event('info', 'Broker đã dừng')
        return {'ok': True}

    except Exception as exc:
        _log_event('error', f'Lỗi dừng broker: {exc}')
        return {'ok': False, 'error': str(exc)}


def restart_broker(cfg=None):
    """Restart Mosquitto broker."""
    stop_result = stop_broker(cfg)
    time.sleep(1)
    start_result = start_broker(cfg)
    _log_event('info', 'Broker đã restart')
    return start_result


# ── Config Generation ────────────────────────────────────────────────────────

def generate_mosquitto_conf(cfg):
    """Sinh nội dung file mosquitto.conf từ BrokerConfig model."""
    lines = [
        '# ═══ MOSQUITTO CONFIG ═══',
        '# Auto-generated by FanJet BMS — DO NOT EDIT MANUALLY',
        f'# Updated: {cfg.updated_at}',
        '',
        '# ── General ──',
        f'listener {cfg.port}',
        f'max_connections {cfg.max_connections}',
        f'allow_anonymous {"true" if cfg.allow_anonymous else "false"}',
        '',
    ]

    if not cfg.allow_anonymous:
        lines += [
            '# ── Authentication ──',
            f'password_file {cfg.password_file}',
            '',
        ]

    lines += [
        '# ── ACL ──',
        f'acl_file {cfg.acl_file}',
        '',
    ]

    if cfg.enable_persistence:
        persist_dir = os.path.join(cfg.mosquitto_dir, 'data')
        lines += [
            '# ── Persistence ──',
            'persistence true',
            f'persistence_location {persist_dir}\\',
            '',
        ]

    if cfg.enable_websocket:
        lines += [
            '# ── WebSocket ──',
            f'listener {cfg.ws_port}',
            'protocol websockets',
            '',
        ]

    if cfg.enable_tls and cfg.tls_cert_path and cfg.tls_key_path:
        lines += [
            '# ── TLS ──',
            f'listener {cfg.tls_port}',
            f'certfile {cfg.tls_cert_path}',
            f'keyfile {cfg.tls_key_path}',
            '',
        ]

    lines += [
        '# ── Logging ──',
        f'log_dest file {cfg.log_file}',
        'log_type all',
        'log_timestamp true',
        'log_timestamp_format %Y-%m-%dT%H:%M:%S',
        '',
    ]

    return '\n'.join(lines)


def apply_config(cfg):
    """Ghi file mosquitto.conf và restart broker."""
    try:
        content = generate_mosquitto_conf(cfg)

        # Tạo thư mục nếu chưa có
        conf_dir = os.path.dirname(cfg.config_path)
        os.makedirs(conf_dir, exist_ok=True)

        # Tạo thư mục log
        log_dir = os.path.dirname(cfg.log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        # Tạo thư mục persistence data
        if cfg.enable_persistence:
            data_dir = os.path.join(cfg.mosquitto_dir, 'data')
            os.makedirs(data_dir, exist_ok=True)

        with open(cfg.config_path, 'w', encoding='utf-8') as f:
            f.write(content)

        _log_event('info', f'Đã ghi cấu hình → {cfg.config_path}')
        return {'ok': True, 'content': content}

    except Exception as exc:
        _log_event('error', f'Lỗi ghi config: {exc}')
        return {'ok': False, 'error': str(exc)}


# ── User Management (mosquitto_passwd) ───────────────────────────────────────

def add_mqtt_user(cfg, username, password):
    """Thêm hoặc cập nhật user MQTT qua mosquitto_passwd."""
    try:
        passwd_exe = _get_passwd_exe(cfg)
        passwd_file = cfg.password_file if cfg else r'C:\Program Files\mosquitto\passwd'

        if not os.path.exists(passwd_exe):
            return {'ok': False, 'error': f'Không tìm thấy {passwd_exe}'}

        # Tạo file nếu chưa tồn tại
        if not os.path.exists(passwd_file):
            os.makedirs(os.path.dirname(passwd_file), exist_ok=True)
            open(passwd_file, 'a').close()

        # mosquitto_passwd -b <file> <username> <password>
        result = subprocess.run(
            [passwd_exe, '-b', passwd_file, username, password],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            _log_event('info', f'Đã thêm/cập nhật user MQTT: {username}')
            return {'ok': True}
        else:
            return {'ok': False, 'error': result.stderr or 'Lỗi không xác định'}

    except Exception as exc:
        _log_event('error', f'Lỗi thêm user: {exc}')
        return {'ok': False, 'error': str(exc)}


def remove_mqtt_user(cfg, username):
    """Xóa user khỏi password file."""
    try:
        passwd_file = cfg.password_file if cfg else r'C:\Program Files\mosquitto\passwd'

        if not os.path.exists(passwd_file):
            return {'ok': True}

        # Đọc file, lọc bỏ dòng user
        with open(passwd_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        filtered = [line for line in lines if not line.startswith(f'{username}:')]

        with open(passwd_file, 'w', encoding='utf-8') as f:
            f.writelines(filtered)

        _log_event('info', f'Đã xóa user MQTT: {username}')
        return {'ok': True}

    except Exception as exc:
        _log_event('error', f'Lỗi xóa user: {exc}')
        return {'ok': False, 'error': str(exc)}


# ── ACL Management ───────────────────────────────────────────────────────────

def update_acl_file(cfg=None):
    """Ghi lại file ACL từ database."""
    try:
        from .models import BrokerACL, BrokerConfig
        if cfg is None:
            cfg, _ = BrokerConfig.objects.get_or_create(pk=1)

        acl_path = cfg.acl_file
        rules = BrokerACL.objects.select_related('user').all()

        lines = [
            '# ═══ MOSQUITTO ACL ═══',
            '# Auto-generated by FanJet BMS',
            '',
        ]

        # Group by user
        global_rules = [r for r in rules if r.user is None]
        user_rules = {}
        for r in rules:
            if r.user:
                user_rules.setdefault(r.user.username, []).append(r)

        # Global rules (pattern topic)
        if global_rules:
            lines.append('# ── Global rules (all users) ──')
            for r in global_rules:
                access = _acl_access_keyword(r.access_type)
                lines.append(f'pattern {access} {r.topic_pattern}')
            lines.append('')

        # Per-user rules
        for uname, urules in user_rules.items():
            lines.append(f'# ── User: {uname} ──')
            lines.append(f'user {uname}')
            for r in urules:
                access = _acl_access_keyword(r.access_type)
                lines.append(f'topic {access} {r.topic_pattern}')
            lines.append('')

        os.makedirs(os.path.dirname(acl_path), exist_ok=True)
        with open(acl_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        _log_event('info', f'Đã cập nhật ACL → {acl_path}')
        return {'ok': True}

    except Exception as exc:
        _log_event('error', f'Lỗi ghi ACL: {exc}')
        return {'ok': False, 'error': str(exc)}


def _acl_access_keyword(access_type):
    """Chuyển access type sang keyword Mosquitto."""
    mapping = {
        'read': 'read',
        'write': 'write',
        'readwrite': 'readwrite',
        'deny': 'deny',
    }
    return mapping.get(access_type, 'readwrite')


# ── Log Reading ──────────────────────────────────────────────────────────────

def read_broker_logs(cfg=None, lines_count=100):
    """Đọc log file Mosquitto, trả về list dicts."""
    try:
        from .models import BrokerConfig
        if cfg is None:
            cfg, _ = BrokerConfig.objects.get_or_create(pk=1)

        log_path = cfg.log_file
        if not os.path.exists(log_path):
            return []

        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()

        # Lấy N dòng cuối
        recent = all_lines[-lines_count:]
        result = []
        for line in recent:
            line = line.strip()
            if not line:
                continue
            level = 'info'
            if 'error' in line.lower() or 'Error' in line:
                level = 'error'
            elif 'warning' in line.lower() or 'Warning' in line:
                level = 'warning'
            elif 'debug' in line.lower():
                level = 'debug'
            result.append({
                'message': line,
                'level': level,
            })

        return result

    except Exception as exc:
        logger.error(f'Lỗi đọc log: {exc}')
        return [{'message': f'Lỗi đọc log: {exc}', 'level': 'error'}]


# ── Connection Count ─────────────────────────────────────────────────────────

def get_connection_count(cfg=None):
    """Lấy số connection hiện tại bằng cách subscribe $SYS topic."""
    try:
        import paho.mqtt.client as mqtt
        from .models import BrokerConfig
        if cfg is None:
            cfg, _ = BrokerConfig.objects.get_or_create(pk=1)

        result = {'count': 0, 'ok': False}

        def on_message(client, userdata, msg):
            try:
                result['count'] = int(msg.payload.decode())
                result['ok'] = True
            except Exception:
                pass
            client.disconnect()

        def on_connect(client, userdata, flags, rc, properties=None):
            if rc == 0:
                client.subscribe('$SYS/broker/clients/active')
            else:
                client.disconnect()

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='fanjet-sys-check')
        client.on_connect = on_connect
        client.on_message = on_message

        client.connect('127.0.0.1', cfg.port, keepalive=5)
        client.loop_start()
        time.sleep(2)
        client.loop_stop()

        return result

    except Exception:
        return {'count': 0, 'ok': False}


# ── Internal helpers ─────────────────────────────────────────────────────────

def _log_event(level, message, source='services'):
    """Ghi log vào database."""
    try:
        from .models import BrokerLog
        BrokerLog.objects.create(level=level, message=message, source=source)
    except Exception:
        logger.warning(f'[MQTT Broker] {level}: {message}')


def check_mosquitto_installed(cfg=None):
    """Kiểm tra Mosquitto đã cài chưa."""
    exe = _get_mosquitto_exe(cfg)
    passwd_exe = _get_passwd_exe(cfg)
    return {
        'installed': os.path.exists(exe),
        'exe_path': exe,
        'passwd_exe_exists': os.path.exists(passwd_exe),
        'passwd_exe_path': passwd_exe,
    }
