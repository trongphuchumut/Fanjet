from django.contrib import admin
from .models import MQTTConfig, OllamaConfig, FanUnit, COSpeedPoint, FanTelemetry, FanGroup


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


@admin.register(FanGroup)
class FanGroupAdmin(admin.ModelAdmin):
    list_display      = ('name', 'boost_per_trip_pct', 'max_speed_pct', 'is_active',
                         'unit_count', 'tripped_count')
    list_filter       = ('is_active',)
    filter_horizontal = ('units',)
    readonly_fields   = ('created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'is_active'),
        }),
        ('Cấu hình bù trip', {
            'fields': ('boost_per_trip_pct', 'max_speed_pct'),
            'description': (
                'Khi X quạt trong nhóm bị trip, các quạt còn lại (chế độ Auto) '
                'sẽ nhận lệnh tăng thêm X × Boost% công suất.'
            ),
        }),
        ('Danh sách quạt', {
            'fields': ('units',),
        }),
        ('Thông tin', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Số quạt')
    def unit_count(self, obj):
        return obj.units.count()

    @admin.display(description='Đang trip')
    def tripped_count(self, obj):
        return obj.units.filter(last_tripped=True).count()
