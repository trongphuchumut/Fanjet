# Tài Liệu Đặc Tả Giao Thức MQTT - Hệ Thống FanJet BMS

Tài liệu này mô tả chi tiết các topic và định dạng payload (JSON) được sử dụng để giao tiếp giữa Web Server (BMS Dashboard - Django) và các thiết bị phần cứng (Bộ điều khiển Quạt).

## 1. Cấu trúc Topic chung

Tất cả các topic đều có chung một phần tiền tố (Topic Base) mặc định với cấu trúc như sau:
`<topic_prefix>/<unit_id>`

* Trong đó:
  * `<topic_prefix>`: Tiền tố mặc định của hệ thống là `fanjet/basement` (Có thể thay đổi trong phần Cài đặt Hệ thống của giao diện Web).
  * `<unit_id>`: Mã định danh ID của từng bộ quạt (Ví dụ: `F01`, `F02`, `FAN-CT1`,...).

👉 **Ví dụ Topic Base thực tế:** `fanjet/basement/F01`

---

## 2. Gửi lên từ Thiết Bị (Upstream / Telemetry)

Dữ liệu do thiết bị (vi điều khiển/PLC ở tủ quạt) liên tục đọc được và gửi lên Web Server định kỳ theo thời gian thực. Báo cáo tình trạng sức khoẻ, thông số cảm biến môi trường.

* **Topic:** `<topic_prefix>/<unit_id>/telemetry`
* **Ví dụ:** `fanjet/basement/F01/telemetry`
* **QoS đề xuất:** 0 hoặc 1

**Định dạng Payload (JSON):**
```json
{
  "co": 35.2,
  "speed": 72,
  "tripped": false,
  "mode": "auto"
}
```

**Giải thích các thông số:**
* `co` *(float)*: Giá trị nồng độ khí CO hệ thống đọc được (đơn vị: ppm).
* `speed` *(integer)*: Tốc độ hiện tại thực tế báo về từ phần cứng (đơn vị: %, khoảng từ `0` đến `100`).
* `tripped` *(boolean)*: Trạng thái cờ báo lỗi/sự cố (Trip/Fault). Giá trị `true` tức là đang có dòng sự cố hoặc mất pha/quá tải, `false` là quạt hoàn toàn bình thường.
* `mode` *(string)*: Chế độ vận hành hiện tại bên dưới. Có 2 giá trị là `"auto"` hoặc `"manual"`.

---

## 3. Gửi xuống từ Server (Downstream / Control & Config)

Dữ liệu từ hệ thống FanJet Web Server (trên Cloud hoặc Máy chủ) đẩy xuống phần cứng qua MQTT để ra lệnh điều khiển tức thời hoặc tinh chỉnh cấu hình chạy tự động.

### 3.1. Lệnh điều khiển Quạt (Command)

Gửi khi người điều hành click chuột để đổi chế độ hoạt động hoặc kéo Slider trượt thay đổi tốc độ quạt (khi chạy tay).

* **Topic:** `<topic_prefix>/<unit_id>/command`
* **Ví dụ:** `fanjet/basement/F01/command`
* **QoS đề xuất:** 1

**Định dạng Payload (JSON):**
```json
{
  "mode": "manual",
  "speed": 80
}
```

**Giải thích các thông số:**
* `mode` *(string)*: Lệnh yêu cầu thiết bị tuân theo (`"auto"`: giao quyền về bộ xử lý tự động theo cảm biến, `"manual"`: yêu cầu khoá bằng lệnh ghi đè).
* `speed` *(integer)*: Tốc độ mong muốn ra lệnh xuống (%). Thường có tác dụng bắt buộc khi `mode` là `"manual"`.

### 3.2. Cập nhật biểu đồ thông minh (Profile)

Giúp thiết bị tự chủ, tự duy trì luật chạy kể cả khi đứt mạng. Web server cho kéo, vẽ cấu hình đồ thị CO-Speed tuỳ chỉnh cho từng quạt, sau đó biên dịch ra Profile đẩy xuống thiết bị phần cứng lưu vào Flash.

* **Topic:** `<topic_prefix>/<unit_id>/profile`
* **Ví dụ:** `fanjet/basement/F01/profile`
* **QoS đề xuất:** 1

**Định dạng Payload (JSON):**
```json
{
  "profile": [
    {
      "co": 10.0,
      "speed": 20
    },
    {
      "co": 30.0,
      "speed": 60
    },
    {
      "co": 50.0,
      "speed": 100
    }
  ]
}
```

**Giải thích các thông số:**
* `profile` *(array)*: Danh sách mảng các điểm cấu trúc thông số.
  * `co` *(float)*: Tại điểm nồng độ CO này.
  * `speed` *(integer)*: Yêu cầu chạy ở tốc độ này. (*Lưu ý: Firmware ở dưới tủ Quạt sẽ có thuật toán Interpolation (nội suy) giữa các điểm dữ liệu mốc này để ra quyết định điều chỉnh tốc độ mượt mà khi chạy ở chế độ AUTO*).
