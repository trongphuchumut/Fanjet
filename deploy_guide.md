# Hướng dẫn Deploy FanJet BMS & MQTT trên Windows

Tài liệu này hướng dẫn bạn cách thiết lập laptop/PC Windows làm máy chủ (Server) cho Web Dashboard và MQTT Broker tự hosting.

## 1. Cài đặt Python & Django Web

1. **Cài Python 3.10+** (nhớ check ô *Add Python to PATH* khi cài đặt).
2. Tải mã nguồn `fanjet` về máy `D:\fanjet`.
3. Mở Terminal (Command Prompt / PowerShell) với quyền Administrator.
4. Tạo và kích hoạt môi trường ảo (Virtual Environment):
   ```cmd
   cd D:\fanjet
   python -m venv venv
   call venv\Scripts\activate
   ```
5. Cài đặt thư viện:
   ```cmd
   pip install django paho-mqtt
   ```

## 2. Cài đặt Mosquitto MQTT Broker

Vì bạn chạy MQTT trên chính laptop của mình, bạn cần cài đặt Eclipse Mosquitto cho Windows.

1. Tải **Mosquitto for Windows** (bản 64-bit `.exe`) từ [mosquitto.org/download](https://mosquitto.org/download/).
2. Chạy file cài đặt.
3. Khi được hỏi thành phần cài đặt, hãy để mặc định (phải có `mosquitto` và mục `Service`).
4. **Quan trọng:** Ghi nhớ đường dẫn cài đặt. Mặc định sẽ là:
   `C:\Program Files\mosquitto`
5. Sau khi cài xong, Mosquitto sẽ tự động cài thêm một Windows Service tên là `Mosquitto Broker`. Hệ thống FanJet BMS sẽ tự động tương tác với service này để quản lý (khởi động/dừng/restart).

## 3. Quản lý MQTT từ Web Dashboard

1. Mở Django server:
   ```cmd
   call venv\Scripts\activate
   python manage.py runserver 0.0.0.0:8000
   ```
2. Mở trình duyệt vào `http://localhost:8000` và đăng nhập bằng tài khoản **Admin**.
3. Ở menu bên trái, tìm mục **Hệ thống > MQTT Broker**.
4. Vào phần **Cấu hình** và nhấn "Lưu & Ghi cấu hình". Quá trình này sẽ tự động sinh file cấu hình `mosquitto.conf` tại thư mục cài đặt Mosquitto.
5. Ứng dụng FanJet sẽ tự động gọi lệnh để khởi động lại (Restart) Mosquitto để nhận cấu hình mới. Bạn có thể kiểm tra trạng thái ngay ở giao diện **MQTT Broker** (biểu tượng chấm xanh "Đang chạy").

## 4. Thiết lập Truy cập từ xa (Tên miền)

Để bạn có thể truy cập Web Dashboard hoặc gửi/nhận MQTT từ xa (ngoài mạng wifi nhà bạn):

### Cách 1: Dùng phần mềm giả lập IP Public (Dễ nhất - Khuyên dùng)
Dùng **Ngrok** hoặc **Cloudflare Tunnel** (miễn phí) để trỏ tên miền (hoặc link sinh tự động) về máy tính của bạn:

- **Web Dashboard**: Expose port `8000` (http)
- **MQTT Broker**: Expose port `1883` (tcp)

### Cách 2: NAT Port Forwarding (Mạng nhà)
1. Truy cập vào modem/router mạng nhà bạn.
2. Tìm tính năng **Port Forwarding** (hoặc NAT/Virtual Server).
3. Mở các port sau trỏ về IP nội bộ của Laptop (ví dụ `192.168.1.100`):
   - Port `8000` (TCP): Dành cho Web Dashboard
   - Port `1883` (TCP): Dành cho MQTT (ESP32 gửi dữ liệu)
   - Port `9001` (TCP): Dành cho MQTT qua WebSocket
4. Mua tên miền, vào trang quản lý DNS (vd namesilo, godaddy, inet) và trỏ bản ghi **A** hoặc tạo **Dynamic DNS (DDNS)** trỏ về IP công cộng (Public IP) mạng nhà bạn.

> **Lưu ý:** Laptop của bạn cần phải luôn mở máy (không Sleep) để hệ thống hoạt động liên tục.
