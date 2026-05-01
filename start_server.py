"""
Production server - FanJet BMS
Chạy bằng: python start_server.py
Chỉ khởi động Web Server (Django/Waitress).
MQTT Broker được quản lý riêng tại /broker/ trên giao diện web.
"""
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

from waitress import serve
from core.wsgi import application

HOST = '0.0.0.0'
PORT = 8080

if __name__ == "__main__":
    print(f"\n{'=' * 50}")
    print(f"  FanJet BMS – Web Server")
    print(f"{'=' * 50}")
    print(f"  Địa chỉ     : http://{HOST}:{PORT}")
    print(f"  Domain       : http://fan-auto.cloud")
    print(f"  MQTT Broker  : Quản lý tại /broker/")
    print(f"  MQTT Client  : Cấu hình tại /dashboard/settings/")
    print(f"{'=' * 50}")
    print(f"  Nhấn Ctrl+C để dừng.\n")

    try:
        serve(application, host=HOST, port=PORT, threads=8)
    except KeyboardInterrupt:
        print("\nĐang tắt server...")
    except Exception as e:
        print(f"\n❌ Lỗi Server: {e}")
        print("Có thể port 8080 đang bị sử dụng bởi ứng dụng khác.")
    finally:
        print("Đã tắt an toàn!")
