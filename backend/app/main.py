import json
import os
import threading
import time
from io import BytesIO
from pathlib import Path
import shutil
from collections import deque
from typing import Any, Generator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
import paho.mqtt.client as mqtt
import websocket


APP_VERSION = "1.2.0-local-lan-compose"

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
BASE_TOPIC = os.getenv("MQTT_BASE_TOPIC", "visionbot")
COMMAND_ACK_TIMEOUT_S = float(os.getenv("COMMAND_ACK_TIMEOUT_S", "3.0"))
COMMAND_ACK_OK_STATUSES = {"accepted", "executed", "ok"}

AI_ENABLE_YOLO = os.getenv("AI_ENABLE_YOLO", "1") == "1"
AI_YOLO_MODEL = os.getenv("AI_YOLO_MODEL", "yolo11n.onnx")
AI_CONF_THRESHOLD = float(os.getenv("AI_CONF_THRESHOLD", "0.25"))
AI_YOLO_IMGSZ = int(os.getenv("AI_YOLO_IMGSZ", "320"))
AI_DETECT_INTERVAL_S = float(os.getenv("AI_DETECT_INTERVAL_S", "0.20"))
AI_ENABLE_VLM = os.getenv("AI_ENABLE_VLM", "1") == "1"
AI_VLM_MODEL = os.getenv("AI_VLM_MODEL", "HuggingFaceTB/SmolVLM-500M-Instruct")
AI_VLM_MAX_NEW_TOKENS = int(os.getenv("AI_VLM_MAX_NEW_TOKENS", "140"))
AI_MODEL_DIR = Path(os.getenv("AI_MODEL_DIR", "models"))
AI_DEVICE = os.getenv("AI_DEVICE", "auto").strip().lower()  # auto/cpu/cuda

DETECTOR_PRESETS = [
    # Keep this list intentionally small and stable. Heavy/non-realtime models caused
    # stream lag and confusing benchmark numbers on CPU-only laptops.
    {"id": "yolo11n.onnx", "label": "ONNX — YOLO11n realtime", "family": "yolo", "speed": "realtime", "recommended_imgsz": 320, "note": "khuyến nghị: nhanh nhất, ổn nhất cho realtime CPU"},
    {"id": "yolo11n.onnx", "label": "ONNX — YOLO11n cân bằng", "family": "yolo", "speed": "balanced", "recommended_imgsz": 320, "note": "giữ 320 vì yolo11n.onnx export cố định input 320"},
    {"id": "yolov8n.onnx", "label": "ONNX — YOLOv8n fallback", "family": "yolo", "speed": "fallback", "recommended_imgsz": 416, "note": "fallback nhẹ nếu YOLO11n lỗi"},
    {"id": "torchvision:ssdlite320_mobilenet_v3_large", "label": "SSD MobileNetV3 320 — không YOLO", "family": "ssd_mobilenet", "speed": "fast", "recommended_imgsz": 320, "note": "detector deep-learning khác YOLO, bbox COCO, CPU"},
]
VLM_PRESETS = [
    {"id": "HuggingFaceTB/SmolVLM2-500M-Video-Instruct", "label": "SmolVLM2 500M — nhẹ nhất", "params": "0.5B", "bbox": "không trực tiếp"},
    {"id": "HuggingFaceTB/SmolVLM-500M-Instruct", "label": "SmolVLM 500M — ổn định", "params": "0.5B", "bbox": "không trực tiếp"},
]


app = FastAPI(title="VisionBot Backend API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only. Tighten this for production.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

robots: dict[str, dict[str, Any]] = {}
events: list[dict[str, Any]] = []
mqtt_connected = False

ack_lock = threading.Lock()
pending_cmd_acks: dict[tuple[str, int], dict[str, Any]] = {}
latest_cmd_acks: dict[str, list[dict[str, Any]]] = {}


def now_ms() -> int:
    return int(time.time() * 1000)


COMMAND_SEQ_MAX = 2_147_483_647


def command_seq() -> int:
    """Return a positive sequence safe for ESP32/ArduinoJson uint32 handling."""
    seq = now_ms() % COMMAND_SEQ_MAX
    return seq if seq > 0 else 1


def normalize_command_seq(value: Any) -> int:
    try:
        seq = int(value or 0)
    except Exception:
        seq = 0
    if seq <= 0:
        return command_seq()
    if seq >= COMMAND_SEQ_MAX:
        seq = seq % COMMAND_SEQ_MAX
    return seq if seq > 0 else 1


def preferred_ai_device() -> str:
    """Return cuda only when explicitly available; otherwise safe CPU fallback."""
    if AI_DEVICE in {"cpu", "none"}:
        return "cpu"
    if AI_DEVICE in {"cuda", "gpu", "auto"}:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
    return "cpu"


def ai_runtime_info() -> dict[str, Any]:
    info = {"requested_device": AI_DEVICE, "selected_device": preferred_ai_device(), "cuda_available": False, "gpu_name": None}
    try:
        import torch
        info["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            info["gpu_name"] = torch.cuda.get_device_name(0)
        info["torch_version"] = getattr(torch, "__version__", None)
    except Exception as exc:
        info["torch_error"] = str(exc)
    return info


class CameraSession:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.running = False
        self.thread: threading.Thread | None = None
        self.latest_jpeg: bytes | None = None
        self.latest_frame_ms: int | None = None
        self.frame_count = 0
        self.frame_times_ms: deque[int] = deque(maxlen=180)
        self.last_error: str | None = None
        self.connected = False
        self.lock = threading.Lock()

    def _fps_locked(self) -> float:
        if len(self.frame_times_ms) < 2:
            return 0.0
        span_ms = self.frame_times_ms[-1] - self.frame_times_ms[0]
        if span_ms <= 0:
            return 0.0
        return round((len(self.frame_times_ms) - 1) * 1000.0 / span_ms, 2)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            size = len(self.latest_jpeg) if self.latest_jpeg else 0
            return {
                "running": self.running,
                "connected": self.connected,
                "frame_count": self.frame_count,
                "stream_fps": self._fps_locked(),
                "latest_frame_ms": self.latest_frame_ms,
                "latest_frame_age_ms": None if self.latest_frame_ms is None else now_ms() - self.latest_frame_ms,
                "latest_frame_size_bytes": size,
                "latest_frame_kb": round(size / 1024.0, 1) if size else 0,
                "last_error": self.last_error,
            }

    def latest_frame(self) -> bytes | None:
        with self.lock:
            return self.latest_jpeg

    def set_frame(self, data: bytes) -> None:
        t = now_ms()
        with self.lock:
            self.latest_jpeg = data
            self.latest_frame_ms = t
            self.frame_count += 1
            self.frame_times_ms.append(t)
            self.connected = True
            self.last_error = None

    def set_error(self, error: str) -> None:
        with self.lock:
            self.last_error = error
            self.connected = False

    def stop(self) -> None:
        self.running = False


camera_sessions: dict[str, CameraSession] = {}


class DriveCommand(BaseModel):
    seq: int = Field(default_factory=command_seq)
    cmd: str | None = None
    left: float | None = None
    right: float | None = None
    ttl_ms: int = 900
    mode: str = "manual"

    @field_validator("seq", mode="before")
    @classmethod
    def _normalize_seq(cls, value: Any) -> int:
        return normalize_command_seq(value)

    @field_validator("ttl_ms")
    @classmethod
    def _ttl_bounds(cls, value: int) -> int:
        # Frontend sends keep-alive every ~300ms. TTL is the safety net.
        return max(150, min(int(value), 2000))


class ServoCommand(BaseModel):
    seq: int = Field(default_factory=command_seq)
    angle: int

    @field_validator("seq", mode="before")
    @classmethod
    def _normalize_seq(cls, value: Any) -> int:
        return normalize_command_seq(value)


class StopCommand(BaseModel):
    seq: int = Field(default_factory=command_seq)
    reason: str = "backend_stop"

    @field_validator("seq", mode="before")
    @classmethod
    def _normalize_seq(cls, value: Any) -> int:
        return normalize_command_seq(value)


class AIConfigUpdate(BaseModel):
    enable_yolo: bool | None = None
    yolo_model: str | None = None
    yolo_imgsz: int | None = None
    conf_threshold: float | None = None
    detect_interval_s: float | None = None
    enable_vlm: bool | None = None
    vlm_model: str | None = None


class AIAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=600)


def topic_for(device_id: str, suffix: str) -> str:
    return f"{BASE_TOPIC}/{device_id}/{suffix}"


def mqtt_is_ready() -> bool:
    return mqtt_connected and mqtt_client.is_connected()


def publish_mqtt_or_503(topic: str, payload: dict[str, Any], qos: int = 1, timeout_s: float = 2.0) -> dict[str, Any]:
    if not mqtt_is_ready():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "mqtt_not_connected",
                "message": "Backend is not connected to the MQTT broker, so the command was not sent.",
                "mqtt_connected_flag": mqtt_connected,
                "mqtt_client_connected": mqtt_client.is_connected(),
            },
        )

    try:
        info = mqtt_client.publish(topic, json.dumps(payload), qos=qos, retain=False)
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"error": "mqtt_publish_exception", "message": str(exc), "topic": topic, "payload": payload}) from exc

    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise HTTPException(status_code=503, detail={"error": "mqtt_publish_rejected", "message": mqtt.error_string(info.rc), "rc": info.rc, "topic": topic, "payload": payload})

    if qos > 0:
        try:
            info.wait_for_publish(timeout=timeout_s)
        except Exception as exc:
            raise HTTPException(status_code=504, detail={"error": "mqtt_publish_wait_exception", "message": str(exc), "mid": info.mid, "topic": topic, "payload": payload}) from exc

        if not info.is_published():
            raise HTTPException(status_code=504, detail={"error": "mqtt_publish_timeout", "message": f"MQTT publish was queued but not acknowledged within {timeout_s:.1f}s.", "mid": info.mid, "topic": topic, "payload": payload})

    return {"ok": True, "topic": topic, "payload": payload, "mqtt": {"qos": qos, "mid": info.mid, "published": info.is_published(), "rc": info.rc}}


def register_pending_cmd_ack(device_id: str, seq: int) -> tuple[tuple[str, int], threading.Event]:
    key = (device_id, int(seq))
    event = threading.Event()
    with ack_lock:
        if key in pending_cmd_acks:
            raise HTTPException(status_code=409, detail={"error": "duplicate_pending_command_seq", "device_id": device_id, "seq": seq})
        pending_cmd_acks[key] = {"event": event, "ack": None, "created_ms": now_ms()}
    return key, event


def clear_pending_cmd_ack(key: tuple[str, int]) -> None:
    with ack_lock:
        pending_cmd_acks.pop(key, None)


def pending_command_ack_count() -> int:
    with ack_lock:
        return len(pending_cmd_acks)


def pending_command_ack_snapshot(device_id: str) -> list[dict[str, Any]]:
    with ack_lock:
        return [{"device_id": did, "seq": seq, "created_ms": item.get("created_ms")} for (did, seq), item in pending_cmd_acks.items() if did == device_id]


def remember_cmd_ack(device_id: str, ack: dict[str, Any]) -> None:
    try:
        seq = int(ack.get("seq") or 0)
    except Exception:
        seq = 0

    ack["_received_ms"] = now_ms()
    latest = latest_cmd_acks.setdefault(device_id, [])
    latest.append(ack)
    del latest[:-100:]

    robot = robots.setdefault(device_id, {"device_id": device_id, "online": True, "state": {}, "telemetry": {}, "events": [], "last_seen_ms": now_ms()})
    robot["online"] = True
    robot["last_seen_ms"] = now_ms()
    robot["last_cmd_ack"] = ack
    robot["cmd_acks"] = latest[-20:]

    if seq <= 0:
        return
    key = (device_id, seq)
    with ack_lock:
        pending = pending_cmd_acks.get(key)
        if pending is not None:
            pending["ack"] = ack
            pending["event"].set()


def publish_command_and_wait_robot_ack(device_id: str, command_name: str, topic: str, payload: dict[str, Any], qos: int = 1, publish_timeout_s: float = 2.0, ack_timeout_s: float = COMMAND_ACK_TIMEOUT_S) -> dict[str, Any]:
    try:
        seq = int(payload.get("seq") or 0)
    except Exception:
        seq = 0
    if seq <= 0:
        raise HTTPException(status_code=400, detail={"error": "missing_command_seq", "payload": payload})

    pending_key, ack_event = register_pending_cmd_ack(device_id, seq)
    try:
        publish_result = publish_mqtt_or_503(topic, payload, qos=qos, timeout_s=publish_timeout_s)
        ack_received = ack_event.wait(timeout=ack_timeout_s)
        with ack_lock:
            pending = pending_cmd_acks.get(pending_key, {})
            robot_ack = pending.get("ack")

        if not ack_received or not robot_ack:
            raise HTTPException(status_code=504, detail={"error": "robot_ack_timeout", "message": f"Command reached the MQTT broker, but robot did not publish cmd_ack within {ack_timeout_s:.1f}s.", "device_id": device_id, "seq": seq, "command": command_name, "topic": topic, "payload": payload, "mqtt": publish_result.get("mqtt")})

        ack_status = str(robot_ack.get("status", "")).lower()
        if ack_status not in COMMAND_ACK_OK_STATUSES:
            raise HTTPException(status_code=409, detail={"error": "robot_rejected_command", "device_id": device_id, "seq": seq, "command": command_name, "payload": payload, "mqtt": publish_result.get("mqtt"), "robot_ack": robot_ack})

        return {"ok": True, "device_id": device_id, "seq": seq, "command": command_name, "topic": topic, "payload": payload, "mqtt": publish_result.get("mqtt"), "robot_ack": robot_ack}
    finally:
        clear_pending_cmd_ack(pending_key)


def safe_json(payload: bytes) -> dict[str, Any]:
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {"raw": payload.decode("utf-8", errors="replace")}


def upsert_robot(device_id: str, data: dict[str, Any], kind: str) -> None:
    r = robots.setdefault(device_id, {"device_id": device_id, "online": False, "state": {}, "telemetry": {}, "events": [], "last_seen_ms": None})
    r["last_seen_ms"] = now_ms()
    if kind == "state":
        r["state"] = data
        r["online"] = bool(data.get("online", True))
        for key in ["ip", "http_base", "stream_url", "robot_id", "firmware", "camera_ready", "mqtt_connected"]:
            if key in data:
                r[key] = data[key]
    elif kind == "telemetry":
        r["telemetry"] = data
        r["online"] = True
        network = data.get("network") if isinstance(data.get("network"), dict) else {}
        camera = data.get("camera") if isinstance(data.get("camera"), dict) else {}
        if "ip" in network:
            r["ip"] = network["ip"]
        if "stream_url" in camera:
            r["stream_url"] = camera["stream_url"]
        if "ready" in camera:
            r["camera_ready"] = camera["ready"]
        if "mqtt_connected" in network:
            r["mqtt_connected"] = network["mqtt_connected"]
    elif kind == "event":
        r["events"].append(data)
        r["events"] = r["events"][-100:]
        events.append(data)
        del events[:-500]


def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None):
    global mqtt_connected
    mqtt_connected = True
    client.subscribe(f"{BASE_TOPIC}/+/state", qos=1)
    client.subscribe(f"{BASE_TOPIC}/+/telemetry", qos=0)
    client.subscribe(f"{BASE_TOPIC}/+/event", qos=0)
    client.subscribe(f"{BASE_TOPIC}/+/cmd_ack", qos=1)
    print(f"[MQTT] connected to {MQTT_HOST}:{MQTT_PORT}")
    print(f"[MQTT] subscribed {BASE_TOPIC}/+/state telemetry event cmd_ack")


def on_disconnect(client: mqtt.Client, userdata, reason_code, properties=None):
    global mqtt_connected
    mqtt_connected = False
    print(f"[MQTT] disconnected: {reason_code}")


def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
    parts = msg.topic.split("/")
    if len(parts) < 3:
        return
    device_id = parts[1]
    kind = parts[2]
    data = safe_json(msg.payload)
    if isinstance(data, dict):
        data["_topic"] = msg.topic
        data["_received_ms"] = now_ms()
    if kind in {"state", "telemetry", "event"}:
        upsert_robot(device_id, data, kind)
        print(f"[MQTT] {kind} from {device_id}")
    elif kind == "cmd_ack":
        remember_cmd_ack(device_id, data)
        print(f"[MQTT] cmd_ack from {device_id}: seq={data.get('seq')} status={data.get('status')}")


mqtt_client = mqtt.Client(client_id="visionbot-backend", protocol=mqtt.MQTTv5)
if MQTT_USERNAME:
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message = on_message


def mqtt_loop():
    while True:
        try:
            mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            mqtt_client.loop_forever()
        except Exception as e:
            print(f"[MQTT] connect/loop error: {e}")
            time.sleep(3)


def camera_loop(session: CameraSession) -> None:
    print(f"[CAM] receiver thread started: {session.device_id}")
    ws = None
    while session.running:
        robot = robots.get(session.device_id)
        stream_url = robot.get("stream_url") if robot else None
        if not stream_url:
            session.set_error("missing_stream_url")
            time.sleep(1)
            continue
        try:
            print(f"[CAM] connecting {session.device_id}: {stream_url}")
            ws = websocket.create_connection(stream_url, timeout=5)
            while session.running:
                data = ws.recv()
                if isinstance(data, bytes) and data[:2] == b"\xff\xd8":
                    session.set_frame(data)
        except Exception as e:
            session.set_error(str(e))
            time.sleep(1)
        finally:
            try:
                if ws:
                    ws.close()
            except Exception:
                pass
    print(f"[CAM] receiver thread stopped: {session.device_id}")


def get_camera_session(device_id: str) -> CameraSession:
    if device_id not in camera_sessions:
        camera_sessions[device_id] = CameraSession(device_id)
    return camera_sessions[device_id]


def start_camera_session(device_id: str) -> CameraSession:
    if device_id not in robots:
        raise HTTPException(status_code=404, detail="robot_not_found")
    session = get_camera_session(device_id)
    if session.running:
        return session
    session.running = True
    session.thread = threading.Thread(target=camera_loop, args=(session,), daemon=True)
    session.thread.start()
    return session


def mjpeg_generator(device_id: str) -> Generator[bytes, None, None]:
    session = start_camera_session(device_id)
    last_seen_count = -1
    while session.running:
        with session.lock:
            frame = session.latest_jpeg
            count = session.frame_count
        if frame is not None and count != last_seen_count:
            last_seen_count = count
            yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n" + frame + b"\r\n"
        else:
            time.sleep(0.03)


# ----------------------------- AI layer -----------------------------

def _decode_jpeg_to_cv2(jpeg: bytes):
    import cv2
    import numpy as np
    arr = np.frombuffer(jpeg, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _encode_cv2_to_jpeg(img, quality: int = 80) -> bytes:
    import cv2
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    return buf.tobytes()


def _is_onnx_model(model_name: str) -> bool:
    return str(model_name).lower().endswith(".onnx")


def _is_torchvision_detector(model_name: str) -> bool:
    return str(model_name).lower().startswith("torchvision:")

def _torchvision_model_key(model_name: str) -> str:
    return str(model_name).split(":", 1)[1].strip().lower()

def _load_torchvision_detector(model_name: str):
    """Load a non-YOLO detector from torchvision.

    These models are not ONNX in this dev path, but they are real deep-learning
    detectors with bbox + labels. They are useful for comparing non-YOLO behavior
    on CPU.
    """
    import torch
    key = _torchvision_model_key(model_name)
    if key == "ssdlite320_mobilenet_v3_large":
        from torchvision.models.detection import ssdlite320_mobilenet_v3_large, SSDLite320_MobileNet_V3_Large_Weights
        weights = SSDLite320_MobileNet_V3_Large_Weights.DEFAULT
        model = ssdlite320_mobilenet_v3_large(weights=weights)
    elif key == "fasterrcnn_mobilenet_v3_large_320_fpn":
        from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_320_fpn, FasterRCNN_MobileNet_V3_Large_320_FPN_Weights
        weights = FasterRCNN_MobileNet_V3_Large_320_FPN_Weights.DEFAULT
        model = fasterrcnn_mobilenet_v3_large_320_fpn(weights=weights)
    elif key == "fasterrcnn_mobilenet_v3_large_fpn":
        from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_fpn, FasterRCNN_MobileNet_V3_Large_FPN_Weights
        weights = FasterRCNN_MobileNet_V3_Large_FPN_Weights.DEFAULT
        model = fasterrcnn_mobilenet_v3_large_fpn(weights=weights)
    elif key == "retinanet_resnet50_fpn":
        from torchvision.models.detection import retinanet_resnet50_fpn, RetinaNet_ResNet50_FPN_Weights
        weights = RetinaNet_ResNet50_FPN_Weights.DEFAULT
        model = retinanet_resnet50_fpn(weights=weights)
    elif key == "fcos_resnet50_fpn":
        from torchvision.models.detection import fcos_resnet50_fpn, FCOS_ResNet50_FPN_Weights
        weights = FCOS_ResNet50_FPN_Weights.DEFAULT
        model = fcos_resnet50_fpn(weights=weights)
    else:
        raise ValueError(f"unsupported torchvision detector: {model_name}")
    model.eval()
    model.to(torch.device(preferred_ai_device()))
    categories = list(getattr(weights, "meta", {}).get("categories", []))
    return model, categories

def _model_metric_key(kind: str, model: str, imgsz: int | None = None) -> str:
    if imgsz:
        return f"{kind}:{model}@{imgsz}"
    return f"{kind}:{model}"

def _update_metric(bucket: dict[str, Any], key: str, latency_ms: float, count_delta: int = 1, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    item = bucket.setdefault(key, {"count": 0, "last_ms": None, "avg_ms": None, "min_ms": None, "max_ms": None, "approx_fps": 0.0})
    n = int(item.get("count") or 0)
    avg = float(item.get("avg_ms") or latency_ms)
    new_n = n + count_delta
    new_avg = latency_ms if n == 0 else ((avg * n) + latency_ms) / new_n
    item.update({
        "count": new_n,
        "last_ms": round(float(latency_ms), 1),
        "avg_ms": round(float(new_avg), 1),
        "min_ms": round(float(latency_ms if item.get("min_ms") is None else min(float(item["min_ms"]), latency_ms)), 1),
        "max_ms": round(float(latency_ms if item.get("max_ms") is None else max(float(item["max_ms"]), latency_ms)), 1),
        "approx_fps": round(1000.0 / new_avg, 2) if new_avg > 0 else 0.0,
        "updated_ms": now_ms(),
    })
    if extra:
        item.update(extra)
    return item


def _onnx_target_path(model_name: str, imgsz: int) -> Path:
    stem = Path(model_name).stem
    # keep one ONNX per imgsz because fixed-shape export is faster than dynamic on CPU
    return AI_MODEL_DIR / "onnx" / f"{stem}-{int(imgsz)}.onnx"


def _resolved_onnx_imgsz(resolved_model: str | None, fallback: int) -> int:
    """Extract the fixed export size from names like yolo11n-320.onnx.

    Ultralytics ONNX exports in this project are fixed-shape for CPU speed.
    If the UI changes imgsz while a previous ONNX model is still loaded, passing
    the new size to a fixed old ONNX file causes:
      INVALID_ARGUMENT: Got 416 Expected 320
    This guard keeps overlay stable instead of breaking the video stream.
    """
    try:
        name = Path(str(resolved_model or "")).stem
        tail = name.rsplit("-", 1)[-1]
        if tail.isdigit():
            return int(tail)
    except Exception:
        pass
    return int(fallback)


def _export_onnx_if_needed(model_name: str, imgsz: int) -> str:
    """Return a local model path. If model_name is *.onnx and missing, export from matching *.pt.

    Example: yolo11n.onnx -> export yolo11n.pt to models/onnx/yolo11n-416.onnx.
    Fixed imgsz + simplify keeps CPU inference predictable.
    """
    name = str(model_name).strip()
    if not _is_onnx_model(name):
        return name

    path = Path(name)
    if path.exists():
        return str(path)

    target = _onnx_target_path(name, imgsz)
    if target.exists():
        return str(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    from ultralytics import YOLO
    base_pt = Path(name).with_suffix(".pt").name
    exporter = YOLO(base_pt)
    exported = exporter.export(format="onnx", imgsz=int(imgsz), simplify=True, dynamic=False, opset=12)
    exported_path = Path(str(exported))
    if not exported_path.exists():
        # Ultralytics commonly exports beside the .pt with same basename.
        exported_path = Path(base_pt).with_suffix(".onnx")
    if exported_path.exists() and exported_path.resolve() != target.resolve():
        shutil.copy2(exported_path, target)
    if not target.exists():
        raise RuntimeError(f"ONNX export finished but target file was not found: {target}")
    return str(target)



def _clean_vlm_text(raw: str) -> str:
    """Best-effort cleanup for chat-template model output.

    Some VLM decoders echo the prompt/chat template. Keep the final assistant-like
    answer compact for the frontend chat bubble, while preserving raw in JSON.
    """
    text = (raw or "").strip()
    for sep in ["Assistant:", "assistant", "<|assistant|>", "ASSISTANT:"]:
        if sep in text:
            text = text.split(sep)[-1].strip()
    # If model echoes a JSON object, extract the user-facing answer when possible.
    if '"answer_vi"' in text:
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                obj = json.loads(text[start:end + 1])
                if isinstance(obj, dict) and obj.get("answer_vi"):
                    text = str(obj["answer_vi"]).strip()
        except Exception:
            pass
    for fence in ["```json", "```"]:
        text = text.replace(fence, "").strip()
    # Avoid huge chat bubbles on weak machines.
    if len(text) > 1200:
        text = text[-1200:].strip()
    return text or "Mình chưa tạo được câu trả lời rõ ràng từ VLM."


def _pick_label(raw: str, labels: list[str], default: str = "uncertain", priority: list[str] | None = None) -> str:
    text = (raw or "").lower().strip()
    text = text.replace("-", "_").replace("slow down", "slow_down").replace("speed up", "speed_up")
    for ch in ".,:;()[]{}":
        text = text.replace(ch, " ")
    hits = []
    for label in labels:
        if f" {label.lower()} " in f" {text} ":
            hits.append(label)
    if priority:
        for label in priority:
            if label in hits:
                return label
    return hits[0] if len(hits) == 1 else default


def _has_any(text: str, words: list[str]) -> bool:
    low = (text or "").lower()
    return any(w in low for w in words)


def _caption_has_person(text: str) -> bool:
    return _has_any(text, ["person", "people", "man", "woman", "child", "human", "người"])


def _caption_has_vehicle(text: str) -> bool:
    return _has_any(text, ["car", "truck", "bus", "motorcycle", "bike", "bicycle", "vehicle", "xe"])


def _caption_has_obstacle(text: str) -> bool:
    return _has_any(text, ["obstacle", "chair", "box", "wall", "door", "table", "bench", "blocked", "barrier", "vật cản"])


def _normalize_robot_action(path_status: str, action: str, caption: str, detector_labels: set[str] | None = None) -> str:
    detector_labels = detector_labels or set()
    risky_labels = {"person", "car", "truck", "bus", "motorcycle", "bicycle", "dog", "cat", "chair", "bench"}
    if path_status == "blocked":
        return "stop"
    if detector_labels & risky_labels:
        return "slow_down"
    if _caption_has_person(caption) or _caption_has_vehicle(caption) or _caption_has_obstacle(caption):
        return "slow_down"
    if path_status in {"crowded", "uncertain"}:
        return "slow_down"
    if path_status == "clear" and action in {"stop", "turn"}:
        return "go"
    return action if action in {"go", "slow_down", "stop", "turn", "speed_up"} else "slow_down"


def _build_robot_answer_vi(caption: str, path_status: str, action: str, question: str | None = None) -> str:
    caption = _clean_vlm_text(caption).strip()
    if not caption:
        caption = "khung hình chưa đủ rõ để nhận diện chắc chắn"

    status_vi = {
        "clear": "Lối phía trước có vẻ khá thoáng.",
        "crowded": "Phía trước hơi đông hoặc có nhiều vật thể gần robot.",
        "blocked": "Phía trước có dấu hiệu bị chắn, robot không nên đi thẳng.",
        "uncertain": "Khung hình chưa đủ chắc chắn, robot nên thận trọng.",
    }.get(path_status, "Khung hình chưa đủ chắc chắn, robot nên thận trọng.")

    advice_vi = {
        "go": "Có thể đi tiếp chậm rãi và tiếp tục quan sát.",
        "slow_down": "Nên giảm tốc, giữ khoảng cách và quan sát thêm trước khi tiến.",
        "stop": "Nên dừng lại để tránh va chạm.",
        "turn": "Nên rẽ hoặc đổi hướng để tránh vùng phía trước.",
        "speed_up": "Chỉ nên tăng tốc nhẹ nếu người điều khiển xác nhận đường thật sự trống.",
    }.get(action, "Nên đi chậm và quan sát thêm.")

    extra = ""
    if question:
        extra = f"\n\nTrả lời câu hỏi: {question.strip()}\nMình dựa trên frame hiện tại; nếu hình mờ hoặc robot đang di chuyển nhanh thì nên kiểm tra lại bằng Video raw."

    return f"Phía trước: {caption}\n\nTình trạng: {status_vi}\n\nLời khuyên: {advice_vi}{extra}"


def _robot_chat_prompt(question: str | None = None) -> str:
    user_question = (question or "").strip()
    task = user_question[:600] if user_question else "Hãy phân tích khung hình hiện tại cho người đang điều khiển robot."
    return (
        "You are the vision assistant for a small ESP32-CAM robot.\n"
        "Look at the front-camera image and answer in natural Vietnamese.\n"
        "Do not output JSON, markdown tables, code blocks, or raw debug fields.\n"
        "Use this exact friendly structure:\n"
        "Phía trước: one short sentence describing the scene, main objects, people, vehicles, or obstacles.\n"
        "Tình trạng: choose clear, crowded, blocked, or uncertain, then explain briefly.\n"
        "Lời khuyên: choose go, slow_down, stop, or turn, then give a safe driving suggestion.\n"
        "If the image is blurry or uncertain, say you are not sure and recommend slow_down.\n"
        f"User question: {task}"
    )

class VisionAI:
    def __init__(self):
        self.yolo = None
        self.yolo_error: str | None = None
        self.yolo_backend: str | None = None
        self.yolo_resolved_model: str | None = None
        self.torchvision_categories: list[str] = []
        self.vlm_loaded = False
        self.vlm_error: str | None = None
        self.processor = None
        self.vlm_model = None
        self.vlm_family: str | None = None
        self.lock = threading.Lock()
        self.cache: dict[str, Any] = {"detections": [], "frame_ms": None, "created_ms": 0, "error": None}
        self.detect_count = 0
        self.detect_error_count = 0
        self.detect_latency_ms: deque[float] = deque(maxlen=80)
        self.last_detect_ms: float | None = None
        self.last_detect_created_ms: int | None = None
        self.last_detect_objects = 0
        self.vlm_latency_ms: deque[float] = deque(maxlen=20)
        self.last_vlm_ms: float | None = None
        self.last_vlm_created_ms: int | None = None
        self.detector_metrics: dict[str, dict[str, Any]] = {}
        self.vlm_metrics: dict[str, dict[str, Any]] = {}

    def _load_yolo(self):
        if self.yolo is not None or self.yolo_error:
            return
        try:
            if _is_torchvision_detector(AI_YOLO_MODEL):
                model, categories = _load_torchvision_detector(AI_YOLO_MODEL)
                self.yolo = model
                self.torchvision_categories = categories
                self.yolo_resolved_model = AI_YOLO_MODEL
                self.yolo_backend = "torchvision-cpu"
            else:
                from ultralytics import YOLO
                resolved_model = _export_onnx_if_needed(AI_YOLO_MODEL, AI_YOLO_IMGSZ)
                self.yolo = YOLO(resolved_model)
                self.yolo_resolved_model = resolved_model
                self.yolo_backend = "onnxruntime-cpu" if _is_onnx_model(resolved_model) else "pytorch-cpu"
        except Exception as exc:
            self.yolo_error = str(exc)

    def detect(self, jpeg: bytes, force: bool = False) -> dict[str, Any]:
        now = now_ms()
        with self.lock:
            if (not force) and self.cache.get("created_ms") and (now - self.cache["created_ms"] < AI_DETECT_INTERVAL_S * 1000):
                return dict(self.cache)

        if not AI_ENABLE_YOLO:
            return {"enabled": False, "detections": [], "error": "AI_ENABLE_YOLO=0"}

        self._load_yolo()
        if self.yolo_error:
            return {"enabled": True, "detections": [], "error": self.yolo_error}

        try:
            img = _decode_jpeg_to_cv2(jpeg)
            if img is None:
                raise RuntimeError("cannot decode jpeg")
            h, w = img.shape[:2]
            detections: list[dict[str, Any]] = []
            t0 = time.perf_counter()

            if _is_torchvision_detector(AI_YOLO_MODEL):
                import torch
                from PIL import Image
                from torchvision.transforms.functional import to_tensor
                rgb = img[:, :, ::-1]
                image = Image.fromarray(rgb)
                # Keep input modest on CPU. Detection models may still resize internally,
                # but this avoids feeding very large frames if the camera is upgraded later.
                scale = min(1.0, float(AI_YOLO_IMGSZ) / max(float(w), float(h))) if AI_YOLO_IMGSZ else 1.0
                infer_w, infer_h = w, h
                if scale < 1.0:
                    infer_w, infer_h = max(1, int(w * scale)), max(1, int(h * scale))
                    image = image.resize((infer_w, infer_h))
                tensor = to_tensor(image)
                with torch.no_grad():
                    pred = self.yolo([tensor])[0]
                boxes = pred.get("boxes", [])
                scores = pred.get("scores", [])
                labels = pred.get("labels", [])
                inv_scale = 1.0 / scale if scale > 0 else 1.0
                for box, score, label_id in zip(boxes, scores, labels):
                    conf = float(score.item())
                    if conf < AI_CONF_THRESHOLD:
                        continue
                    x1, y1, x2, y2 = [float(v) * inv_scale for v in box.tolist()]
                    cls_id = int(label_id.item())
                    label = self.torchvision_categories[cls_id] if 0 <= cls_id < len(self.torchvision_categories) else str(cls_id)
                    detections.append({
                        "label": str(label),
                        "confidence": round(conf, 3),
                        "bbox_xyxy": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                        "bbox_norm": [round(x1 / w, 4), round(y1 / h, 4), round(x2 / w, 4), round(y2 / h, 4)],
                    })
            else:
                predict_imgsz = _resolved_onnx_imgsz(self.yolo_resolved_model, AI_YOLO_IMGSZ) if _is_onnx_model(self.yolo_resolved_model or AI_YOLO_MODEL) else AI_YOLO_IMGSZ
                predict_kwargs = {"conf": AI_CONF_THRESHOLD, "imgsz": predict_imgsz, "verbose": False}
                if not _is_onnx_model(self.yolo_resolved_model or AI_YOLO_MODEL):
                    predict_kwargs["device"] = 0 if preferred_ai_device() == "cuda" else "cpu"
                results = self.yolo.predict(img, **predict_kwargs)
                for result in results:
                    names = result.names
                    for box in result.boxes:
                        x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                        cls_id = int(box.cls[0].item())
                        conf = float(box.conf[0].item())
                        detections.append({
                            "label": str(names.get(cls_id, cls_id)),
                            "confidence": round(conf, 3),
                            "bbox_xyxy": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                            "bbox_norm": [round(x1 / w, 4), round(y1 / h, 4), round(x2 / w, 4), round(y2 / h, 4)],
                        })

            latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            metric_key = _model_metric_key("detector", AI_YOLO_MODEL, AI_YOLO_IMGSZ)
            out = {"enabled": True, "model": AI_YOLO_MODEL, "resolved_model": self.yolo_resolved_model, "backend": self.yolo_backend, "conf_threshold": AI_CONF_THRESHOLD, "imgsz": AI_YOLO_IMGSZ, "width": w, "height": h, "detections": detections, "detections_count": len(detections), "inference_ms": latency_ms, "inference_fps": round(1000.0 / latency_ms, 2) if latency_ms > 0 else 0.0, "metric_key": metric_key, "created_ms": now_ms(), "error": None}
            with self.lock:
                self.cache = dict(out)
                self.detect_count += 1
                self.detect_latency_ms.append(latency_ms)
                self.last_detect_ms = latency_ms
                self.last_detect_created_ms = out["created_ms"]
                self.last_detect_objects = len(detections)
                out["model_metric"] = dict(_update_metric(self.detector_metrics, metric_key, latency_ms, extra={"model": AI_YOLO_MODEL, "imgsz": AI_YOLO_IMGSZ, "backend": self.yolo_backend, "last_objects": len(detections)}))
            return out
        except Exception as exc:
            with self.lock:
                self.detect_error_count += 1
            return {"enabled": True, "model": AI_YOLO_MODEL, "backend": self.yolo_backend, "resolved_model": self.yolo_resolved_model, "detections": [], "detections_count": 0, "error": str(exc)}

    def draw_overlay(self, jpeg: bytes) -> bytes:
        """Draw bbox overlay without destroying stream FPS.

        Stable behavior for CPU-only laptop:
        - If detector has an error or no boxes, return the raw JPEG directly.
          The error is still visible in AI chat/status, but the video stream is
          not re-encoded every frame.
        - Only decode/re-encode frames that actually have boxes to draw.
        """
        result = self.detect(jpeg)
        if result.get("error") or not result.get("detections"):
            return jpeg

        import cv2
        img = _decode_jpeg_to_cv2(jpeg)
        if img is None:
            return jpeg
        for det in result.get("detections", []):
            x1, y1, x2, y2 = [int(v) for v in det["bbox_xyxy"]]
            label = f"{det['label']} {det['confidence']:.2f}"
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 180, 0), 2)
            cv2.rectangle(img, (x1, max(0, y1 - 22)), (x1 + max(80, len(label) * 9), y1), (0, 180, 0), -1)
            cv2.putText(img, label, (x1 + 4, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        return buf.tobytes() if ok else jpeg

    def _load_vlm(self):
        if self.vlm_loaded or self.vlm_error:
            return
        try:
            import torch
            from transformers import AutoProcessor
            model_name = str(AI_VLM_MODEL)
            self.processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
            device_name = preferred_ai_device()
            dtype = torch.float16 if device_name == "cuda" else torch.float32
            if model_name.lower().startswith("microsoft/florence-2"):
                from transformers import AutoModelForCausalLM
                self.vlm_model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=dtype, trust_remote_code=True)
                self.vlm_model.to(torch.device(device_name))
                self.vlm_family = "florence2"
            else:
                try:
                    from transformers import AutoModelForImageTextToText as _AutoVlmModel
                except Exception:
                    from transformers import AutoModelForVision2Seq as _AutoVlmModel
                if device_name == "cuda":
                    self.vlm_model = _AutoVlmModel.from_pretrained(model_name, torch_dtype=dtype, device_map="auto", trust_remote_code=True)
                else:
                    self.vlm_model = _AutoVlmModel.from_pretrained(model_name, torch_dtype=dtype, trust_remote_code=True)
                    self.vlm_model.to(torch.device("cpu"))
                self.vlm_family = "chat_vlm"
            self.vlm_model.eval()
            self.vlm_loaded = True
        except Exception as exc:
            self.vlm_error = str(exc)

    def _vlm_generate_text(self, image, prompt: str, max_new_tokens: int | None = None) -> tuple[str, float]:
        import torch

        img = image.convert("RGB")
        img.thumbnail((512, 384))
        messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
        text = self.processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = self.processor(text=text, images=[img], return_tensors="pt")
        device = next(self.vlm_model.parameters()).device
        inputs = {k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()}
        t0 = time.perf_counter()
        with torch.no_grad():
            output_ids = self.vlm_model.generate(
                **inputs,
                max_new_tokens=max_new_tokens or AI_VLM_MAX_NEW_TOKENS,
                do_sample=False,
                repetition_penalty=1.2,
                no_repeat_ngram_size=4,
            )
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        input_len = inputs["input_ids"].shape[1] if "input_ids" in inputs else 0
        new_tokens = output_ids[:, input_len:] if input_len else output_ids
        raw = self.processor.batch_decode(new_tokens, skip_special_tokens=True)[0]
        return _clean_vlm_text(raw), latency_ms

    def analyze_scene(self, jpeg: bytes, question: str | None = None, detector_labels: set[str] | None = None) -> dict[str, Any]:
        if not AI_ENABLE_VLM:
            return {"enabled": False, "error": "AI_ENABLE_VLM=0. Set AI_ENABLE_VLM=1 to enable VLM."}
        self._load_vlm()
        if self.vlm_error:
            return {"enabled": True, "model": AI_VLM_MODEL, "error": self.vlm_error}
        try:
            import torch
            from PIL import Image
            image = Image.open(BytesIO(jpeg)).convert("RGB")
            created = None
            # Florence-2 has dedicated prompt tasks such as <CAPTION> and <OD>.
            # Use <OD> when the user asks about objects/bbox/obstacles so VLM can
            # return boxes; otherwise use caption-style answer.
            if self.vlm_family == "florence2":
                w, h = image.size
                q = (question or "").lower()
                want_od = any(x in q for x in ["vật", "object", "bbox", "khung", "cản", "người", "xe", "detect", "nhận dạng"])
                task_prompt = "<OD>" if want_od else "<CAPTION>"
                inputs = self.processor(text=task_prompt, images=image, return_tensors="pt")
                device = next(self.vlm_model.parameters()).device
                inputs = {k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()}
                t0 = time.perf_counter()
                with torch.no_grad():
                    generated_ids = self.vlm_model.generate(
                        input_ids=inputs.get("input_ids"),
                        pixel_values=inputs.get("pixel_values"),
                        max_new_tokens=AI_VLM_MAX_NEW_TOKENS,
                        num_beams=3,
                    )
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
                raw = self.processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
                parsed = {}
                try:
                    parsed = self.processor.post_process_generation(raw, task=task_prompt, image_size=(w, h))
                except Exception:
                    parsed = {}
                detections = []
                od = parsed.get("<OD>") or parsed.get(task_prompt) or {}
                bboxes = od.get("bboxes") or []
                labels = od.get("labels") or []
                for box, label in zip(bboxes, labels):
                    x1, y1, x2, y2 = [float(v) for v in box]
                    detections.append({
                        "label": str(label),
                        "confidence": None,
                        "bbox_xyxy": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                        "bbox_norm": [round(x1 / w, 4), round(y1 / h, 4), round(x2 / w, 4), round(y2 / h, 4)],
                        "source": "florence2_od",
                    })
                caption = ""
                cap = parsed.get("<CAPTION>") or parsed.get(task_prompt)
                if isinstance(cap, str):
                    caption = cap
                elif isinstance(cap, dict):
                    caption = cap.get("caption") or str(cap)
                if detections:
                    names = ", ".join([d["label"] for d in detections[:10]])
                    answer = f"Florence-2 nhận dạng được: {names}. Nếu vật thể nằm gần giữa/đầu khung hình thì nên đi chậm hoặc dừng để kiểm tra."
                else:
                    answer = caption or _clean_vlm_text(raw)
                created = now_ms()
                metric_key = _model_metric_key("vlm", AI_VLM_MODEL)
                with self.lock:
                    self.vlm_latency_ms.append(latency_ms)
                    self.last_vlm_ms = latency_ms
                    self.last_vlm_created_ms = created
                    metric = dict(_update_metric(self.vlm_metrics, metric_key, latency_ms, extra={"model": AI_VLM_MODEL, "family": self.vlm_family, "last_objects": len(detections)}))
                return {"enabled": True, "model": AI_VLM_MODEL, "family": self.vlm_family, "raw": raw, "parsed": parsed, "detections": detections, "detections_count": len(detections), "answer_vi": answer, "inference_ms": latency_ms, "inference_fps": round(1000.0 / latency_ms, 2) if latency_ms > 0 else 0.0, "metric_key": metric_key, "model_metric": metric, "created_ms": created}

            caption_prompt = (
                "Look at the image from a small robot front camera. "
                "Describe what is visible ahead in one short natural Vietnamese sentence. "
                "Mention the main scene, objects, people, vehicles, or obstacles. "
                "Do not give advice. Do not use JSON."
            )
            path_prompt = (
                "Look at the robot front-camera image. For a robot moving forward, choose the path status. "
                "Answer only one word: clear, crowded, blocked, uncertain."
            )
            action_prompt = (
                "Look at the robot front-camera image. What should the robot do next? "
                "Answer only one action: go, slow_down, stop, turn, speed_up."
            )
            if question:
                caption_prompt += f" User question context: {question[:500]}"

            raw_caption, caption_ms = self._vlm_generate_text(image, caption_prompt, max_new_tokens=70)
            raw_path, path_ms = self._vlm_generate_text(image, path_prompt, max_new_tokens=12)
            raw_action, action_ms = self._vlm_generate_text(image, action_prompt, max_new_tokens=12)
            latency_ms = round(caption_ms + path_ms + action_ms, 1)
            path_status = _pick_label(raw_path, ["clear", "crowded", "blocked", "uncertain"], default="uncertain", priority=["blocked", "crowded", "uncertain", "clear"])
            action = _pick_label(raw_action, ["go", "slow_down", "stop", "turn", "speed_up"], default="slow_down", priority=["stop", "turn", "slow_down", "go", "speed_up"])
            action = _normalize_robot_action(path_status, action, raw_caption, detector_labels=detector_labels)
            answer = _build_robot_answer_vi(raw_caption, path_status, action, question=question)
            raw = raw_caption
            created = now_ms()
            metric_key = _model_metric_key("vlm", AI_VLM_MODEL)
            with self.lock:
                self.vlm_latency_ms.append(latency_ms)
                self.last_vlm_ms = latency_ms
                self.last_vlm_created_ms = created
                metric = dict(_update_metric(self.vlm_metrics, metric_key, latency_ms, extra={"model": AI_VLM_MODEL, "family": self.vlm_family, "path_status": path_status, "action": action}))
            debug = {
                "raw_caption": raw_caption,
                "raw_path": raw_path,
                "raw_action": raw_action,
                "path_status": path_status,
                "action": action,
                "caption_ms": caption_ms,
                "path_ms": path_ms,
                "action_ms": action_ms,
                "has_vehicle": _caption_has_vehicle(raw_caption),
                "has_person": _caption_has_person(raw_caption),
                "has_obstacle": _caption_has_obstacle(raw_caption),
            }
            return {"enabled": True, "model": AI_VLM_MODEL, "family": self.vlm_family, "raw": raw, "answer_vi": answer, "path_status": path_status, "action": action, "debug": debug, "inference_ms": latency_ms, "inference_fps": round(1000.0 / latency_ms, 2) if latency_ms > 0 else 0.0, "metric_key": metric_key, "model_metric": metric, "created_ms": created}
        except Exception as exc:
            return {"enabled": True, "model": AI_VLM_MODEL, "family": self.vlm_family, "error": str(exc)}


    def preload(self, load_detector: bool = True, load_vlm: bool = False) -> dict[str, Any]:
        """Load the currently selected detector/VLM once so the first UI click is not surprised by download/load latency.

        This intentionally preloads only the selected models. Preloading every VLM/detector on a CPU laptop
        would consume a lot of RAM/disk and can freeze WSL.
        """
        if load_detector and AI_ENABLE_YOLO:
            self._load_yolo()
        if load_vlm and AI_ENABLE_VLM:
            self._load_vlm()
        return self.status()


    def configure(self, update: AIConfigUpdate) -> dict[str, Any]:
        global AI_ENABLE_YOLO, AI_YOLO_MODEL, AI_CONF_THRESHOLD, AI_YOLO_IMGSZ, AI_DETECT_INTERVAL_S
        global AI_ENABLE_VLM, AI_VLM_MODEL
        with self.lock:
            yolo_changed = False
            vlm_changed = False

            if update.enable_yolo is not None and bool(update.enable_yolo) != AI_ENABLE_YOLO:
                AI_ENABLE_YOLO = bool(update.enable_yolo)
                yolo_changed = True
            if update.yolo_model is not None:
                model = str(update.yolo_model).strip()
                if model and model != AI_YOLO_MODEL:
                    AI_YOLO_MODEL = model
                    yolo_changed = True
            if update.yolo_imgsz is not None:
                imgsz = max(160, min(1280, int(update.yolo_imgsz)))
                if imgsz != AI_YOLO_IMGSZ:
                    AI_YOLO_IMGSZ = imgsz
                    yolo_changed = True
            if update.conf_threshold is not None:
                conf = max(0.05, min(0.95, float(update.conf_threshold)))
                if conf != AI_CONF_THRESHOLD:
                    AI_CONF_THRESHOLD = conf
                    yolo_changed = True
            if update.detect_interval_s is not None:
                AI_DETECT_INTERVAL_S = max(0.05, min(5.0, float(update.detect_interval_s)))

            if update.enable_vlm is not None and bool(update.enable_vlm) != AI_ENABLE_VLM:
                AI_ENABLE_VLM = bool(update.enable_vlm)
                vlm_changed = True
            if update.vlm_model is not None:
                model = str(update.vlm_model).strip()
                if model and model != AI_VLM_MODEL:
                    AI_VLM_MODEL = model
                    vlm_changed = True

            if yolo_changed:
                self.yolo = None
                self.yolo_error = None
                self.yolo_backend = None
                self.yolo_resolved_model = None
                self.torchvision_categories = []
                self.cache = {"detections": [], "frame_ms": None, "created_ms": 0, "error": None}
                self.last_detect_ms = None
                self.last_detect_created_ms = None
                self.last_detect_objects = 0
                self.detect_latency_ms.clear()

            if vlm_changed:
                self.vlm_loaded = False
                self.vlm_error = None
                self.processor = None
                self.vlm_model = None
                self.vlm_family = None
                self.last_vlm_ms = None
                self.last_vlm_created_ms = None
                self.vlm_latency_ms.clear()

        return self.status()

    def preset_config(self) -> dict[str, Any]:
        return {
            "detector_presets": DETECTOR_PRESETS,
            "vlm_presets": VLM_PRESETS,
            "quick_profiles": {
                "realtime": {"yolo_model": "yolo11n.onnx", "yolo_imgsz": 320, "conf_threshold": 0.25, "detect_interval_s": 0.20},
                "balanced": {"yolo_model": "yolo11n.onnx", "yolo_imgsz": 320, "conf_threshold": 0.25, "detect_interval_s": 0.30},
                "strong": {"yolo_model": "yolo11s.onnx", "yolo_imgsz": 512, "conf_threshold": 0.25, "detect_interval_s": 0.50},
                "mobilenet": {"yolo_model": "torchvision:ssdlite320_mobilenet_v3_large", "yolo_imgsz": 320, "conf_threshold": 0.30, "detect_interval_s": 0.50},
                "fasterrcnn": {"yolo_model": "torchvision:fasterrcnn_mobilenet_v3_large_320_fpn", "yolo_imgsz": 320, "conf_threshold": 0.35, "detect_interval_s": 1.00},
            },
            "notes": {
                "detectors": "Danh sách đã rút gọn để giữ stream ổn định: YOLO11n realtime, YOLO11n cân bằng, YOLOv8n fallback, SSD MobileNet.",
                "vlm": "VLM dùng cho hỏi đáp/nhận dạng theo frame. Florence-2 có thể trả bbox qua prompt <OD>; các VLM chat khác trả nhãn/vị trí tương đối."
            }
        }

    def status(self) -> dict[str, Any]:
        with self.lock:
            avg_yolo = round(sum(self.detect_latency_ms) / len(self.detect_latency_ms), 1) if self.detect_latency_ms else None
            avg_vlm = round(sum(self.vlm_latency_ms) / len(self.vlm_latency_ms), 1) if self.vlm_latency_ms else None
            detect_fps = round(1000.0 / avg_yolo, 2) if avg_yolo and avg_yolo > 0 else 0.0
            return {
                "yolo": {
                    "enabled": AI_ENABLE_YOLO,
                    "model": AI_YOLO_MODEL,
                    "resolved_model": self.yolo_resolved_model,
                    "backend": self.yolo_backend,
                    "device": preferred_ai_device(),
                    "conf_threshold": AI_CONF_THRESHOLD,
                    "imgsz": AI_YOLO_IMGSZ,
                    "detect_interval_s": AI_DETECT_INTERVAL_S,
                    "loaded": self.yolo is not None,
                    "error": self.yolo_error,
                    "detect_count": self.detect_count,
                    "detect_error_count": self.detect_error_count,
                    "last_inference_ms": self.last_detect_ms,
                    "avg_inference_ms": avg_yolo,
                    "approx_detect_fps": detect_fps,
                    "last_objects": self.last_detect_objects,
                    "last_created_ms": self.last_detect_created_ms,
                    "benchmark": self.detector_metrics.get(_model_metric_key("detector", AI_YOLO_MODEL, AI_YOLO_IMGSZ)),
                },
                "detector_benchmarks": dict(self.detector_metrics),
                "vlm": {
                    "enabled": AI_ENABLE_VLM,
                    "model": AI_VLM_MODEL,
                    "loaded": self.vlm_loaded,
                    "error": self.vlm_error,
                    "last_inference_ms": self.last_vlm_ms,
                    "avg_inference_ms": avg_vlm,
                    "last_created_ms": self.last_vlm_created_ms,
                    "max_new_tokens": AI_VLM_MAX_NEW_TOKENS,
                    "family": self.vlm_family,
                    "device": preferred_ai_device(),
                    "benchmark": self.vlm_metrics.get(_model_metric_key("vlm", AI_VLM_MODEL)),
                },
                "vlm_benchmarks": dict(self.vlm_metrics),
                "runtime": ai_runtime_info(),
            }


vision_ai = VisionAI()


def ai_mjpeg_generator(device_id: str) -> Generator[bytes, None, None]:
    session = start_camera_session(device_id)
    last_seen_count = -1
    while session.running:
        with session.lock:
            frame = session.latest_jpeg
            count = session.frame_count
        if frame is not None and count != last_seen_count:
            last_seen_count = count
            try:
                frame = vision_ai.draw_overlay(frame)
            except Exception as exc:
                print(f"[AI] overlay error: {exc}")
            yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-cache\r\n\r\n" + frame + b"\r\n"
        else:
            time.sleep(0.03)


@app.on_event("startup")
def startup():
    threading.Thread(target=mqtt_loop, daemon=True).start()


@app.get("/")
def api_root():
    return {"ok": True, "service": "VisionBot Backend API", "version": APP_VERSION, "frontend": "Run the separate frontend/ app with npm run dev."}


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION, "mqtt_connected": mqtt_is_ready(), "mqtt_connected_flag": mqtt_connected, "mqtt_client_connected": mqtt_client.is_connected(), "mqtt_host": MQTT_HOST, "mqtt_port": MQTT_PORT, "robots": len(robots), "camera_sessions": {k: v.snapshot() for k, v in camera_sessions.items()}, "command_ack_timeout_s": COMMAND_ACK_TIMEOUT_S, "pending_command_acks": pending_command_ack_count(), "ai": {"yolo_enabled": AI_ENABLE_YOLO, "yolo_model": AI_YOLO_MODEL, "yolo_imgsz": AI_YOLO_IMGSZ, "vlm_enabled": AI_ENABLE_VLM, "vlm_model": AI_VLM_MODEL, "status": vision_ai.status()}}


@app.get("/api/robots")
def list_robots():
    return {"robots": list(robots.values()), "mqtt_connected": mqtt_is_ready()}


@app.get("/api/robots/{device_id}")
def get_robot(device_id: str):
    if device_id not in robots:
        raise HTTPException(status_code=404, detail="robot_not_found")
    data = dict(robots[device_id])
    if device_id in camera_sessions:
        data["camera_session"] = camera_sessions[device_id].snapshot()
    return data


@app.post("/api/robots/{device_id}/camera/start")
def start_camera(device_id: str):
    session = start_camera_session(device_id)
    return {"ok": True, "device_id": device_id, "camera_session": session.snapshot()}


@app.post("/api/robots/{device_id}/camera/stop")
def stop_camera(device_id: str):
    session = get_camera_session(device_id)
    session.stop()
    return {"ok": True, "device_id": device_id, "camera_session": session.snapshot()}


@app.get("/api/robots/{device_id}/video.mjpg")
def video_mjpg(device_id: str):
    if device_id not in robots:
        raise HTTPException(status_code=404, detail="robot_not_found")
    return StreamingResponse(mjpeg_generator(device_id), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-cache"})


@app.get("/api/robots/{device_id}/ai/video.mjpg")
def ai_video_mjpg(device_id: str):
    if device_id not in robots:
        raise HTTPException(status_code=404, detail="robot_not_found")
    return StreamingResponse(ai_mjpeg_generator(device_id), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-cache"})


@app.get("/api/robots/{device_id}/ai/status")
def ai_status(device_id: str):
    session = get_camera_session(device_id)
    return {"device_id": device_id, "camera_session": session.snapshot(), "ai": vision_ai.status(), "presets": vision_ai.preset_config(), "created_ms": now_ms()}


@app.get("/api/ai/config")
def ai_config_get():
    return {"ai": vision_ai.status(), "presets": vision_ai.preset_config(), "created_ms": now_ms()}


@app.post("/api/ai/config")
def ai_config_set(update: AIConfigUpdate):
    status = vision_ai.configure(update)
    return {"ok": True, "ai": status, "presets": vision_ai.preset_config(), "created_ms": now_ms()}


@app.post("/api/ai/preload")
def ai_preload(load_detector: bool = True, load_vlm: bool = False):
    status = vision_ai.preload(load_detector=load_detector, load_vlm=load_vlm)
    return {"ok": True, "ai": status, "presets": vision_ai.preset_config(), "created_ms": now_ms()}


@app.get("/api/robots/{device_id}/ai/detect")
def ai_detect(device_id: str, force: bool = False):
    session = start_camera_session(device_id)
    frame = session.latest_frame()
    if frame is None:
        raise HTTPException(status_code=503, detail={"error": "no_camera_frame", "camera_session": session.snapshot()})
    return {"device_id": device_id, **vision_ai.detect(frame, force=force)}


@app.get("/api/robots/{device_id}/ai/analyze")
def ai_analyze(device_id: str):
    session = start_camera_session(device_id)
    frame = session.latest_frame()
    if frame is None:
        raise HTTPException(status_code=503, detail={"error": "no_camera_frame", "camera_session": session.snapshot()})
    detections = vision_ai.detect(frame, force=True)
    detector_labels = {d.get("label", "").lower() for d in detections.get("detections", [])}
    scene = vision_ai.analyze_scene(frame, detector_labels=detector_labels)
    # Safety layer: if detector/VLM sees people/vehicles/obstacles, do not blindly go.
    labels = set(detector_labels)
    labels |= {d.get("label", "").lower() for d in scene.get("detections", [])} if isinstance(scene, dict) else set()
    risky = bool(labels & {"person", "car", "truck", "bus", "motorcycle", "bicycle", "dog", "cat", "chair", "bench"})
    safe_action = scene.get("action") if isinstance(scene, dict) and scene.get("action") else ("slow_down" if risky else "go")
    if risky and safe_action == "go":
        safe_action = "slow_down"
    safety = {"risk_detected": risky, "safe_action": safe_action, "rule": "detector/VLM risky label override" if risky else "VLM robot action"}
    return {"device_id": device_id, "answer": scene.get("answer_vi") if isinstance(scene, dict) else None, "detections": detections, "scene": scene, "safety": safety, "created_ms": now_ms()}


@app.post("/api/robots/{device_id}/ai/ask")
def ai_ask(device_id: str, req: AIAskRequest):
    session = start_camera_session(device_id)
    frame = session.latest_frame()
    if frame is None:
        raise HTTPException(status_code=503, detail={"error": "no_camera_frame", "camera_session": session.snapshot()})
    detections = vision_ai.detect(frame, force=False)
    dets = detections.get("detections", []) if isinstance(detections, dict) else []
    det_summary = ", ".join([f"{d.get('label')} {d.get('confidence')}" for d in dets[:8]]) or "không có detection rõ từ detector realtime"
    vlm_question = f"Detector realtime đang thấy: {det_summary}. Người dùng hỏi: {req.question}"
    detector_labels = {d.get("label", "").lower() for d in detections.get("detections", [])}
    scene = vision_ai.analyze_scene(frame, question=vlm_question, detector_labels=detector_labels)
    labels = set(detector_labels)
    labels |= {d.get("label", "").lower() for d in scene.get("detections", [])} if isinstance(scene, dict) else set()
    risky = bool(labels & {"person", "car", "truck", "bus", "motorcycle", "bicycle", "dog", "cat", "chair", "bench"})
    safe_action = scene.get("action") if isinstance(scene, dict) and scene.get("action") else ("slow_down" if risky else "go")
    if risky and safe_action == "go":
        safe_action = "slow_down"
    safety = {"risk_detected": risky, "safe_action": safe_action, "rule": "detector/VLM risky label override" if risky else "VLM robot action"}
    return {"device_id": device_id, "question": req.question, "answer": scene.get("answer_vi") if isinstance(scene, dict) else None, "detections": detections, "scene": scene, "safety": safety, "created_ms": now_ms()}


@app.post("/api/robots/{device_id}/control/drive")
def drive(device_id: str, command: DriveCommand):
    payload = command.model_dump(exclude_none=True)
    return publish_command_and_wait_robot_ack(device_id, "drive", topic_for(device_id, "cmd/drive"), payload, qos=1)


@app.post("/api/robots/{device_id}/control/servo")
def servo(device_id: str, command: ServoCommand):
    payload = command.model_dump()
    return publish_command_and_wait_robot_ack(device_id, "servo", topic_for(device_id, "cmd/servo"), payload, qos=1)


@app.post("/api/robots/{device_id}/control/stop")
def stop(device_id: str, command: StopCommand):
    payload = command.model_dump()
    return publish_command_and_wait_robot_ack(device_id, "stop", topic_for(device_id, "cmd/stop"), payload, qos=1)


@app.post("/api/robots/{device_id}/control/mode/{mode}")
def set_mode(device_id: str, mode: str):
    if mode not in {"idle", "manual", "ai", "estop"}:
        raise HTTPException(status_code=400, detail="invalid_mode")
    payload = {"seq": command_seq(), "mode": mode}
    return publish_command_and_wait_robot_ack(device_id, "mode", topic_for(device_id, "cmd/mode"), payload, qos=1)


@app.get("/api/robots/{device_id}/cmd_acks")
def get_robot_cmd_acks(device_id: str):
    return {"device_id": device_id, "cmd_acks": latest_cmd_acks.get(device_id, [])[-100:], "pending": pending_command_ack_snapshot(device_id)}


@app.get("/api/events")
def get_events():
    return {"events": events[-200:]}
