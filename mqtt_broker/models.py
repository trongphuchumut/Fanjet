from django.db import models
from django.utils import timezone


class BrokerConfig(models.Model):
    """Singleton – cấu hình Mosquitto broker trên Windows."""
    # Paths
    mosquitto_dir   = models.CharField('Thư mục Mosquitto', max_length=500,
                        default=r'C:\Program Files\mosquitto')
    config_path     = models.CharField('File cấu hình', max_length=500,
                        default=r'C:\Program Files\mosquitto\mosquitto.conf')
    password_file   = models.CharField('File mật khẩu', max_length=500,
                        default=r'C:\Program Files\mosquitto\passwd')
    acl_file        = models.CharField('File ACL', max_length=500,
                        default=r'C:\Program Files\mosquitto\acl')
    log_file        = models.CharField('File Log', max_length=500,
                        default=r'C:\Program Files\mosquitto\log\mosquitto.log')

    # Ports
    port            = models.PositiveIntegerField('Cổng MQTT', default=1883)
    ws_port         = models.PositiveIntegerField('Cổng WebSocket', default=9001)
    tls_port        = models.PositiveIntegerField('Cổng TLS', default=8883)

    # Features
    enable_websocket = models.BooleanField('Bật WebSocket', default=True)
    enable_tls       = models.BooleanField('Bật TLS/SSL', default=False)
    tls_cert_path    = models.CharField('Đường dẫn Certificate', max_length=500, blank=True)
    tls_key_path     = models.CharField('Đường dẫn Private Key', max_length=500, blank=True)

    # Limits
    max_connections  = models.PositiveIntegerField('Số kết nối tối đa', default=100)
    allow_anonymous  = models.BooleanField('Cho phép ẩn danh', default=False)

    # Persistence
    enable_persistence = models.BooleanField('Bật lưu trữ (persistence)', default=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cấu hình Broker'

    def __str__(self):
        return f'Mosquitto @ :{self.port}'


class BrokerUser(models.Model):
    """User MQTT được quản lý qua mosquitto_passwd."""
    username    = models.CharField('Tên đăng nhập', max_length=100, unique=True)
    description = models.CharField('Mô tả', max_length=255, blank=True)
    is_active   = models.BooleanField('Kích hoạt', default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['username']
        verbose_name = 'User MQTT'
        verbose_name_plural = 'Users MQTT'

    def __str__(self):
        return self.username


class BrokerACL(models.Model):
    ACCESS_CHOICES = [
        ('read',      'Chỉ đọc (subscribe)'),
        ('write',     'Chỉ ghi (publish)'),
        ('readwrite', 'Đọc + Ghi'),
        ('deny',      'Từ chối'),
    ]
    user          = models.ForeignKey(BrokerUser, on_delete=models.CASCADE,
                      related_name='acl_rules', null=True, blank=True,
                      verbose_name='User', help_text='Để trống = áp dụng cho tất cả')
    topic_pattern = models.CharField('Topic Pattern', max_length=500,
                      help_text='Ví dụ: fanjet/basement/#')
    access_type   = models.CharField('Quyền truy cập', max_length=10,
                      choices=ACCESS_CHOICES, default='readwrite')
    order         = models.IntegerField('Thứ tự', default=0)

    class Meta:
        ordering = ['order', 'user__username']
        verbose_name = 'ACL Rule'

    def __str__(self):
        user_label = self.user.username if self.user else '(tất cả)'
        return f'{user_label} → {self.topic_pattern} [{self.access_type}]'


class BrokerLog(models.Model):
    LEVEL_CHOICES = [
        ('info',    'Info'),
        ('warning', 'Warning'),
        ('error',   'Error'),
        ('debug',   'Debug'),
    ]
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    level     = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='info')
    message   = models.TextField()
    source    = models.CharField(max_length=50, default='broker')

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Log Entry'

    def __str__(self):
        return f'[{self.level}] {self.timestamp:%H:%M:%S} – {self.message[:60]}'
