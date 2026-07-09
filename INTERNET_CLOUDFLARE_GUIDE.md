# VisionBot Internet Mode With Cloudflare Tunnel

This mode removes the dependency on ESP32-CAM and laptop being on the same Wi-Fi.

Camera path:

```text
ESP32-CAM -> WSS Cloudflare Tunnel -> camera-relay -> backend -> frontend
```

Control path:

```text
frontend -> backend -> MQTT broker cloud/VPS -> ESP32-CAM
```

Cloudflare Tunnel is good for HTTPS/WSS camera relay. It does not expose raw MQTT port `1883` on the free quick tunnel, so MQTT still needs a cloud/VPS broker.

## Option A - Fast Demo Without VPS

Use Cloudflare Tunnel for camera and a public MQTT broker for command testing.

Terminal 1:

```bash
cd ~/visionbot/VisionBot-main
bash scripts/install_camera_relay_wsl.sh
CAMERA_TOKEN=demo_camera BACKEND_TOKEN=demo_backend bash scripts/run_camera_relay_wsl.sh
```

PowerShell:

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://localhost:8001
```

Copy the generated URL, for example:

```text
https://abc.trycloudflare.com
```

ESP32-CAM setup portal:

```text
MQTT broker host/IP: broker.emqx.io
MQTT broker port: 1883
MQTT username:
MQTT password:
Camera relay host/domain: abc.trycloudflare.com
Camera relay port: 443
Camera relay TLS: 1
Camera relay token: demo_camera
```

Backend:

```bash
cd ~/visionbot/VisionBot-main
MQTT_HOST=broker.emqx.io \
MQTT_PORT=1883 \
CAMERA_RELAY_WS='wss://abc.trycloudflare.com/camera/ws/subscribe/{device_id}' \
CAMERA_RELAY_TOKEN=demo_backend \
bash scripts/run_backend_wsl_cpu.sh
```

Frontend:

```bash
cd ~/visionbot/VisionBot-main
VITE_API_BASE=http://localhost:8000 VITE_DEVICE_ID=VB-CAM-E9BFB4 bash scripts/run_frontend_wsl.sh
```

## Option B - Proper VPS

Use `deploy/vps`:

```bash
cd deploy/vps
cp .env.example .env
docker compose up -d --build
```

Then point ESP and backend to your VPS domain:

```text
Camera push: wss://your-domain.com/camera/ws/push/<device_id>?token=...
Backend subscribe: wss://your-domain.com/camera/ws/subscribe/{device_id}?token=...
MQTT: your-domain.com:1883
```

## Quick Checks

Relay health:

```bash
curl https://abc.trycloudflare.com/camera/health
```

Backend health:

```bash
curl http://localhost:8000/api/health
```

Camera session:

```bash
curl http://localhost:8000/api/robots/VB-CAM-E9BFB4/ai/status
```

The camera session should show:

```json
{
  "running": true,
  "connected": true,
  "frame_count": 10
}
```
