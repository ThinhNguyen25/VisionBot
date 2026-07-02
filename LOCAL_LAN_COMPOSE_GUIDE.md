# VisionBot Local LAN Docker Compose

Mục tiêu: mang project sang máy khác, bật một hotspot cố định, chạy một lệnh Docker Compose là có dashboard + backend AI + MQTT broker.

## 1. Cấu hình hotspot laptop

Trên Windows bật Mobile Hotspot với thông tin cố định:

```text
SSID: VisionBot-LAN
Password: visionbot123
```

Windows Mobile Hotspot thường đặt IP laptop là:

```text
192.168.137.1
```

Firmware ESP32-CAM bản này đã mặc định:

```text
Wi-Fi SSID: VisionBot-LAN
Wi-Fi password: visionbot123
MQTT host: 192.168.137.1
MQTT port: 1884
MQTT username/password: trống
```

Nếu hotspot chưa bật, ESP sẽ fallback về WiFiManager portal như cũ.

## 2. Nạp ESP32-CAM

Nạp file:

```text
firmware/VisionBot_ESP32CAM/VisionBot_ESP32CAM.ino
```

Arduino libraries:

```text
WiFiManager
PubSubClient
WebSockets
ArduinoJson
esp32-camera / ESP32 board package
```

Sau khi nạp, mở Serial Monitor `115200`. Khi hotspot đúng, ESP sẽ tự hiện:

```text
Demo hotspot connected.
MQTT broker default: 192.168.137.1:1884
MQTT connected.
```

## 3. Chạy toàn bộ app bằng Docker Compose

Yêu cầu trên máy demo:

```text
Docker Desktop
WSL2 Ubuntu hoặc terminal có Docker Compose
```

Copy project vào WSL, ví dụ:

```bash
mkdir -p ~/visionbot
cp "/mnt/c/HocTap/VisionBot-local-lan-compose.zip" ~/visionbot/
cd ~/visionbot
unzip -o VisionBot-local-lan-compose.zip
cd VisionBot-main
```

Chạy toàn bộ:

```bash
docker compose up -d --build
```

Lệnh này bật:

```text
visionbot-mqtt       MQTT broker, external port 1884, internal port 1883
visionbot-backend    FastAPI + AI, port 8000
visionbot-frontend   Dashboard, port 5173
```

Lần build đầu tiên cần internet để tải Docker images, Python packages, Node packages. Các lần sau thường chỉ cần:

```bash
docker compose up -d
```

## 4. Mở dashboard

Trên laptop:

```text
http://localhost:5173
```

Từ điện thoại/máy khác đang nối vào hotspot:

```text
http://192.168.137.1:5173
```

Frontend tự gọi backend theo host đang mở:

```text
http://192.168.137.1:8000
```

Không cần sửa `frontend/.env`.

## 5. Kiểm tra trạng thái

```bash
docker compose ps
docker compose logs -f mqtt
docker compose logs -f backend
```

Test backend:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/robots
```

Test MQTT topic:

```bash
docker exec -it visionbot-mqtt mosquitto_sub -h localhost -p 1883 -t 'visionbot/#' -v
```

Reset ESP. Nếu đúng, terminal sẽ thấy:

```text
visionbot/VB-CAM-E9BFB4/state {...}
visionbot/VB-CAM-E9BFB4/telemetry {...}
```

## 6. Firewall Windows

Nếu ESP hoặc điện thoại không vào được, mở PowerShell Run as Administrator:

```powershell
New-NetFirewallRule -DisplayName "VisionBot MQTT 1884" -Direction Inbound -Protocol TCP -LocalPort 1884 -Action Allow
New-NetFirewallRule -DisplayName "VisionBot Backend 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
New-NetFirewallRule -DisplayName "VisionBot Frontend 5173" -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow
```

## 7. Dừng app

```bash
docker compose down
```

Xóa sạch retained MQTT/model cache nếu cần làm lại từ đầu:

```bash
docker compose down -v
```

## 8. Ghi nhớ nhanh

Mỗi lần demo:

```bash
cd ~/visionbot/VisionBot-main
docker compose up -d
```

Mở:

```text
http://localhost:5173
```

ESP chỉ cần nối hotspot `VisionBot-LAN`.
