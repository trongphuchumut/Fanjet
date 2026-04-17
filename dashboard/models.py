from django.db import models
from django.utils import timezone


class MQTTConfig(models.Model):
    broker_host  = models.CharField('Địa chỉ Broker', max_length=255, default='localhost')
    broker_port  = models.PositiveIntegerField('Cổng', default=1883)
    username     = models.CharField('Tên đăng nhập', max_length=255, blank=True)
    password     = models.CharField('Mật khẩu', max_length=255, blank=True)
    client_id    = models.CharField('Client ID', max_length=255, default='fanjet-web-01')
    topic_prefix = models.CharField('Tiền tố Topic', max_length=255, default='fanjet/basement')
    qos          = models.PositiveSmallIntegerField('Mức QoS', default=1,
                     choices=[(0,'QoS 0'),(1,'QoS 1'),(2,'QoS 2')])
    keep_alive   = models.PositiveIntegerField('Keep Alive (giây)', default=60)
    use_tls      = models.BooleanField('Dùng TLS/SSL', default=False)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cấu hình MQTT'

    def __str__(self):
        return f'{self.broker_host}:{self.broker_port}'


class OllamaConfig(models.Model):
    host          = models.CharField('Địa chỉ Ollama', max_length=255,
                      default='http://localhost:11434')
    default_model = models.CharField('Model mặc định', max_length=100, default='llama3.2')
    system_prompt = models.TextField('System Prompt', default=(
        'Bạn là trợ lý AI của hệ thống quản lý quạt thông gió tầng hầm FanJet. '
        'Trả lời bằng tiếng Việt, ngắn gọn và chính xác. '
        'Khi được hỏi về quạt, hãy dựa vào dữ liệu thực tế được cung cấp.'
    ))

    class Meta:
        verbose_name = 'Cấu hình Ollama AI'

    def __str__(self):
        return f'{self.host} / {self.default_model}'


class FanUnit(models.Model):
    MODE_CHOICES = [('auto', 'Tự động (Auto)'), ('manual', 'Thủ công (Manual)')]

    # Identity
    unit_id  = models.CharField('Mã bộ quạt', max_length=20, unique=True)
    name     = models.CharField('Tên bộ quạt', max_length=100)
    location = models.CharField('Vị trí', max_length=200, blank=True)
    zone     = models.CharField('Khu vực', max_length=50, default='B1', help_text='Ví dụ: B1, B2, Tầng 1, Mái...')

    # MQTT (leave blank → auto-generate from prefix + unit_id)
    mqtt_topic_base = models.CharField('MQTT Topic Base', max_length=255, blank=True)

    # Control
    control_mode = models.CharField('Chế độ điều khiển', max_length=10,
                     choices=MODE_CHOICES, default='auto')
    manual_speed = models.IntegerField('Tốc độ thủ công (%)', default=0)  # 0 or 20-100

    # CO thresholds (configurable per unit)
    co_warn_ppm  = models.FloatField('Ngưỡng cảnh báo CO (ppm)', default=25.0)
    co_alarm_ppm = models.FloatField('Ngưỡng báo động CO (ppm)', default=50.0)

    # Cached latest telemetry (written by MQTT subscriber thread)
    last_co_ppm    = models.FloatField(null=True, blank=True)
    last_speed_pct = models.IntegerField(null=True, blank=True)
    last_tripped   = models.BooleanField(default=False)
    last_seen      = models.DateTimeField(null=True, blank=True)

    is_active  = models.BooleanField('Kích hoạt', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['zone', 'unit_id']
        verbose_name = 'Bộ quạt'
        verbose_name_plural = 'Danh sách bộ quạt'

    def __str__(self):
        return f'[{self.unit_id}] {self.name}'

    def get_topic_base(self):
        if self.mqtt_topic_base:
            return self.mqtt_topic_base
        try:
            cfg = MQTTConfig.objects.get(pk=1)
            return f'{cfg.topic_prefix}/{self.unit_id}'
        except Exception:
            return f'fanjet/basement/{self.unit_id}'

    def co_status(self):
        if self.last_co_ppm is None:
            return 'unknown'
        if self.last_co_ppm >= self.co_alarm_ppm:
            return 'alarm'
        if self.last_co_ppm >= self.co_warn_ppm:
            return 'warning'
        return 'normal'

    def is_online(self):
        if not self.last_seen:
            return False
        return (timezone.now() - self.last_seen).total_seconds() < 90


class COSpeedPoint(models.Model):
    """Một điểm trên biểu đồ tương quan CO → Tốc độ quạt"""
    fan_unit  = models.ForeignKey(FanUnit, on_delete=models.CASCADE,
                  related_name='co_speed_points')
    co_ppm    = models.FloatField('Nồng độ CO (ppm)')
    speed_pct = models.IntegerField('Tốc độ quạt (%)')   # 0 or 20-100
    order     = models.IntegerField('Thứ tự', default=0)

    class Meta:
        ordering = ['order', 'co_ppm']
        verbose_name = 'Điểm CO-Speed'

    def __str__(self):
        return f'{self.fan_unit.unit_id}: {self.co_ppm}ppm → {self.speed_pct}%'


class FanTelemetry(models.Model):
    """Dữ liệu telemetry nhận từ MQTT, lưu vào SQLite"""
    fan_unit   = models.ForeignKey(FanUnit, on_delete=models.CASCADE,
                   related_name='telemetry')
    timestamp  = models.DateTimeField(auto_now_add=True, db_index=True)
    co_ppm     = models.FloatField()
    speed_pct  = models.IntegerField()
    is_tripped = models.BooleanField(default=False)
    mode       = models.CharField(max_length=10, default='auto')

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['fan_unit', '-timestamp'])]
        verbose_name = 'Telemetry'

    def __str__(self):
        return f'{self.fan_unit.unit_id} @ {self.timestamp:%H:%M:%S}'
