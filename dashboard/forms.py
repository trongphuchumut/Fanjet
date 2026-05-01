from django import forms
from .models import MQTTConfig, OllamaConfig, FanUnit


class MQTTConfigForm(forms.ModelForm):
    password = forms.CharField(
        label='Mật khẩu broker', required=False,
        widget=forms.PasswordInput(render_value=True,
            attrs={'placeholder': '(để trống nếu không xác thực)',
                   'autocomplete': 'new-password'})
    )

    class Meta:
        model  = MQTTConfig
        fields = ['broker_host', 'broker_port', 'username', 'password',
                  'client_id', 'topic_prefix', 'qos', 'keep_alive', 'use_tls',
                  'auto_connect']
        widgets = {
            'broker_host':   forms.TextInput(attrs={'placeholder': '192.168.1.100'}),
            'broker_port':   forms.NumberInput(attrs={'min': 1, 'max': 65535}),
            'username':      forms.TextInput(attrs={'placeholder': '(để trống nếu không có)'}),
            'client_id':     forms.TextInput(attrs={'placeholder': 'fanjet-web-01'}),
            'topic_prefix':  forms.TextInput(attrs={'placeholder': 'fanjet/basement'}),
            'keep_alive':    forms.NumberInput(attrs={'min': 10, 'max': 3600, 'step': 10}),
        }


class OllamaConfigForm(forms.ModelForm):
    class Meta:
        model  = OllamaConfig
        fields = ['host', 'default_model', 'system_prompt']
        widgets = {
            'host':           forms.TextInput(attrs={'placeholder': 'http://localhost:11434'}),
            'default_model':  forms.TextInput(attrs={'placeholder': 'llama3.2'}),
            'system_prompt':  forms.Textarea(attrs={'rows': 4}),
        }


class FanUnitForm(forms.ModelForm):
    class Meta:
        model  = FanUnit
        fields = ['unit_id', 'name', 'location', 'zone',
                  'mqtt_topic_base', 'co_warn_ppm', 'co_alarm_ppm']
        widgets = {
            'unit_id':         forms.TextInput(attrs={'placeholder': 'U01'}),
            'name':            forms.TextInput(attrs={'placeholder': 'Bộ quạt 01'}),
            'location':        forms.TextInput(attrs={'placeholder': 'Khu A – Hành lang Bắc'}),
            'zone':            forms.TextInput(attrs={'placeholder': 'B1, Tầng trệt, Khu A...'}),
            'mqtt_topic_base': forms.TextInput(attrs={'placeholder': 'Để trống → tự sinh từ prefix + unit_id'}),
            'co_warn_ppm':     forms.NumberInput(attrs={'step': '0.5', 'min': '0'}),
            'co_alarm_ppm':    forms.NumberInput(attrs={'step': '0.5', 'min': '0'}),
        }
