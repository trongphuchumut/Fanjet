import json
import logging

import requests
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import FanUnitForm, MQTTConfigForm, OllamaConfigForm
from .models import COSpeedPoint, FanTelemetry, FanUnit, MQTTConfig, OllamaConfig
from .mqtt_service import publish_command, publish_free, get_mqtt_status, reconnect_mqtt, disconnect_mqtt
from accounts.decorators import role_required

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mqtt_cfg():
    cfg, _ = MQTTConfig.objects.get_or_create(pk=1)
    return cfg


def _ollama_cfg():
    cfg, _ = OllamaConfig.objects.get_or_create(pk=1)
    return cfg


def _unit_summary(unit):
    """Dict used for API responses and context."""
    online = unit.is_online()
    co     = unit.last_co_ppm
    status = unit.co_status()
    return {
        'unit_id':      unit.unit_id,
        'name':         unit.name,
        'zone':         unit.zone,
        'co_ppm':       co,
        'speed_pct':    unit.last_speed_pct,
        'is_tripped':   unit.last_tripped,
        'mode':         unit.control_mode,
        'manual_speed': unit.manual_speed,
        'online':       online,
        'co_status':    status,
        'co_warn_ppm':  unit.co_warn_ppm,
        'co_alarm_ppm': unit.co_alarm_ppm,
    }


# ═══ Page views ══════════════════════════════════════════════════════════════

@login_required(login_url='accounts:login')
def home_view(request):
    units = FanUnit.objects.filter(is_active=True)
    running = sum(1 for u in units if u.last_speed_pct and u.last_speed_pct > 0)
    faults  = sum(1 for u in units if u.last_tripped)
    return render(request, 'dashboard/home.html', {
        'page':        'home',
        'mqtt_config': _mqtt_cfg(),
        'units':       units,
        'running':     running,
        'faults':      faults,
        'total_fans':  units.count(),
    })


@login_required(login_url='accounts:login')
def units_view(request):
    units = FanUnit.objects.all()
    return render(request, 'dashboard/units_list.html', {
        'page':        'units',
        'mqtt_config': _mqtt_cfg(),
        'units':       units,
    })


@login_required(login_url='accounts:login')
@role_required(['Admin'])
def unit_add_view(request):
    form = FanUnitForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Đã thêm bộ quạt thành công!')
        return redirect('dashboard:units')
    return render(request, 'dashboard/unit_form.html', {
        'page': 'units', 'mqtt_config': _mqtt_cfg(),
        'form': form, 'action': 'add',
    })


@login_required(login_url='accounts:login')
@role_required(['Admin'])
def unit_edit_view(request, unit_id):
    unit = get_object_or_404(FanUnit, unit_id=unit_id)
    form = FanUnitForm(request.POST or None, instance=unit)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Đã cập nhật bộ quạt!')
        return redirect('dashboard:unit_detail', unit_id=unit_id)
    return render(request, 'dashboard/unit_form.html', {
        'page': 'units', 'mqtt_config': _mqtt_cfg(),
        'form': form, 'unit': unit, 'action': 'edit',
    })


@login_required(login_url='accounts:login')
def unit_detail_view(request, unit_id):
    unit   = get_object_or_404(FanUnit, unit_id=unit_id)
    points = unit.co_speed_points.order_by('co_ppm')
    recent = FanTelemetry.objects.filter(fan_unit=unit).order_by('-timestamp')[:60]
    return render(request, 'dashboard/unit_detail.html', {
        'page':           'units',
        'mqtt_config':    _mqtt_cfg(),
        'unit':           unit,
        'profile_points': points,
        'recent':         recent,
        'co_status':      unit.co_status(),
    })


@login_required(login_url='accounts:login')
@role_required(['Admin'])
@require_POST
def unit_delete_view(request, unit_id):
    unit = get_object_or_404(FanUnit, unit_id=unit_id)
    name = unit.name
    unit.delete()
    messages.success(request, f'Đã xóa bộ quạt {name}')
    return redirect('dashboard:units')


@login_required(login_url='accounts:login')
def monitor_view(request):
    return render(request, 'dashboard/monitor.html', {
        'page': 'monitor', 'mqtt_config': _mqtt_cfg(),
    })


@login_required(login_url='accounts:login')
def analytics_view(request):
    units = FanUnit.objects.filter(is_active=True)
    return render(request, 'dashboard/analytics.html', {
        'page': 'analytics', 'mqtt_config': _mqtt_cfg(), 'units': units,
    })


@login_required(login_url='accounts:login')
def chatbot_view(request):
    ollama = _ollama_cfg()
    models_list = []
    try:
        r = requests.get(f'{ollama.host}/api/tags', timeout=3)
        if r.ok:
            models_list = [m['name'] for m in r.json().get('models', [])]
    except Exception:
        pass
    return render(request, 'dashboard/chatbot.html', {
        'page':          'chatbot',
        'mqtt_config':   _mqtt_cfg(),
        'ollama':        ollama,
        'ollama_models': models_list,
    })


@login_required(login_url='accounts:login')
@role_required(['Admin'])
def settings_view(request):
    mqtt_cfg   = _mqtt_cfg()
    ollama_cfg = _ollama_cfg()
    mqtt_form   = MQTTConfigForm(None, instance=mqtt_cfg)
    ollama_form = OllamaConfigForm(None, instance=ollama_cfg)

    if request.method == 'POST':
        tab = request.POST.get('_tab', 'mqtt')
        if tab == 'mqtt':
            mqtt_form = MQTTConfigForm(request.POST, instance=mqtt_cfg)
            if mqtt_form.is_valid():
                mqtt_form.save()
                # Auto reconnect sau khi đổi config
                try:
                    reconnect_mqtt()
                    messages.success(request, 'Đã lưu cấu hình MQTT và kết nối lại!')
                except Exception as exc:
                    messages.warning(request, f'Đã lưu config nhưng lỗi reconnect: {exc}')
                return redirect('dashboard:settings')
        elif tab == 'ollama':
            ollama_form = OllamaConfigForm(request.POST, instance=ollama_cfg)
            if ollama_form.is_valid():
                ollama_form.save()
                messages.success(request, 'Đã lưu cấu hình Ollama AI!')
                return redirect('dashboard:settings')

    return render(request, 'dashboard/settings.html', {
        'page':        'settings',
        'mqtt_config': mqtt_cfg,
        'mqtt_form':   mqtt_form,
        'ollama_form': ollama_form,
        'units':       FanUnit.objects.all(),
    })


# ═══ JSON API views ═══════════════════════════════════════════════════════════

@login_required(login_url='accounts:login')
def api_telemetry(request):
    units = FanUnit.objects.filter(is_active=True)
    return JsonResponse({'units': [_unit_summary(u) for u in units]})


@login_required(login_url='accounts:login')
@role_required(['Admin', 'Operator'])
@require_POST
def api_command(request, unit_id):
    unit = get_object_or_404(FanUnit, unit_id=unit_id)
    try:
        data  = json.loads(request.body)
        mode  = data.get('mode', unit.control_mode)
        speed = int(data.get('speed', unit.manual_speed))

        FanUnit.objects.filter(pk=unit.pk).update(
            control_mode=mode, manual_speed=speed)

        cfg   = _mqtt_cfg()
        topic = f'{unit.get_topic_base()}/command'
        publish_command(cfg, topic, {'mode': mode, 'speed': speed})
        return JsonResponse({'ok': True, 'mode': mode, 'speed': speed})
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)


@login_required(login_url='accounts:login')
@role_required(['Admin'])
@require_POST
def api_profile_save(request, unit_id):
    unit = get_object_or_404(FanUnit, unit_id=unit_id)
    try:
        points = json.loads(request.body)   # [{co_ppm, speed_pct}, …]
        COSpeedPoint.objects.filter(fan_unit=unit).delete()
        for i, p in enumerate(points):
            COSpeedPoint.objects.create(
                fan_unit=unit,
                co_ppm=float(p['co_ppm']),
                speed_pct=int(p['speed_pct']),
                order=i,
            )
        # Publish profile to MQTT so fans can load it
        cfg     = _mqtt_cfg()
        topic   = f'{unit.get_topic_base()}/profile'
        payload = {'profile': [{'co': p['co_ppm'], 'speed': p['speed_pct']}
                                for p in points]}
        publish_command(cfg, topic, payload)
        return JsonResponse({'ok': True, 'count': len(points)})
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)


@login_required(login_url='accounts:login')
def api_history(request, unit_id):
    unit  = get_object_or_404(FanUnit, unit_id=unit_id)
    hours = int(request.GET.get('hours', 24))
    since = timezone.now() - timezone.timedelta(hours=hours)
    qs = FanTelemetry.objects.filter(
        fan_unit=unit, timestamp__gte=since
    ).order_by('timestamp').values('timestamp', 'co_ppm', 'speed_pct', 'is_tripped', 'mode')

    data = [{
        'ts':      r['timestamp'].isoformat(),
        'co':      r['co_ppm'],
        'speed':   r['speed_pct'],
        'tripped': r['is_tripped'],
        'mode':    r['mode'],
    } for r in qs]
    return JsonResponse({'data': data})


@login_required(login_url='accounts:login')
@require_POST
def api_chat(request):
    from django.http import StreamingHttpResponse
    try:
        body     = json.loads(request.body)
        model    = body.get('model', 'llama3.2')
        msgs_in  = body.get('messages', [])
        ollama   = _ollama_cfg()

        # Build advanced system context with 24h history
        units    = FanUnit.objects.filter(is_active=True)
        ctx      = []
        since_24h = timezone.now() - timezone.timedelta(hours=24)

        for u in units:
            co    = f'{u.last_co_ppm:.1f}ppm' if u.last_co_ppm is not None else 'N/A'
            spd   = f'{u.last_speed_pct}%'    if u.last_speed_pct is not None else 'N/A'
            trip  = 'CÓ LỖI (TRIP)' if u.last_tripped else 'OK bình thường'
            onl   = 'Online' if u.is_online() else 'Offline'
            
            # Simple 24h stats
            telemetry = FanTelemetry.objects.filter(fan_unit=u, timestamp__gte=since_24h)
            trips_24h = telemetry.filter(is_tripped=True).count()
            max_co_list = [t.co_ppm for t in telemetry if t.co_ppm is not None]
            max_co_24h = max(max_co_list) if max_co_list else 0.0

            ctx.append(
                f"- Quạt {u.name} (Mã: {u.unit_id}, Khu vực: {u.zone}):\n"
                f"  + Trạng thái hiện tại: CO={co}, Tốc độ={spd}, Tình trạng={trip}, Chế độ={u.control_mode.upper()}, Kết nối={onl}.\n"
                f"  + Thống kê 24h qua: CO cao nhất={max_co_24h:.1f}ppm, Số lần sự kiện lỗi={trips_24h}."
            )

        expert_prompt = (
            "Bạn là chuyên gia chẩn đoán AI của Hệ thống Quản trị Tòa nhà FanJet. "
            "Nhiệm vụ của bạn là phân tích dữ liệu, đánh giá độ an toàn, và đưa ra lời khuyên bảo trì hoặc điều khiển cho kỹ thuật viên. "
            "Hãy trả lời ngắn gọn, súc tích, chuyên nghiệp bằng tiếng Việt và dùng Markdown để trình bày. "
            "Nhấn mạnh vào các thông số bất thường (như lỗi TRIP hoặc CO cực cao).\n\n"
            "Dữ liệu thực tế và lịch sử 24h của hệ thống quạt hiện tại:\n"
            + ('\n'.join(ctx) if ctx else '(Chưa có bộ quạt nào)')
        )

        sys_msg = {'role': 'system', 'content': f"{ollama.system_prompt}\n\n{expert_prompt}"}
        
        r = requests.post(
            f'{ollama.host}/api/chat',
            json={
                'model':    model,
                'messages': [sys_msg] + msgs_in,
                'stream':   True,
            },
            timeout=10,
            stream=True
        )
        r.raise_for_status()

        def stream_generator():
            try:
                for line in r.iter_lines():
                    if line:
                        yield line.decode('utf-8') + '\n'
            except requests.exceptions.ChunkedEncodingError:
                pass

        return StreamingHttpResponse(stream_generator(), content_type='application/x-ndjson')

    except requests.exceptions.ConnectionError:
        return JsonResponse({'error': 'Không kết nối được cấu hình Ollama host. Hãy đảm bảo Ollama đang chạy.'}, status=503)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=500)


@login_required(login_url='accounts:login')
def api_ollama_models(request):
    ollama = _ollama_cfg()
    try:
        r = requests.get(f'{ollama.host}/api/tags', timeout=5)
        if r.ok:
            return JsonResponse({
                'ok':     True,
                'models': [m['name'] for m in r.json().get('models', [])],
            })
    except Exception as exc:
        return JsonResponse({'ok': False, 'models': [], 'error': str(exc)})
    return JsonResponse({'ok': False, 'models': []})


@login_required(login_url='accounts:login')
def api_mqtt_log(request):
    """Trả về các MQTT message gần đây (polling thay thế WebSocket)."""
    try:
        since_id = int(request.GET.get('since', 0))
    except (ValueError, TypeError):
        since_id = 0
    from .mqtt_service import get_recent_messages
    msgs = get_recent_messages(since_id)
    return JsonResponse({'ok': True, 'messages': msgs})


# ═══ MQTT Client API ═════════════════════════════════════════════════════════

@login_required(login_url='accounts:login')
def api_mqtt_status(request):
    """GET – Trạng thái MQTT client connection."""
    status = get_mqtt_status()
    return JsonResponse({'ok': True, **status})


@login_required(login_url='accounts:login')
@role_required(['Admin'])
@require_POST
def api_mqtt_reconnect(request):
    """POST – Reconnect MQTT client với config hiện tại."""
    try:
        reconnect_mqtt()
        return JsonResponse({'ok': True, 'message': 'Đang kết nối lại…'})
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)


@login_required(login_url='accounts:login')
@role_required(['Admin'])
@require_POST
def api_mqtt_disconnect(request):
    """POST – Ngắt kết nối MQTT client."""
    try:
        disconnect_mqtt()
        return JsonResponse({'ok': True, 'message': 'Đã ngắt kết nối.'})
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)


@login_required(login_url='accounts:login')
@role_required(['Admin', 'Operator'])
@require_POST
def api_mqtt_publish(request):
    """POST – Publish tự do đến bất kỳ topic nào.
    Body: {"topic": "...", "payload": "...", "qos": 1}
    """
    try:
        data = json.loads(request.body)
        topic = data.get('topic', '').strip()
        payload = data.get('payload', '').strip()
        qos = int(data.get('qos', 1))

        if not topic:
            return JsonResponse({'ok': False, 'error': 'Topic không được để trống'}, status=400)
        if not payload:
            return JsonResponse({'ok': False, 'error': 'Payload không được để trống'}, status=400)

        ok = publish_free(topic, payload, qos=qos)
        if ok:
            return JsonResponse({'ok': True, 'message': f'Đã publish đến {topic}'})
        else:
            return JsonResponse({'ok': False, 'error': 'Không thể publish. Kiểm tra kết nối MQTT.'}, status=500)
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)


# ═══════════════════════════════════════════════════
# PERFORMANCE MONITOR API
# ═══════════════════════════════════════════════════

@login_required
@role_required('Admin')
def api_perf_toggle(request):
    """POST: bật/tắt performance monitor in ra terminal."""
    from . import perf_monitor
    if request.method != 'POST':
        return JsonResponse({'error': 'POST only'}, status=405)

    data = json.loads(request.body) if request.body else {}
    interval = int(data.get('interval', 5))

    if perf_monitor.is_running():
        perf_monitor.stop()
        return JsonResponse({'ok': True, 'running': False, 'message': 'PerfMon đã tắt'})
    else:
        perf_monitor.start(interval=interval)
        return JsonResponse({'ok': True, 'running': True, 'message': f'PerfMon đã bật (interval={interval}s)'})


@login_required
@role_required('Admin')
def api_perf_status(request):
    """GET: lấy snapshot CPU/RAM hiện tại."""
    from . import perf_monitor
    return JsonResponse(perf_monitor.get_snapshot())
