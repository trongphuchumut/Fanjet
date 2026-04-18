"""
Production server - FanJet BMS
Chạy bằng: python start_server.py
"""
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

from waitress import serve
from core.wsgi import application

HOST = '0.0.0.0'
PORT = 8080

print(f"=== FanJet BMS Production Server ===")
print(f"Listening on  : http://{HOST}:{PORT}")
print(f"Domain        : http://fan-auto.cloud")
print(f"Press Ctrl+C to stop.")
print("=" * 40)

serve(application, host=HOST, port=PORT, threads=8)
