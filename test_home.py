import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from dashboard.views import home_view

user = User.objects.get(username='admin')
req = RequestFactory().get('/dashboard/')
req.user = user

try:
    resp = home_view(req)
    print("STATUS:", resp.status_code)
except Exception as e:
    import traceback
    traceback.print_exc()
