# VisionBot AIoT

VisionBot la robot AIoT dung ESP32-CAM, MQTT control, camera WebSocket push/relay, backend FastAPI AI va frontend React.

Ban nay bam VisionBot System Design Specification v1.0, uu tien P0:

- MQTT command co ACK, TTL 300-500ms, khong retain command nguy hiem.
- ESP32-CAM/robot mat Wi-Fi/MQTT/backend thi retry voi backoff, khong reset/AP mode lien tuc.
- Backend giu latest-frame buffer, drop frame cu, khong xep hang AI lam lag.
- Dashboard hien ro backend/MQTT/robot/camera state machine, retry, stale/offline.
- VLM mac dinh dung llama-server OpenAI-compatible cho SmolVLM GGUF; backend khong bi treo neu VLM chua chay.

Kien truc ho tro 3 che do:

```text
1. Local LAN fallback
   ESP32-CAM -> ws://ESP:86 -> Backend pull -> Frontend
   Frontend -> Backend -> local MQTT -> ESP32-CAM

2. Backend direct camera push
   ESP32-CAM -> ws(s)://<backend-domain>/ws/camera/<device_id> -> Backend latest frame
   Frontend -> Backend -> MQTT -> ESP32-CAM

3. Internet relay/VPS mode
   ESP32-CAM -> Camera Relay WSS -> Backend subscribe -> Frontend
   Frontend -> Backend -> MQTT cloud/VPS -> ESP32-CAM
```

## 1. Kien truc Internet mode

```text
Camera:
ESP32-CAM
  -> wss://<domain>/camera/ws/push/<device_id>
  -> camera-relay
  -> backend subscribe frame
  -> frontend xem MJPEG tu backend

Control:
frontend
  -> backend FastAPI
  -> MQTT broker cloud/VPS
  -> ESP32-CAM motor/servo

AI:
backend nhan JPEG frame
  -> YOLO / VLM
  -> frontend hien thi result
```

ESP32-CAM khong can biet IP laptop. Laptop/backend khong can biet IP ESP.

## 2. Thanh phan chinh

```text
backend/       FastAPI, MQTT client, camera frame buffer, YOLO/VLM
camera-relay/  WebSocket binary JPEG relay, giu latest frame, drop frame cu
frontend/      React dashboard
firmware/      ESP32-CAM firmware LAN va Internet Push
deploy/vps/    Mosquitto + camera-relay + Caddy cho VPS
broker/        Mosquitto local fallback
scripts/       Script cai/chay WSL
```

## 3. Chay nhanh Local LAN

### 3.0 Mot lenh Docker cho demo tren laptop

Chay tat ca service local bang Docker Compose: MQTT broker, backend, frontend, camera-relay va VLM llama-server.

```bash
cd ~/visionbot/VisionBot-main
docker compose up -d --build
```

Neu muon xem log:

```bash
docker compose logs -f backend frontend camera-relay vlm
```

Dashboard:

```text
http://localhost:5173
```

Terminal 1 - MQTT local:

```bash
cd ~/visionbot/VisionBot-main/broker
docker compose up -d
docker logs -f visionbot-mosquitto
```

Terminal 2 - Backend:

```bash
cd ~/visionbot/VisionBot-main
bash scripts/install_backend_wsl.sh
bash scripts/run_backend_wsl_cpu.sh
```

Terminal 3 - Frontend:

```bash
cd ~/visionbot/VisionBot-main
bash scripts/install_frontend_wsl.sh
bash scripts/run_frontend_wsl.sh
```

Mo dashboard:

```text
http://localhost:5173
http://<ip-laptop>:5173
```

Firmware LAN fallback:

```text
firmware/VisionBot_ESP32CAM_MQTT1883/VisionBot_ESP32CAM_MQTT1883.ino
```

Trong setup portal ESP dien Wi-Fi, MQTT host la IP laptop trong cung mang, MQTT port 1883.

## 4. Internet / Cloudflare Tunnel

Cloudflare Tunnel free expose duoc HTTPS/WSS cho backend/camera, nhung khong expose MQTT TCP 1883. Vi vay MQTT nen dung VPS Mosquitto hoac broker cloud rieng.

### 4.0 Nhanh nhat: mot lenh Docker cho Internet mode

Muc tieu:

```text
ESP32-CAM -> Internet Wi-Fi bat ky 2.4GHz
ESP32-CAM -> MQTT cloud public de nhan lenh
ESP32-CAM -> Cloudflare Tunnel WSS de day frame camera
Laptop -> Docker backend/frontend/VLM de dieu khien va AI
```

Chay tren WSL:

```bash
cd ~/visionbot/VisionBot-main
MQTT_HOST=broker.emqx.io MQTT_PORT=1883 CAMERA_TOKEN=demo_camera BACKEND_TOKEN=demo_backend \
docker compose -f docker-compose.internet.yml up -d --build
```

Lenh tren tu bat:

```text
camera-relay
cloudflared quick tunnel
backend FastAPI
frontend dashboard
SmolVLM llama-server Docker
```

Lay link Cloudflare cho ESP32-CAM:

```bash
docker compose -f docker-compose.internet.yml logs -f cloudflared
```

Tim dong co dang:

```text
https://abc-xyz.trycloudflare.com
```

ESP32-CAM dung firmware Internet Push:

```text
firmware/VisionBot_ESP32CAM_INTERNET_PUSH/VisionBot_ESP32CAM_INTERNET_PUSH.ino
```

Vao portal ESP32-CAM va dien:

```text
Wi-Fi SSID: Wi-Fi bat ky 2.4GHz co Internet
Wi-Fi password: mat khau Wi-Fi do

MQTT broker host/IP: broker.emqx.io
MQTT broker port: 1883
MQTT username: de trong
MQTT password: de trong

Camera relay host/domain: abc-xyz.trycloudflare.com
Camera relay port: 443
Camera relay TLS: 1
Camera relay token: demo_camera
```

Mo dashboard tren laptop:

```text
http://localhost:5173
```

Trong o Backend API de:

```text
http://localhost:8000
```

Kiem tra:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/robots
```

Neu thay `mqtt_connected:true`, robot online va camera co frame la dung. Luc nay ESP32-CAM va laptop khong can chung Wi-Fi; chi can ca hai co Internet.

Luu y demo: `broker.emqx.io` la broker public, ai cung co the subscribe topic neu biet topic. Khi bao ve do an that, nen dung VPS Mosquitto rieng co username/password.

### 4.1 Direct backend push qua Cloudflare

Chay backend tren laptop:

```bash
cd ~/visionbot/VisionBot-main
MQTT_HOST=<mqtt-cloud-or-vps-host> \
MQTT_PORT=1883 \
CAMERA_PUSH_TOKEN=demo_camera \
bash scripts/run_backend_wsl_cpu.sh
```

PowerShell mo tunnel backend:

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8000
```

Copy URL dang:

```text
https://abc.trycloudflare.com
```

Trong firmware Internet Push dien:

```text
Camera push host/domain: abc.trycloudflare.com
Camera push port: 443
Camera push TLS: 1
Camera push token: demo_camera
Camera push path: /ws/camera   (mac dinh backend cung chap nhan /camera/ws/push)
MQTT broker host/IP: <mqtt-cloud-or-vps-host>
MQTT broker port: 1883
```

Backend nhan frame tai:

```text
wss://abc.trycloudflare.com/ws/camera/<device_id>?token=demo_camera
```

### 4.2 Camera relay rieng

Chay camera relay tren laptop:

```bash
cd ~/visionbot/VisionBot-main
bash scripts/install_camera_relay_wsl.sh
CAMERA_TOKEN=demo_camera BACKEND_TOKEN=demo_backend bash scripts/run_camera_relay_wsl.sh
```

Tunnel relay:

```powershell
cloudflared tunnel --url http://localhost:8001
```

Backend ket noi relay:

```bash
MQTT_HOST=<mqtt-cloud-or-vps-host> \
MQTT_PORT=1883 \
CAMERA_RELAY_WS='wss://abc.trycloudflare.com/camera/ws/subscribe/{device_id}' \
CAMERA_RELAY_TOKEN=demo_backend \
bash scripts/run_backend_wsl_cpu.sh
```

Public broker chi nen dung demo. Ban on dinh nen dung VPS Mosquitto rieng.

Frontend:

```bash
cd ~/visionbot/VisionBot-main
bash scripts/install_frontend_wsl.sh
bash scripts/run_frontend_wsl.sh
```

Mo:

```text
http://localhost:5173
```

## 5. Firmware ESP32-CAM Internet Push

File:

```text
firmware/VisionBot_ESP32CAM_INTERNET_PUSH/VisionBot_ESP32CAM_INTERNET_PUSH.ino
```

Trong Arduino IDE:

```text
Board: AI Thinker ESP32-CAM
Partition: Huge APP
PSRAM: Enabled
Upload speed: 115200
```

Sau khi nap, vao setup portal ESP va dien:

```text
Wi-Fi SSID/password: Wi-Fi bat ky co Internet
MQTT broker host/IP: broker cloud/VPS
MQTT broker port: 1883
MQTT username/password: neu co
Camera push/relay host/domain: abc.trycloudflare.com
Camera relay port: 443
Camera relay TLS: 1
Camera relay token: demo_camera
```

Serial dung se co:

```text
[CAM PUSH] relay URL: wss://abc.trycloudflare.com:443/camera/ws/push/<device_id>?token=...
[CAM PUSH] connected to backend relay.
MQTT connected.
```

## 6. SmolVLM GGUF qua llama-server

Backend mac dinh ho tro SmolVLM GGUF qua OpenAI-compatible API:

```text
AI_VLM_PROVIDER=llama_server
AI_VLM_MODEL=ggml-org/SmolVLM-500M-Instruct-GGUF
AI_VLM_OPENAI_BASE_URL=http://127.0.0.1:8080
AI_VLM_TIMEOUT_S=25
```

Chay llama-server rieng theo repo SmolVLM realtime/GGUF cua ban, expose:

```text
http://127.0.0.1:8080/v1/chat/completions
```

Neu dung Docker backend, `docker-compose.yml` da dat:

```text
AI_VLM_OPENAI_BASE_URL=http://host.docker.internal:8080
```

Neu VLM chua chay, dashboard van stream/detect duoc; VLM chat se bao `llama_server_unavailable` ro rang va lan sau van retry.

## 7. VPS deployment chuan

Copy repo len VPS, vao:

```bash
cd deploy/vps
cp .env.example .env
```

Tao MQTT users:

```bash
docker run --rm -it -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -c /mosquitto/config/passwd backend_user
docker run --rm -it -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd /mosquitto/config/passwd robot01_user
```

Sua `.env`:

```env
VISIONBOT_DOMAIN=your-domain.example.com
CAMERA_TOKEN=change_camera_token
BACKEND_TOKEN=change_backend_token
```

Chay:

```bash
docker compose up -d --build
docker compose logs -f
```

Health:

```bash
curl https://your-domain.example.com/camera/health
```

Backend tren laptop/server:

```bash
MQTT_HOST=your-domain.example.com \
MQTT_PORT=1883 \
MQTT_USERNAME=backend_user \
MQTT_PASSWORD='password' \
CAMERA_RELAY_WS='wss://your-domain.example.com/camera/ws/subscribe/{device_id}' \
CAMERA_RELAY_TOKEN='change_backend_token' \
bash scripts/run_backend_wsl_cpu.sh
```

## 8. Docker Compose local

Chay full stack local:

```bash
cd ~/visionbot/VisionBot-main
docker compose up -d --build
docker compose ps
```

Mac dinh compose mo:

```text
Frontend: http://localhost:5173
Backend:  http://localhost:8000
MQTT:     localhost:1884 -> container 1883
Relay:    http://localhost:8001/camera/health
```

Neu firmware dang dung MQTT port 1883 thi chay broker rieng trong `broker/` thay vi full compose, hoac sua firmware MQTT port thanh 1884.

## 9. Debug nhanh

MQTT:

```bash
mosquitto_sub -h <mqtt-host> -p 1883 -t 'visionbot/#' -v
```

Relay:

```bash
curl https://<relay-domain>/camera/health
```

Backend:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/robots
curl http://localhost:8000/api/robots/<device_id>/ai/status
```

Camera push direct:

```text
ws://<backend-ip>:8000/ws/camera/<device_id>
wss://<cloudflare-domain>/ws/camera/<device_id>?token=<CAMERA_PUSH_TOKEN>
```

Camera session can co:

```json
{
  "running": true,
  "connected": true,
  "frame_count": 10
}
```

## 10. Safety

- Motor command co TTL/duration, ESP tu stop khi qua han.
- ESP stop motor khi mat Wi-Fi/MQTT, nhung service loi thi retry backoff, khong reset/AP loop.
- Backend validate command va cho ack.
- Emergency stop luon uu tien.
- Camera stream khong di qua MQTT.
