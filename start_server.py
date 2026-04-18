"""
Production server - FanJet BMS
Chạy bằng: python start_server.py (Yêu cầu Run as Administrator)
"""
import os
import sys
import subprocess
import ctypes

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

from waitress import serve
from core.wsgi import application

HOST = '0.0.0.0'
PORT = 8080

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def start_mqtt():
    print("Khởi động MQTT Broker (Mosquitto)...")
    try:
        subprocess.run(["powershell", "-Command", "Start-Service -Name 'mosquitto'"], check=True, capture_output=True)
        print("✅ Đã bật MQTT Broker!")
    except subprocess.CalledProcessError as e:
        print("❌ Không thể bật MQTT Broker. Hãy chắc chắn bạn đang chạy bằng quyền Administrator!")

def stop_mqtt():
    print("Tắt MQTT Broker (Mosquitto)...")
    try:
        subprocess.run(["powershell", "-Command", "Stop-Service -Name 'mosquitto' -Force"], check=True, capture_output=True)
        print("✅ Đã tắt MQTT Broker!")
    except subprocess.CalledProcessError as e:
        print("❌ Lỗi khi tắt MQTT Broker.")

if __name__ == "__main__":
    if not is_admin():
        print("⚠️ CẢNH BÁO: Bạn chưa chạy terminal bằng quyền Administrator!")
        print("MQTT Broker có thể sẽ không tự khởi động được.\n")

    start_mqtt()

    print(f"\n=== FanJet BMS Production Server ===")
    print(f"Listening on  : http://{HOST}:{PORT}")
    print(f"Domain        : http://fan-auto.cloud")
    print(f"Press Ctrl+C to stop.")
    print("=" * 40)

    try:
        serve(application, host=HOST, port=PORT, threads=8)
    except KeyboardInterrupt:
        print("\nĐang tắt server...")
    except Exception as e:
        print(f"\n❌ Lỗi Server: {e}")
        print("Có thể port 8080 đang bị sử dụng bởi một ứng dụng khác (hoặc server cũ chưa tắt hẳn).")
    finally:
        stop_mqtt()
        print("Đã tắt an toàn!")
