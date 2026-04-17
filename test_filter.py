import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

import accounts.templatetags.auth_extras as mytags
print("Available filters in mytags:", mytags.register.filters.keys())
