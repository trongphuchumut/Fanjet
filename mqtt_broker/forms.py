from django import forms
from .models import BrokerConfig, BrokerUser, BrokerACL


class BrokerConfigForm(forms.ModelForm):
    class Meta:
        model = BrokerConfig
        fields = [
            'mosquitto_dir', 'config_path', 'password_file', 'acl_file', 'log_file',
            'port', 'ws_port', 'tls_port',
            'enable_websocket', 'enable_tls', 'tls_cert_path', 'tls_key_path',
            'max_connections', 'allow_anonymous', 'enable_persistence',
        ]
        widgets = {
            'mosquitto_dir':  forms.TextInput(attrs={'placeholder': r'C:\Program Files\mosquitto'}),
            'config_path':    forms.TextInput(attrs={'placeholder': r'C:\Program Files\mosquitto\mosquitto.conf'}),
            'password_file':  forms.TextInput(attrs={'placeholder': r'C:\Program Files\mosquitto\passwd'}),
            'acl_file':       forms.TextInput(attrs={'placeholder': r'C:\Program Files\mosquitto\acl'}),
            'log_file':       forms.TextInput(attrs={'placeholder': r'C:\Program Files\mosquitto\log\mosquitto.log'}),
            'port':           forms.NumberInput(attrs={'min': 1, 'max': 65535}),
            'ws_port':        forms.NumberInput(attrs={'min': 1, 'max': 65535}),
            'tls_port':       forms.NumberInput(attrs={'min': 1, 'max': 65535}),
            'max_connections': forms.NumberInput(attrs={'min': 1, 'max': 10000}),
            'tls_cert_path':  forms.TextInput(attrs={'placeholder': r'C:\certs\cert.pem'}),
            'tls_key_path':   forms.TextInput(attrs={'placeholder': r'C:\certs\key.pem'}),
        }


class BrokerUserForm(forms.Form):
    """Form thêm/sửa user MQTT (password qua mosquitto_passwd, không lưu DB)."""
    username = forms.CharField(
        label='Tên đăng nhập MQTT',
        max_length=100,
        widget=forms.TextInput(attrs={'placeholder': 'esp32_device_01', 'autocomplete': 'off'})
    )
    password = forms.CharField(
        label='Mật khẩu',
        widget=forms.PasswordInput(attrs={'placeholder': '••••••••', 'autocomplete': 'new-password'}),
        min_length=4,
    )
    password_confirm = forms.CharField(
        label='Xác nhận mật khẩu',
        widget=forms.PasswordInput(attrs={'placeholder': '••••••••', 'autocomplete': 'new-password'}),
        min_length=4,
    )
    description = forms.CharField(
        label='Mô tả',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Thiết bị ESP32 tầng B1'})
    )

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get('password')
        pw2 = cleaned.get('password_confirm')
        if pw and pw2 and pw != pw2:
            raise forms.ValidationError('Mật khẩu không khớp!')
        return cleaned


class BrokerUserEditForm(forms.Form):
    """Form sửa user MQTT (password tuỳ chọn)."""
    password = forms.CharField(
        label='Mật khẩu mới (để trống = không đổi)',
        required=False,
        widget=forms.PasswordInput(attrs={'placeholder': '(để trống nếu không đổi)', 'autocomplete': 'new-password'}),
    )
    password_confirm = forms.CharField(
        label='Xác nhận mật khẩu mới',
        required=False,
        widget=forms.PasswordInput(attrs={'placeholder': '(để trống nếu không đổi)', 'autocomplete': 'new-password'}),
    )
    description = forms.CharField(
        label='Mô tả',
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Thiết bị ESP32 tầng B1'})
    )
    is_active = forms.BooleanField(label='Kích hoạt', required=False, initial=True)

    def clean(self):
        cleaned = super().clean()
        pw = cleaned.get('password')
        pw2 = cleaned.get('password_confirm')
        if pw and pw2 and pw != pw2:
            raise forms.ValidationError('Mật khẩu không khớp!')
        return cleaned


class BrokerACLForm(forms.ModelForm):
    class Meta:
        model = BrokerACL
        fields = ['user', 'topic_pattern', 'access_type', 'order']
        widgets = {
            'topic_pattern': forms.TextInput(attrs={'placeholder': 'fanjet/basement/#',
                                                     'style': "font-family:'JetBrains Mono',monospace"}),
            'order': forms.NumberInput(attrs={'min': 0, 'max': 999}),
        }
