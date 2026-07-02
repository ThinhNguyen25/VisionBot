# VisionBot chạy gấp bằng MQTT thường trên WSL

> Bản mới khuyên dùng `LOCAL_LAN_COMPOSE_GUIDE.md` với `docker compose up -d --build`.
> File này giữ lại cho cách chạy thủ công từng terminal.

File này dành cho bản demo nội bộ: Mosquitto MQTT thường port `1883`, không dùng TLS/cert, không bắt buộc username/password.

## 1. Lấy IP Wi-Fi của laptop Windows

Trên Windows PowerShell:

```powershell
ipconfig
```

Tìm card Wi-Fi đang kết nối cùng mạng với ESP32-CAM, lấy dòng `IPv4 Address`, ví dụ:

```text
192.168.1.66
```

ESP32-CAM phải dùng IP này làm `MQTT host`. Không dùng `localhost`, không dùng IP WSL `172.x.x.x`.

## 2. Chạy broker MQTT trong WSL

```bash
cd ~/visionbot/VisionBot-main/broker
docker compose down
docker compose up -d
docker logs visionbot-mosquitto --tail 50
```

Log đúng sẽ có port `1883`.

## 3. Cài và chạy backend

```bash
cd ~/visionbot/VisionBot-main
./scripts/install_backend_wsl.sh
./scripts/run_backend_wsl_cpu.sh
```

Backend dùng mặc định:

```text
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_USERNAME=
MQTT_PASSWORD=
```

Test:

```bash
curl http://localhost:8000/api/health
```

Nếu `mqtt_connected: true` là backend đã nối broker.

## 4. Cài và chạy frontend

Mở terminal WSL khác:

```bash
cd ~/visionbot/VisionBot-main
./scripts/install_frontend_wsl.sh
./scripts/run_frontend_wsl.sh
```

Mở trên laptop:

```text
http://localhost:5173
```

Nếu mở từ điện thoại cùng Wi-Fi, vào:

```text
http://<IP-Wi-Fi-laptop>:5173
```

Trong `frontend/.env`, nếu dùng điện thoại:

```text
VITE_API_BASE=http://<IP-Wi-Fi-laptop>:8000
VITE_DEVICE_ID=VB-CAM-E9BFB4
```

## 5. Nạp lại ESP32-CAM

Nạp file:

```text
firmware/VisionBot_ESP32CAM/VisionBot_ESP32CAM.ino
```

Trong Arduino IDE cần thư viện:

```text
WiFiManager
PubSubClient
WebSockets
ArduinoJson
esp32-camera / ESP32 board package
```

Sau khi nạp, mở Serial Monitor `115200`. ESP sẽ hiện setup AP kiểu:

```text
VisionBot-xxxxxx
```

Kết nối điện thoại/laptop vào AP đó rồi nhập portal:

```text
Wi-Fi SSID: Wi-Fi chung với laptop
Wi-Fi password: mật khẩu Wi-Fi
MQTT host: IP Wi-Fi laptop, ví dụ 192.168.1.66
MQTT port: 1883
MQTT username: để trống
MQTT password: để trống
MQTT base topic: visionbot
Telemetry interval ms: 5000
```

Không cần Root CA, không cần cert.

## 6. Khi đổi Wi-Fi hoặc IP laptop

Không cần tạo cert nữa. Chỉ cần mở lại portal để sửa `MQTT host`.

Cách nhanh nhất: trong Serial Monitor gửi ký tự:

```text
x
```

ESP sẽ reset config và mở portal lại. Sau đó nhập IP Wi-Fi mới của laptop.

## 7. Nếu ESP không hiện online

Kiểm tra theo thứ tự:

1. Laptop, ESP32-CAM, điện thoại có cùng Wi-Fi không.
2. ESP `MQTT host` có đúng IP Wi-Fi Windows không, không phải IP WSL.
3. Broker có chạy không:

```bash
docker ps
docker logs visionbot-mosquitto --tail 80
```

4. Backend có `mqtt_connected: true` không:

```bash
curl http://localhost:8000/api/health
```

5. Windows Firewall có chặn port `1883`, `8000`, `5173` không. Nếu điện thoại không vào được frontend/backend, mở firewall cho các port này hoặc chỉ demo trực tiếp trên laptop.
