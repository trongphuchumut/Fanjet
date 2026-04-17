import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

try:
    from django.template.defaulttags import load
    from django.template.loader import get_template
    from django.template import engines
    
    env = engines['django'].engine
    template = env.get_template('dashboard/base.html')
    print("SUCCESS compiling base.html!")
except Exception as e:
    import traceback
    traceback.print_exc()
