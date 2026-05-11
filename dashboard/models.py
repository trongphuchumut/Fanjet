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
    auto_connect = models.BooleanField('Tự kết nối khi khởi động', default=True,
                     help_text='Tự động kết nối MQTT client khi web server khởi động')
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cấu hình MQTT Client'

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

    # Connection timeout settings
    msg_interval_sec     = models.PositiveIntegerField(
        'Chu kỳ bản tin (giây)', default=30,
        help_text='Thời gian giữa 2 bản tin MQTT của quạt (giây). Dùng để đánh giá mất kết nối.'
    )
    disconnect_timeout_sec = models.PositiveIntegerField(
        'Timeout mất kết nối (giây)', default=90,
        help_text='Nếu không nhận được bản tin sau thời gian này → coi là mất kết nối.'
    )

    # Cached latest telemetry (written by MQTT subscriber thread)
    last_co_ppm    = models.FloatField(null=True, blank=True)
    last_speed_pct = models.IntegerField(null=True, blank=True)
    last_tripped   = models.BooleanField(default=False)
    last_seen      = models.DateTimeField(null=True, blank=True)

    # Gateway 4G signal (written by MQTT subscriber thread)
    last_rssi      = models.IntegerField('RSSI (dBm)', null=True, blank=True,
                       help_text='Cường độ tín hiệu 4G gateway (dBm)')
    last_carrier   = models.CharField('Nhà mạng', max_length=50, blank=True, default='')
    last_signal    = models.CharField('Chất lượng sóng', max_length=20, blank=True, default='',
                       help_text='excellent/good/fair/weak/critical/unknown')

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
        return (timezone.now() - self.last_seen).total_seconds() < self.disconnect_timeout_sec

    def seconds_since_seen(self):
        """Số giây kể từ bản tin cuối. None nếu chưa có bản tin."""
        if not self.last_seen:
            return None
        return int((timezone.now() - self.last_seen).total_seconds())

    def signal_label(self):
        """Nhãn chất lượng tín hiệu dựa theo RSSI."""
        if self.last_rssi is None:
            return 'unknown'
        r = self.last_rssi
        if r >= -70:   return 'excellent'
        if r >= -85:   return 'good'
        if r >= -95:   return 'fair'
        if r >= -105:  return 'weak'
        return 'critical'


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


class FanGroup(models.Model):
    """
    Nhóm quạt – khi X quạt trong nhóm bị trip, các quạt còn lại
    sẽ tự động tăng công suất thêm X × boost_per_trip_pct (mặc định 10%).
    """
    name        = models.CharField('Tên nhóm', max_length=100, unique=True)
    description = models.TextField('Mô tả', blank=True)
    units       = models.ManyToManyField(
        FanUnit, related_name='fan_groups', blank=True,
        verbose_name='Danh sách quạt',
        help_text='Chọn các quạt thuộc nhóm này.',
    )
    # Mỗi quạt trip → các quạt còn lại tăng thêm bao nhiêu %
    boost_per_trip_pct = models.PositiveIntegerField(
        'Boost mỗi lần trip (%)', default=10,
        help_text='Mỗi 1 quạt bị trip → quạt còn lại tăng thêm X% công suất. Mặc định 10%.',
    )
    # Giới hạn tốc độ tối đa khi boost (để tránh vượt quá 100%)
    max_speed_pct = models.PositiveIntegerField(
        'Tốc độ tối đa khi boost (%)', default=100,
        help_text='Giới hạn tốc độ tối đa khi áp dụng boost trip. Mặc định 100%.',
    )
    is_active   = models.BooleanField('Kích hoạt', default=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Nhóm quạt'
        verbose_name_plural = 'Danh sách nhóm quạt'

    def __str__(self):
        return self.name

    def get_trip_compensation(self):
        """
        Trả về dict {unit_id: target_speed_pct} cho tất cả quạt đang HOẠT ĐỘNG
        (không trip, is_active=True) trong nhóm, với tốc độ đã được bù trip.
        Nếu không cần bù → trả về dict rỗng.
        """
        if not self.is_active:
            return {}

        all_units = list(self.units.filter(is_active=True))
        if not all_units:
            return {}

        tripped_count = sum(1 for u in all_units if u.last_tripped)
        if tripped_count == 0:
            return {}

        boost = tripped_count * self.boost_per_trip_pct   # tổng % cần tăng

        result = {}
        for u in all_units:
            if u.last_tripped:
                continue   # quạt đang trip → không gửi lệnh
            if u.control_mode != 'auto':
                continue   # quạt manual → không can thiệp
            base_speed  = u.last_speed_pct or 0
            new_speed   = min(base_speed + boost, self.max_speed_pct)
            result[u.unit_id] = new_speed
        return result
