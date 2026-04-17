import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from .forms import BrokerACLForm, BrokerConfigForm, BrokerUserEditForm, BrokerUserForm
from .models import BrokerACL, BrokerConfig, BrokerLog, BrokerUser
from . import services

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _broker_cfg():
    cfg, _ = BrokerConfig.objects.get_or_create(pk=1)
    return cfg


def _mqtt_cfg():
    """Get dashboard MQTTConfig for sidebar status."""
    try:
        from dashboard.models import MQTTConfig
        cfg, _ = MQTTConfig.objects.get_or_create(pk=1)
        return cfg
    except Exception:
        return None


# ═══ Page Views (Admin only) ═════════════════════════════════════════════════

@login_required(login_url='accounts:login')
@role_required(['Admin'])
def broker_dashboard_view(request):
    """Trang tổng quan MQTT Broker."""
    cfg = _broker_cfg()
    status = services.get_broker_status(cfg)
    install_check = services.check_mosquitto_installed(cfg)
    conn_info = services.get_connection_count(cfg)
    recent_logs = services.read_broker_logs(cfg, lines_count=20)

    return render(request, 'mqtt_broker/broker_dashboard.html', {
        'page': 'broker',
        'mqtt_config': _mqtt_cfg(),
        'cfg': cfg,
        'status': status,
        'installed': install_check,
        'connections': conn_info,
        'recent_logs': recent_logs,
        'user_count': BrokerUser.objects.filter(is_active=True).count(),
        'acl_count': BrokerACL.objects.count(),
    })


@login_required(login_url='accounts:login')
@role_required(['Admin'])
def broker_config_view(request):
    """Cấu hình Mosquitto broker."""
    cfg = _broker_cfg()
    form = BrokerConfigForm(instance=cfg)

    if request.method == 'POST':
        form = BrokerConfigForm(request.POST, instance=cfg)
        if form.is_valid():
            form.save()
            # Sinh và ghi file config
            result = services.apply_config(cfg)
            if result['ok']:
                messages.success(request, 'Đã lưu và ghi cấu hình Mosquitto!')
            else:
                messages.warning(request, f'Đã lưu DB nhưng lỗi ghi file: {result["error"]}')
            return redirect('mqtt_broker:config')

    # Preview config
    preview = services.generate_mosquitto_conf(cfg)

    return render(request, 'mqtt_broker/broker_config.html', {
        'page': 'broker',
        'mqtt_config': _mqtt_cfg(),
        'cfg': cfg,
        'form': form,
        'config_preview': preview,
    })


@login_required(login_url='accounts:login')
@role_required(['Admin'])
def broker_users_view(request):
    """Quản lý user MQTT."""
    cfg = _broker_cfg()
    users = BrokerUser.objects.all()

    if request.method == 'POST':
        form = BrokerUserForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            desc = form.cleaned_data.get('description', '')

            # Kiểm tra trùng
            if BrokerUser.objects.filter(username=username).exists():
                messages.error(request, f'User "{username}" đã tồn tại!')
            else:
                # Thêm vào password file
                result = services.add_mqtt_user(cfg, username, password)
                if result['ok']:
                    BrokerUser.objects.create(username=username, description=desc)
                    services.update_acl_file(cfg)
                    messages.success(request, f'Đã thêm user MQTT: {username}')
                else:
                    messages.error(request, f'Lỗi: {result["error"]}')
            return redirect('mqtt_broker:users')
    else:
        form = BrokerUserForm()

    return render(request, 'mqtt_broker/broker_users.html', {
        'page': 'broker',
        'mqtt_config': _mqtt_cfg(),
        'users': users,
        'form': form,
    })


@login_required(login_url='accounts:login')
@role_required(['Admin'])
def broker_user_edit_view(request, user_id):
    """Sửa user MQTT."""
    cfg = _broker_cfg()
    user = get_object_or_404(BrokerUser, pk=user_id)

    if request.method == 'POST':
        form = BrokerUserEditForm(request.POST)
        if form.is_valid():
            password = form.cleaned_data.get('password')
            desc = form.cleaned_data.get('description', '')
            is_active = form.cleaned_data.get('is_active', True)

            user.description = desc
            user.is_active = is_active
            user.save()

            if password:
                services.add_mqtt_user(cfg, user.username, password)
                messages.success(request, f'Đã đổi mật khẩu user: {user.username}')
            else:
                messages.success(request, f'Đã cập nhật user: {user.username}')
            return redirect('mqtt_broker:users')
    else:
        form = BrokerUserEditForm(initial={
            'description': user.description,
            'is_active': user.is_active,
        })

    return render(request, 'mqtt_broker/broker_user_edit.html', {
        'page': 'broker',
        'mqtt_config': _mqtt_cfg(),
        'user': user,
        'form': form,
    })


@login_required(login_url='accounts:login')
@role_required(['Admin'])
@require_POST
def broker_user_delete_view(request, user_id):
    """Xóa user MQTT."""
    cfg = _broker_cfg()
    user = get_object_or_404(BrokerUser, pk=user_id)
    username = user.username
    services.remove_mqtt_user(cfg, username)
    user.delete()
    services.update_acl_file(cfg)
    messages.success(request, f'Đã xóa user MQTT: {username}')
    return redirect('mqtt_broker:users')


@login_required(login_url='accounts:login')
@role_required(['Admin'])
def broker_acl_view(request):
    """Quản lý ACL rules."""
    cfg = _broker_cfg()
    acl_rules = BrokerACL.objects.select_related('user').all()

    if request.method == 'POST':
        form = BrokerACLForm(request.POST)
        if form.is_valid():
            form.save()
            services.update_acl_file(cfg)
            messages.success(request, 'Đã thêm rule ACL!')
            return redirect('mqtt_broker:acl')
    else:
        form = BrokerACLForm()

    # Read current ACL file content
    acl_preview = ''
    try:
        import os
        if os.path.exists(cfg.acl_file):
            with open(cfg.acl_file, 'r', encoding='utf-8') as f:
                acl_preview = f.read()
    except Exception:
        pass

    return render(request, 'mqtt_broker/broker_acl.html', {
        'page': 'broker',
        'mqtt_config': _mqtt_cfg(),
        'acl_rules': acl_rules,
        'form': form,
        'acl_preview': acl_preview,
    })


@login_required(login_url='accounts:login')
@role_required(['Admin'])
@require_POST
def broker_acl_delete_view(request, acl_id):
    """Xóa ACL rule."""
    cfg = _broker_cfg()
    rule = get_object_or_404(BrokerACL, pk=acl_id)
    rule.delete()
    services.update_acl_file(cfg)
    messages.success(request, 'Đã xóa rule ACL!')
    return redirect('mqtt_broker:acl')


@login_required(login_url='accounts:login')
@role_required(['Admin'])
def broker_logs_view(request):
    """Xem logs broker."""
    cfg = _broker_cfg()
    lines_count = int(request.GET.get('lines', 100))
    log_entries = services.read_broker_logs(cfg, lines_count=lines_count)

    return render(request, 'mqtt_broker/broker_logs.html', {
        'page': 'broker',
        'mqtt_config': _mqtt_cfg(),
        'log_entries': log_entries,
        'lines_count': lines_count,
    })


# ═══ API Views ═══════════════════════════════════════════════════════════════

@login_required(login_url='accounts:login')
@role_required(['Admin'])
def api_broker_status(request):
    """JSON trạng thái broker."""
    cfg = _broker_cfg()
    status = services.get_broker_status(cfg)
    conn = services.get_connection_count(cfg)
    installed = services.check_mosquitto_installed(cfg)
    return JsonResponse({
        'status': status,
        'connections': conn,
        'installed': installed,
    })


@login_required(login_url='accounts:login')
@role_required(['Admin'])
@require_POST
def api_broker_start(request):
    """Khởi động broker."""
    cfg = _broker_cfg()
    result = services.start_broker(cfg)
    return JsonResponse(result)


@login_required(login_url='accounts:login')
@role_required(['Admin'])
@require_POST
def api_broker_stop(request):
    """Dừng broker."""
    cfg = _broker_cfg()
    result = services.stop_broker(cfg)
    return JsonResponse(result)


@login_required(login_url='accounts:login')
@role_required(['Admin'])
@require_POST
def api_broker_restart(request):
    """Restart broker."""
    cfg = _broker_cfg()
    result = services.restart_broker(cfg)
    return JsonResponse(result)


@login_required(login_url='accounts:login')
@role_required(['Admin'])
def api_broker_logs(request):
    """JSON logs gần nhất."""
    cfg = _broker_cfg()
    lines = int(request.GET.get('lines', 50))
    entries = services.read_broker_logs(cfg, lines_count=lines)
    return JsonResponse({'logs': entries})
