from django.contrib import admin
from .models import MQTTConfig, OllamaConfig, FanUnit, COSpeedPoint, FanTelemetry


@admin.register(MQTTConfig)
class MQTTConfigAdmin(admin.ModelAdmin):
    list_display = ('broker_host', 'broker_port', 'client_id', 'use_tls', 'updated_at')


@admin.register(OllamaConfig)
class OllamaConfigAdmin(admin.ModelAdmin):
    list_display = ('host', 'default_model')


class COSpeedPointInline(admin.TabularInline):
    model  = COSpeedPoint
    extra  = 1
    ordering = ('co_ppm',)


@admin.register(FanUnit)
class FanUnitAdmin(admin.ModelAdmin):
    list_display   = ('unit_id', 'name', 'zone', 'control_mode', 'last_co_ppm',
                      'last_speed_pct', 'last_tripped', 'is_active')
    list_filter    = ('zone', 'control_mode', 'is_active')
    search_fields  = ('unit_id', 'name', 'location')
    inlines        = [COSpeedPointInline]
    readonly_fields = ('last_co_ppm', 'last_speed_pct', 'last_tripped', 'last_seen', 'created_at')


@admin.register(FanTelemetry)
class FanTelemetryAdmin(admin.ModelAdmin):
    list_display  = ('fan_unit', 'timestamp', 'co_ppm', 'speed_pct', 'is_tripped', 'mode')
    list_filter   = ('fan_unit', 'is_tripped', 'mode')
    ordering      = ('-timestamp',)
