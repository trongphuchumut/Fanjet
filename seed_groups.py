import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import Group

groups = ['Admin', 'Operator', 'Viewer']
for g in groups:
    group, created = Group.objects.get_or_create(name=g)
    if created:
        print(f"Created group: {g}")
    else:
        print(f"Group {g} already exists.")

print("Finish seeding RBAC groups.")
