# VisionBot AI/IoT Dashboard

VisionBot la robot ESP32-CAM dung dashboard React, backend FastAPI AI, MQTT broker Mosquitto va Docker Compose de chay local LAN. Ban hien tai uu tien demo nhanh, on dinh, mang di may nao cung chay duoc neu laptop phat hotspot co dinh.

## 1. Ban nay chay nhu the nao

```text
Phone/Laptop browser
  -> Frontend dashboard: http://192.168.137.1:5173
      -> Backend FastAPI + AI: http://192.168.137.1:8000
          -> MQTT broker trong Docker: external 1884 -> internal 1883
              -> ESP32-CAM robot

ESP32-CAM
  -> Wi-Fi hotspot: VisionBot-LAN
  -> MQTT: 192.168.137.1:1884
  -> Camera WebSocket: ws://<ESP-IP>:86/
```

Khong con MQTTS/cert cho ban demo nay. MQTT la plain TCP trong mang local/hotspot rieng de giam loi khi doi Wi-Fi, doi IP laptop.

## 2. Cau hinh co dinh de dem di demo

Bat Windows Mobile Hotspot:

```text
SSID: VisionBot-LAN
Password: visionbot123
Laptop hotspot IP thuong la: 192.168.137.1
```

Firmware ESP32-CAM ban demo da mac dinh:

```text
Wi-Fi SSID: VisionBot-LAN
Wi-Fi password: visionbot123
MQTT host: 192.168.137.1
MQTT external port: 1884
MQTT username/password: de trong
Device ID: VB-CAM-E9BFB4
```

Neu ESP32-CAM cua ban da nap firmware `v1.2.1-compose-hotspot-port1884` va serial log da hien `MQTT connected`, thi khong can nap lai code moi lan chay.

## 3. Can cai gi tren may moi

Tren Windows:

```text
Docker Desktop
Ubuntu WSL2
Git
Chrome/Edge
Arduino IDE chi can neu phai nap lai ESP32-CAM
```

Trong Ubuntu WSL:

```bash
sudo apt update
sudo apt install -y git curl unzip ca-certificates
```

Docker Desktop can bat WSL Integration cho distro Ubuntu dang dung.

## 4. Lay project tu GitHub

Trong WSL:

```bash
mkdir -p ~/visionbot
cd ~/visionbot
git clone https://github.com/ThinhNguyen25/VisionBot.git VisionBot-main
cd VisionBot-main
```

Neu da clone roi va muon cap nhat ban moi:

```bash
cd ~/visionbot/VisionBot-main
git pull
```

## 5. Chay toan bo he thong bang mot lenh

Bat Docker Desktop truoc, sau do trong WSL:

```bash
cd ~/visionbot/VisionBot-main
docker compose up -d --build
docker compose ps
```

Lenh nay bat cung luc:

```text
visionbot-mqtt       Mosquitto MQTT broker, port ngoai 1884
visionbot-backend    FastAPI + AI, port 8000
visionbot-frontend   Dashboard, port 5173
```

Lan dau can internet de tai Docker image, Python packages va Node packages. Nhung lan sau co the chay nhanh hon:

```bash
docker compose up -d
```

## 6. Mo giao dien dieu khien

Tren laptop:

```text
http://localhost:5173
```

Tren dien thoai hoac may khac dang noi vao hotspot `VisionBot-LAN`:

```text
http://192.168.137.1:5173
```

Backend health:

```text
http://192.168.137.1:8000/api/health
```

Frontend tu tinh backend theo host dang mo, nen khong can sua `frontend/.env` khi xem tren dien thoai.

## 7. Trinh tu demo nhanh

1. Bat Docker Desktop.
2. Bat Windows Mobile Hotspot:
   `VisionBot-LAN` / `visionbot123`.
3. Cam nguon ESP32-CAM.
4. Chay:

```bash
cd ~/visionbot/VisionBot-main
docker compose up -d --build
```

5. Mo:

```text
http://192.168.137.1:5173
```

6. Trong UI bam `Lam moi`, thay MQTT OK va Robot online la co the lai.

## 8. Kiem tra log khi co loi

Xem cac container:

```bash
docker compose ps
```

Xem MQTT:

```bash
docker compose logs -f mqtt
```

Khi ESP ket noi dung, log se co dong gan giong:

```text
New client connected ... as VB-CAM-E9BFB4
```

Xem backend:

```bash
docker compose logs -f backend
```

Test API:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/robots
```

Nghe MQTT topic truc tiep:

```bash
docker exec -it visionbot-mqtt mosquitto_sub -h localhost -p 1883 -t 'visionbot/#' -v
```

## 9. Dung he thong

Dung container nhung giu volume/cache:

```bash
docker compose down
```

Xoa sach volume MQTT/model cache de lam lai tu dau:

```bash
docker compose down -v
```

## 10. Nap ESP32-CAM khi nao

Khong can nap lai neu ESP dang co ban demo:

```text
Firmware: v1.2.1-compose-hotspot-port1884
Wi-Fi: VisionBot-LAN
MQTT: 192.168.137.1:1884
```

Chi nap lai khi:

```text
ESP dang la firmware MQTTS cu
ESP dang tro ve MQTT port 1883/8883 sai voi Docker Compose moi
ESP khong tu vao VisionBot-LAN
Muon doi ten Wi-Fi/password/hardware pin
```

File firmware:

```text
firmware/VisionBot_ESP32CAM/VisionBot_ESP32CAM.ino
```

Arduino libraries can co:

```text
WiFiManager
PubSubClient
WebSockets
ArduinoJson
ESP32 board package co esp32-camera
```

Serial Monitor:

```text
Baud: 115200
```

Log dung:

```text
Demo hotspot connected.
IP: 192.168.137.xxx
MQTT TCP probe 192.168.137.1:1884 ... OK
MQTT connected.
Runtime ready
```

## 11. AI trong ban demo

Mac dinh backend chay CPU:

```text
Detector: yolo11n.onnx
imgsz: 320
conf: 0.25
VLM: tat mac dinh de stream on dinh
```

Trong UI:

```text
Video raw    xem camera goc
AI overlay   xem stream co bbox detector
Detect       detect mot frame
VLM          hoi dap tren frame hien tai neu bat VLM/model da tai
Tai model    preload model dang chon
Ap dung      cap nhat model/imgsz/conf/interval
```

Luu y:

```text
yolo11n.onnx trong repo export input 320, nen khong chon imgsz 416 cho model nay.
VLM lan dau co the rat lau vi phai tai model.
Neu CPU yeu, dung Video raw khi lai robot, chi bam Detect khi can nhan dang.
```

## 12. Firewall Windows

Neu dien thoai khong mo duoc dashboard hoac ESP khong vao MQTT, mo PowerShell Run as Administrator:

```powershell
New-NetFirewallRule -DisplayName "VisionBot MQTT 1884" -Direction Inbound -Protocol TCP -LocalPort 1884 -Action Allow
New-NetFirewallRule -DisplayName "VisionBot Backend 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
New-NetFirewallRule -DisplayName "VisionBot Frontend 5173" -Direction Inbound -Protocol TCP -LocalPort 5173 -Action Allow
```

Kiem tra tren Windows:

```powershell
Test-NetConnection 192.168.137.1 -Port 1884
```

## 13. Loi thuong gap

### Docker compose khong co MQTT port 1884

Kiem tra:

```bash
docker compose ps
```

Can thay:

```text
0.0.0.0:1884->1883/tcp
0.0.0.0:8000->8000/tcp
0.0.0.0:5173->80/tcp
```

### Backend bao mqtt_connected false

Chay:

```bash
docker compose logs --tail 80 backend
docker compose logs --tail 80 mqtt
```

Backend phai co:

```text
[MQTT] connected to mqtt:1883
```

### Robot offline

Kiem tra theo thu tu:

```text
1. Hotspot Windows co dung VisionBot-LAN / visionbot123 khong
2. ESP serial co IP 192.168.137.xxx khong
3. ESP serial co MQTT probe 192.168.137.1:1884 OK khong
4. docker compose ps co expose 1884 khong
5. Firewall Windows co chan port 1884 khong
```

### Dien thoai vao dashboard nhung khong stream

Kiem tra trong serial ESP:

```text
Camera stream URL: ws://192.168.137.xxx:86/
```

Dien thoai phai ket noi vao hotspot `VisionBot-LAN`. Neu dien thoai dung 4G/ Wi-Fi khac se khong thay ESP.

### YOLO bao Got 416 Expected 320

Dung preset `YOLO realtime` hoac `YOLO can bang` trong ban moi. Ca hai da ep `yolo11n.onnx` ve `imgsz=320`.

### VLM bao thieu num2words

Ban Dockerfile/requirements moi da them:

```text
num2words>=0.5.13
```

Build lai backend:

```bash
docker compose build backend
docker compose up -d backend
```

## 14. File huong dan phu

```text
LOCAL_LAN_COMPOSE_GUIDE.md  huong dan Docker Compose LAN chi tiet
QUICK_WSL_MQTT_DEMO.md      cach chay thu cong tung service, chi de tham khao
```

## 15. Cau lenh nho nhanh

Moi lan thi/demo:

```bash
cd ~/visionbot/VisionBot-main
docker compose up -d
```

Mo tren dien thoai:

```text
http://192.168.137.1:5173
```

Dung:

```bash
docker compose down
```
