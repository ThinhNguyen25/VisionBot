# VisionBot VPS Deployment

This folder runs the Internet-facing relay layer:

- `mosquitto`: MQTT broker for command/status/telemetry.
- `camera-relay`: WebSocket binary JPEG relay.
- `caddy`: HTTPS/WSS reverse proxy for `/camera/*`.

## 1. Create MQTT users

From `deploy/vps` on the VPS:

```bash
cp .env.example .env
mkdir -p mosquitto/config
docker run --rm -it -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -c /mosquitto/config/passwd backend_user
docker run --rm -it -v "$PWD/mosquitto/config:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd /mosquitto/config/passwd robot01_user
```

## 2. Edit `.env`

```env
VISIONBOT_DOMAIN=your-domain.example.com
CAMERA_TOKEN=change_camera_token
BACKEND_TOKEN=change_backend_token
```

Point the domain DNS A record to the VPS IP.

## 3. Start services

```bash
docker compose up -d --build
docker compose logs -f camera-relay mosquitto caddy
```

Health check:

```bash
curl https://your-domain.example.com/camera/health
```

## 4. ESP32-CAM settings

In the ESP setup portal:

```text
MQTT broker host/IP: your-domain.example.com
MQTT broker port: 1883
MQTT username: robot01_user
MQTT password: your password
Camera relay host/domain: your-domain.example.com
Camera relay port: 443
Camera relay TLS: 1
Camera relay token: CAMERA_TOKEN value
```

## 5. Backend settings

On the laptop/server:

```bash
MQTT_HOST=your-domain.example.com \
MQTT_PORT=1883 \
MQTT_USERNAME=backend_user \
MQTT_PASSWORD='your password' \
CAMERA_RELAY_WS='wss://your-domain.example.com/camera/ws/subscribe/{device_id}' \
CAMERA_RELAY_TOKEN='BACKEND_TOKEN value' \
bash scripts/run_backend_wsl_cpu.sh
```
