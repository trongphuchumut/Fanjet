import os
import django
import random
from django.utils import timezone
from datetime import timedelta

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from dashboard.models import FanUnit, FanTelemetry, COSpeedPoint

# Clear old
FanUnit.objects.all().delete()

# Create two fans
f1 = FanUnit.objects.create(
    unit_id='U01',
    name='Quạt hút chính hành lang B1',
    zone='B1',
    location='Khu A - Hành lang Bắc',
    control_mode='auto',
    co_warn_ppm=25.0,
    co_alarm_ppm=50.0,
)

f2 = FanUnit.objects.create(
    unit_id='U02',
    name='Quạt hút dự phòng',
    zone='B2',
    location='Khu B - Phòng máy',
    control_mode='manual',
    manual_speed=45,
    co_warn_ppm=30.0,
    co_alarm_ppm=60.0,
)

# Create CO-Speed points for F1
COSpeedPoint.objects.create(fan_unit=f1, co_ppm=0, speed_pct=0, order=0)
COSpeedPoint.objects.create(fan_unit=f1, co_ppm=20, speed_pct=30, order=1)
COSpeedPoint.objects.create(fan_unit=f1, co_ppm=40, speed_pct=60, order=2)
COSpeedPoint.objects.create(fan_unit=f1, co_ppm=60, speed_pct=100, order=3)

# Generate 24h telemetry data for F1 and F2
now = timezone.now()
data = []

for i in range(144):  # 144 * 10 mins = 24h
    ts = now - timedelta(minutes=i*10)
    
    # f1 gets some simulated random curve
    co1 = 15.0 + 10.0 * __import__('math').sin(i / 10.0) + random.uniform(-2, 2)
    spd1 = 30 + 10 * __import__('math').sin(i / 10.0)
    if co1 > 50: co1 = 51 # limit
    
    data.append(FanTelemetry(
        fan_unit=f1,
        co_ppm=co1,
        speed_pct=int(spd1),
        is_tripped=False,
        mode='auto',
    ))
    # mock ts (need to set it after bulk_create or do model.save())

for t in reversed(data): # Chronological
    t.save()
    t.timestamp = now - timedelta(minutes=(144-len(data))*10) # rough, actually let's just do individual saves
    
data = []
for i in range(144):
    ts = now - timedelta(minutes=i*10)
    # f2 flat manual
    data.append(FanTelemetry(
        fan_unit=f2,
        co_ppm=20 + random.uniform(-1,1),
        speed_pct=45,
        is_tripped=(i == 50), # one trip event
        mode='manual'
    ))

for idx, t in enumerate(reversed(data)):
    t.save()
    FanTelemetry.objects.filter(pk=t.pk).update(timestamp=now - timedelta(minutes=(144-idx)*10))

for idx, t in enumerate(FanTelemetry.objects.filter(fan_unit=f1).order_by('id')):
    FanTelemetry.objects.filter(pk=t.pk).update(timestamp=now - timedelta(minutes=(144-idx)*10))


# Update latest for cache
f1.last_co_ppm = 23.4
f1.last_speed_pct = 40
f1.last_seen = now
f1.save()

f2.last_co_ppm = 19.8
f2.last_speed_pct = 45
f2.last_seen = now
f2.save()

print("Mock data generated successfully!")
