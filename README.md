# VisionBot AI/IoT Dashboard

VisionBot là robot ESP32-CAM AI/IoT dùng **frontend React/Vite**, **backend FastAPI**, **Mosquitto MQTTS**, và **ESP32-CAM headless**. Frontend không điều khiển trực tiếp ESP32-CAM; mọi lệnh đi qua backend, backend publish MQTTS xuống robot.

## 1. Kiến trúc

```text
Frontend React/Vite
  -> Backend FastAPI
      -> Mosquitto MQTTS broker
          -> ESP32-CAM firmware

ESP32-CAM
  -> WebSocket JPEG stream port 86
  -> Backend relay MJPEG raw/AI overlay
```

AI trong dự án có 2 nhánh:

```text
Detector realtime
  - YOLO ONNX CPU
  - SSDlite MobileNetV3 / Faster R-CNN / RetinaNet / FCOS qua TorchVision
  - trả bbox + nhãn + latency + FPS

VLM hỏi đáp theo frame
  - SmolVLM / SmolVLM2 / Florence-2 / Qwen2.5-VL 3B / PaliGemma2 3B
  - trả lời câu hỏi về frame hiện tại
  - có latency/FPS để benchmark
  - không dùng realtime liên tục trên CPU
```

## 2. Phần cứng đang hỗ trợ

Phần cứng hiện tại của project:

```text
ESP32-CAM AI Thinker + camera OV3660
L298N motor driver
2 motor DC vàng
Servo GPIO2
Laptop Windows + Ubuntu WSL2
Mosquitto Docker broker
```

Pin firmware hiện tại:

```text
IN1 = GPIO12
IN2 = GPIO13
IN3 = GPIO14
IN4 = GPIO15
Servo = GPIO2
Camera AI Thinker pins giữ theo firmware
```

ESP32-CAM dùng MQTTS strict TLS, không dùng setInsecure.

## 3. App/framework cần cài trên máy mới

Trên Windows:

```text
Docker Desktop
Ubuntu WSL2
Arduino IDE
Git
GitHub CLI nếu muốn push repo nhanh
Trình duyệt Chrome/Edge
```

Trong Ubuntu WSL:

```bash
sudo apt update
sudo apt install -y git unzip curl ca-certificates openssl python3 python3-venv python3-pip
```

Node.js cần bản 20 trở lên. Nếu `node -v` dưới 20, cài bằng `n`:

```bash
sudo apt install -y nodejs npm
sudo npm install -g n
sudo n 20.19.0
hash -r
node -v
npm -v
```

Docker Desktop cần bật WSL Integration cho Ubuntu distro đang dùng.

## 4. Copy project vào WSL

Nếu project đang ở Windows:

```text
C:\HocTap\TrienKhaiUngDungAIoT\VisionBot_MQTTS_Backend_Starter
```

Copy sang WSL:

```bash
mkdir -p ~/visionbot
cp -a /mnt/c/HocTap/TrienKhaiUngDungAIoT/VisionBot_MQTTS_Backend_Starter ~/visionbot/
cd ~/visionbot/VisionBot_MQTTS_Backend_Starter
ls
```

Cần thấy:

```text
backend  broker  frontend  scripts
```

Nếu `cp` báo không đọc được `broker/certs/ca.key` do permission, vẫn có thể chạy nếu còn đủ `ca.crt`, `server.crt`, `server.key`. `ca.key` chỉ cần khi tạo lại cert.

## 5. Broker MQTTS

### 5.1. Chạy broker

```bash
cd ~/visionbot/VisionBot_MQTTS_Backend_Starter/broker
docker compose down
docker compose up -d
docker ps
docker logs visionbot-mosquitto --tail 80
```

Log mong muốn:

```text
Opening ipv4 listen socket on port 8883
mosquitto version ... running
```

### 5.2. Khi đổi Wi-Fi/IP laptop

ESP32-CAM không dùng IP WSL kiểu `172.x.x.x`. ESP32-CAM dùng IP Wi-Fi của laptop, ví dụ:

```text
192.168.1.66
```

Nếu IP Wi-Fi đổi, tạo lại server cert có SAN IP mới:

```bash
cd ~/visionbot/VisionBot_MQTTS_Backend_Starter
./scripts/create_broker_certs_wsl.sh
```

Nhập IP Wi-Fi laptop khi script hỏi. Sau đó restart broker:

```bash
cd broker
docker compose down
docker compose up -d
```

Lấy Root CA để dán vào ESP32-CAM config portal:

```bash
cat broker/certs/ca.crt
```

Nếu portal chỉ nhận một dòng, chuyển newline thành `\n`:

```bash
python3 - <<'PY'
from pathlib import Path
p = Path('broker/certs/ca.crt')
print(p.read_text().replace('\r','').replace('\n','\\n'))
PY
```

## 6. ESP32-CAM config portal

Khi firmware mở portal, nhập:

```text
Wi-Fi SSID: Wi-Fi của bạn
Wi-Fi password: mật khẩu Wi-Fi
MQTT host: IP Wi-Fi laptop, ví dụ 192.168.1.66
MQTT port: 8883
MQTT username: VB-CAM-E9BFB4
MQTT password: robot-pass-123
MQTT base topic: visionbot
Root CA: nội dung ca.crt
```

Không nhập `localhost` cho ESP32-CAM. `localhost` chỉ dùng cho backend khi backend và broker chạy cùng máy.

## 7. Backend FastAPI

### 7.1. Cài backend

```bash
cd ~/visionbot/VisionBot_MQTTS_Backend_Starter
./scripts/install_backend_wsl.sh
```

Script sẽ tạo:

```text
backend/.venv
backend/.env
```

Mở `backend/.env` nếu muốn sửa broker/model:

```bash
nano backend/.env
```

### 7.2. Chạy backend CPU/GPU auto

```bash
cd ~/visionbot/VisionBot_MQTTS_Backend_Starter
./scripts/run_backend_wsl_auto.sh
```

Script tự kiểm tra:

```text
Có NVIDIA CUDA trong WSL -> cho phép AI_DEVICE=auto/cuda
Không có CUDA -> dùng CPU defaults: yolo11n.onnx imgsz 320
```

Kiểm tra runtime:

```bash
./scripts/check_ai_runtime.sh
```

Test backend:

```bash
curl http://localhost:8000/api/health
```

Nếu thấy `mqtt_connected: true` và robot online trong UI là ổn.

### 7.3. Chạy CPU cố định

Máy không GPU nên có thể dùng:

```bash
./scripts/run_backend_wsl_cpu.sh
```

Cấu hình CPU khuyên dùng:

```text
Detector: yolo11n.onnx
imgsz: 320 hoặc 416
conf: 0.25
interval: 0.20
VLM: SmolVLM 500M hoặc Florence-2 base khi cần hỏi đáp
```

### 7.4. GPU NVIDIA tùy chọn

Nếu máy khác có NVIDIA GPU:

```bash
nvidia-smi
cd backend
source .venv/bin/activate
python - <<'PY'
import torch
print(torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
PY
```

Nếu CUDA hoạt động, có thể dùng `backend/.env.gpu.example`:

```bash
cp backend/.env.gpu.example backend/.env
./scripts/run_backend_wsl_auto.sh
```

Nếu `torch.cuda.is_available()` vẫn `False`, máy đó đang dùng PyTorch CPU hoặc WSL/GPU driver chưa đúng. Khi đó quay lại CPU ONNX.

## 8. Frontend React/Vite

Cài frontend:

```bash
cd ~/visionbot/VisionBot_MQTTS_Backend_Starter
./scripts/install_frontend_wsl.sh
```

Chạy frontend:

```bash
./scripts/run_frontend_wsl.sh
```

Mở trên laptop:

```text
http://localhost:5173
```

Mở từ điện thoại cùng Wi-Fi:

```text
http://<IP-Wi-Fi-laptop>:5173
```

Nếu dùng điện thoại, sửa `frontend/.env`:

```text
VITE_API_BASE=http://192.168.1.66:8000
VITE_DEVICE_ID=VB-CAM-E9BFB4
```

Sau đó restart frontend.

## 9. Ý nghĩa nút trong UI

```text
Làm mới      -> refresh health/state/AI status
Manual mode  -> thoát estop, cho phép robot nhận drive
Dừng khẩn cấp -> emergency stop, muốn chạy lại cần Manual mode
Video raw    -> stream camera gốc từ ESP32-CAM
AI overlay   -> stream camera có bbox detector
Detect       -> chạy detector một frame
VLM          -> dùng VLM nhìn frame hiện tại và trả lời
Tắt stream   -> ngắt receiver camera backend
Tải model    -> preload detector/VLM đang chọn
Áp dụng      -> lưu detector/imgsz/conf/interval/VLM đang chọn vào backend
```

Điều khiển robot:

```text
Giữ W / nút Tiến  -> robot tiến, frontend gửi keepalive drive
Thả tay           -> frontend gửi stop
Mất mạng/browser tắt -> ESP tự dừng nhờ TTL
A/D               -> trái/phải đã được sửa ở frontend nếu phần cứng bị đảo
```

## 10. AI model trong UI

### Detector realtime

Nhóm này dùng cho bbox/nhãn, có thể chạy liên tục:

```text
ONNX — YOLO11n realtime        nhanh nhất CPU
ONNX — YOLO11n cân bằng        chính xác hơn chút
ONNX — YOLO11s mạnh hơn        nặng hơn
ONNX — YOLOv8n nhẹ             fallback ổn định
ONNX — YOLOv8s cân bằng        so sánh YOLOv8/YOLO11
SSD MobileNetV3 320            non-YOLO detector nhẹ
Faster R-CNN MobileNetV3 320   non-YOLO chính xác hơn, chậm hơn
RetinaNet / FCOS               model nặng để benchmark
```

### VLM hỏi đáp theo frame

Nhóm này dùng để hỏi đáp/caption/nhận dạng sâu, không nên chạy realtime liên tục trên CPU:

```text
SmolVLM 500M          nhẹ nhất
SmolVLM2 500M         thử so sánh
SmolVLM2 2.2B         mạnh hơn, chậm hơn
Florence-2 base       có OD/grounding/bbox theo prompt
Florence-2 large      mạnh hơn base
Qwen2.5-VL 3B         nhận dạng/localization tốt nhưng chậm CPU
PaliGemma2 3B         VLM 3B để so sánh
```

## 11. FPS/latency nên hiểu thế nào

```text
Stream FPS       FPS camera/backend nhận được
Frame KB         kích thước JPEG frame mới nhất
Infer            latency lần detector gần nhất
Avg              latency trung bình detector model đang chọn
AI FPS           ước lượng 1000 / avg_ms của detector
VLM latency      thời gian một lượt VLM trả lời
VLM FPS          chỉ để benchmark; VLM CPU thường rất thấp
```

Với CPU laptop:

```text
Stream FPS 18-30 là ổn
YOLO ONNX 320 dưới 100 ms là ổn
VLM vài chục giây/lượt là bình thường nếu CPU yếu
```

## 12. GitHub upload an toàn

Không upload secret/model/cache:

```text
broker/certs/*.key
broker/passwords
backend/.env
frontend/.env
backend/.venv
frontend/node_modules
backend/models
*.pt
*.onnx
*.safetensors
```

Patch đã có `.gitignore`, nhưng vẫn kiểm tra trước khi commit:

```bash
cd ~/visionbot/VisionBot_MQTTS_Backend_Starter
git status --ignored
```

Tạo repo GitHub:

```bash
sudo apt install -y git gh
gh auth login

git init
git branch -M main
git add .
git status
git commit -m "Initial VisionBot AIoT dashboard"
gh repo create VisionBot --private --source=. --remote=origin --push
```

Muốn public:

```bash
gh repo create VisionBot --public --source=. --remote=origin --push
```

Nếu lỡ add file nhạy cảm trước khi `.gitignore` có hiệu lực:

```bash
git rm -r --cached .
git add .
git status
git commit -m "Clean VisionBot project"
git push -u origin main
```

## 13. Lỗi thường gặp

### Frontend chọn model nhưng bị quay lại mặc định

Dùng patch v1.1.5 trở lên. Nguyên nhân cũ là frontend polling `/ai/status` và tự sync lại model đang chạy ở backend trước khi người dùng bấm `Áp dụng`.

### No module named ultralytics

```bash
cd backend
source .venv/bin/activate
pip install --upgrade -r requirements-ai.txt
```

### VLM quá chậm

Bình thường nếu CPU. Dùng VLM theo lượt hỏi đáp, không chạy realtime.

### ESP không kết nối MQTTS

Kiểm tra:

```text
ESP MQTT host = IP Wi-Fi laptop
server.crt SAN có IP Wi-Fi đó
ESP Root CA = ca.crt hiện tại
broker docker expose 0.0.0.0:8883
firewall mở port 8883
```

### Điện thoại không mở frontend/backend

Chạy backend/frontend với `--host 0.0.0.0`, dùng IP Wi-Fi laptop, không dùng `localhost` trên điện thoại.

---

## v1.1.6 Stable AI Stream Note

Nếu bản multi-model trước đó làm AI overlay lag hoặc báo lỗi kiểu:

```text
INVALID_ARGUMENT: Got 416 Expected 320
```

hãy dùng bản v1.1.6. Bản này rút gọn model để giữ ổn định:

- Realtime CPU: `ONNX — YOLO11n realtime`, `imgsz=320`
- Cân bằng: `ONNX — YOLO11n cân bằng`, `imgsz=416`
- Fallback: `ONNX — YOLOv8n fallback`, `imgsz=416`
- Non-YOLO: `SSD MobileNetV3 320`

VLM chỉ dùng để hỏi một frame hiện tại. Không dùng VLM để stream realtime trên CPU.
