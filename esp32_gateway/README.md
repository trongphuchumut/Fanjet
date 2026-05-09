# ESP32 PLC ↔ MQTT Gateway – FanJet BMS

Firmware cho ESP32 làm **Gateway trung gian** giữa PLC (Modbus RTU / RS-485)
và MQTT Broker (kết nối 4G LTE qua module A7680C).

## Kiến trúc tổng quan

```
  ┌──────────┐   RS-485 Modbus RTU   ┌──────────────┐   UART    ┌─────────┐   4G LTE   ┌──────────────┐
  │   PLC    │ ◄─────────────────── │    ESP32      │ ────────► │ A7680C  │ ─────────► │ MQTT Broker  │
  │ (Tủ quạt)│   (MAX485 / SP3485)  │  (Gateway)   │           │ (SIM)   │            │ (Mosquitto)  │
  └──────────┘                       └──────────────┘           └─────────┘            └──────┬───────┘
                                                                                              │
                                                                                       ┌──────▼───────┐
                                                                                       │ FanJet BMS   │
                                                                                       │ Web Server   │
                                                                                       └──────────────┘
```

## Sơ đồ đấu nối phần cứng

```
  ┌────────────────────┐         ┌──────────────────┐         ┌───────────────┐
  │      ESP32         │         │  MAX485 / SP3485 │         │     PLC       │
  │                    │         │                  │         │               │
  │  GPIO17 (TX2) ────►│── DI    │             A ──►│─────────│◄── RS485 A    │
  │  GPIO16 (RX2) ◄────│── RO    │             B ──►│─────────│◄── RS485 B    │
  │  GPIO5  (DE)  ────►│── DE+RE │                  │         │               │
  │                    │         │  VCC ── 3.3V     │         │               │
  │  3.3V ────────────►│── VCC   │  GND ── GND     │         │               │
  │  GND  ────────────►│── GND   │                  │         │               │
  └────────────────────┘         └──────────────────┘         └───────────────┘

  ┌────────────────────┐         ┌──────────────────┐
  │      ESP32         │         │     A7680C       │
  │                    │         │                  │
  │  GPIO26 (TX1) ────►│─────────│◄── RXD          │
  │  GPIO27 (RX1) ◄────│─────────│──► TXD          │
  │  GPIO4  (PWR) ────►│─────────│◄── PWRKEY       │
  │                    │         │                  │
  │  GND  ────────────►│─────────│◄── GND          │
  │                    │         │  VCC ── 4V (LDO) │
  │  GPIO2 (LED) ──► LED        │  [SIM Card]      │
  └────────────────────┘         └──────────────────┘
```

> ⚠️ **Lưu ý**: A7680C cần nguồn riêng 3.5–4.2V (dùng LDO từ 5V), **không cấp trực tiếp 3.3V từ ESP32**.

## Bảng chân ESP32

| ESP32 Pin | Kết nối              | Ghi chú                           |
|-----------|----------------------|-----------------------------------|
| GPIO17    | MAX485 DI            | UART2 TX → RS-485 truyền          |
| GPIO16    | MAX485 RO            | UART2 RX ← RS-485 nhận            |
| GPIO5     | MAX485 DE + RE       | Direction Enable (HIGH = transmit) |
| GPIO26    | A7680C RXD           | UART1 TX → 4G module              |
| GPIO27    | A7680C TXD           | UART1 RX ← 4G module              |
| GPIO4     | A7680C PWRKEY        | Power on/off modem                 |
| GPIO2     | LED onboard          | Trạng thái hoạt động               |

## Modbus Register Map (PLC)

### Input Registers (đọc từ PLC ← cảm biến)

| Register | Mô tả              | Đơn vị / Giá trị                |
|----------|---------------------|----------------------------------|
| 0x00     | CO Concentration    | ppm × 10 (VD: 352 = 35.2 ppm)   |
| 0x01     | Fan Speed           | 0–100 %                          |
| 0x02     | Tripped flag        | 0 = OK, 1 = Lỗi/Trip            |
| 0x03     | Mode                | 0 = Auto, 1 = Manual             |

### Holding Registers (ghi xuống PLC → điều khiển)

| Register | Mô tả              | Đơn vị / Giá trị                |
|----------|---------------------|----------------------------------|
| 0x00     | Set Mode            | 0 = Auto, 1 = Manual             |
| 0x01     | Set Speed           | 0–100 %                          |

## MQTT Topics

### Upstream – ESP32 → Server (Telemetry)
- **Topic:** `fanjet/basement/<unit_id>/telemetry`
- **Payload:**
```json
{"co": 35.2, "speed": 72, "tripped": false, "mode": "auto"}
```

### Downstream – Server → ESP32 (Command)
- **Topic:** `fanjet/basement/<unit_id>/command`
- **Payload:**
```json
{"mode": "manual", "speed": 80}
```

### Downstream – Server → ESP32 (Profile)
- **Topic:** `fanjet/basement/<unit_id>/profile`
- **Payload:**
```json
{"profile": [{"co": 10, "speed": 20}, {"co": 30, "speed": 60}, {"co": 50, "speed": 100}]}
```

## Cài đặt & Upload

### Yêu cầu
- **Arduino IDE** ≥ 2.0 hoặc **PlatformIO**
- **Board:** ESP32 Dev Module
- **Libraries** (cài qua Library Manager):
  - `TinyGSM` – Quản lý A7680C AT commands
  - `PubSubClient` – MQTT client
  - `ArduinoJson` v7+ – JSON parse/serialize
  - `ModbusMaster` – Modbus RTU master

### Các bước Upload
1. Mở `esp32_gateway.ino` trong Arduino IDE
2. Chọn Board: **ESP32 Dev Module**
3. Sửa cấu hình mặc định trong code (APN, MQTT host...) hoặc dùng Serial CLI sau khi upload
4. Upload → mở Serial Monitor 115200 baud
5. Dùng lệnh `set` + `save` để cấu hình, sau đó `restart`

## Cấu hình qua Serial CLI

Kết nối Serial Monitor (115200 baud), gõ lệnh:

```
set apn v-internet
set mqtt_host fan-auto.cloud
set mqtt_port 1883
set mqtt_user admin
set mqtt_pass secret123
set mqtt_prefix fanjet/basement
set unit_id F01
set modbus_addr 1
set pub_interval 3
save
restart
```

### Danh sách lệnh

| Lệnh                     | Mô tả                                  |
|---------------------------|-----------------------------------------|
| `set <key> <value>`      | Đặt giá trị cấu hình                   |
| `save`                   | Lưu config vào NVS Flash               |
| `restart`                | Khởi động lại ESP32                     |
| `status`                 | Xem trạng thái hiện tại                 |
| `read`                   | Đọc PLC ngay lập tức                    |
| `pub`                    | Force publish telemetry                 |
| `help`                   | Hiển thị danh sách lệnh                 |

## LED trạng thái

| Pattern               | Ý nghĩa                    |
|-----------------------|-----------------------------|
| Chớp chậm (1s)        | Mất kết nối / Lỗi 4G       |
| Chớp nhanh (200ms)    | Đang kết nối...             |
| Sáng liên tục         | MQTT đã kết nối thành công  |

## Luồng hoạt động

1. **Khởi động** → Load config NVS → Init RS-485 Modbus → Power on A7680C → Kết nối 4G → Kết nối MQTT
2. **Mỗi 1 giây** → Đọc 4 Input Registers từ PLC (CO, Speed, Trip, Mode)
3. **Mỗi N giây** (cấu hình `pub_interval`) → Publish telemetry JSON lên MQTT
4. **Khi nhận `/command`** → Parse JSON → Ghi Holding Registers xuống PLC
5. **Khi nhận `/profile`** → Lưu profile vào RAM + NVS Flash
6. **Mất kết nối** → Tự động reconnect GPRS + MQTT mỗi 15 giây
