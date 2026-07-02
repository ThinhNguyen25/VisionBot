#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
source .venv/bin/activate
set -a
[ -f .env ] && source .env
set +a

HAS_CUDA=0
if command -v nvidia-smi >/dev/null 2>&1; then
  if python - <<'PY' >/dev/null 2>&1
import torch
raise SystemExit(0 if torch.cuda.is_available() else 1)
PY
  then
    HAS_CUDA=1
  fi
fi

export MQTT_HOST="${MQTT_HOST:-localhost}"
export MQTT_PORT="${MQTT_PORT:-1883}"
export MQTT_USERNAME="${MQTT_USERNAME:-}"
export MQTT_PASSWORD="${MQTT_PASSWORD:-}"
export MQTT_BASE_TOPIC="${MQTT_BASE_TOPIC:-visionbot}"
export COMMAND_ACK_TIMEOUT_S="${COMMAND_ACK_TIMEOUT_S:-3.0}"

if [ "$HAS_CUDA" = "1" ]; then
  echo "[AI] CUDA detected. Backend will allow AI_DEVICE=auto/cuda."
  export AI_DEVICE="${AI_DEVICE:-auto}"
  export AI_ENABLE_YOLO="${AI_ENABLE_YOLO:-1}"
  export AI_YOLO_MODEL="${AI_YOLO_MODEL:-yolo11s.pt}"
  export AI_YOLO_IMGSZ="${AI_YOLO_IMGSZ:-512}"
  export AI_CONF_THRESHOLD="${AI_CONF_THRESHOLD:-0.25}"
  export AI_DETECT_INTERVAL_S="${AI_DETECT_INTERVAL_S:-0.10}"
else
  echo "[AI] No CUDA GPU detected. Using CPU realtime defaults."
  export AI_DEVICE="${AI_DEVICE:-auto}"
  export AI_ENABLE_YOLO="${AI_ENABLE_YOLO:-1}"
  export AI_YOLO_MODEL="${AI_YOLO_MODEL:-yolo11n.onnx}"
  export AI_YOLO_IMGSZ="${AI_YOLO_IMGSZ:-320}"
  export AI_CONF_THRESHOLD="${AI_CONF_THRESHOLD:-0.25}"
  export AI_DETECT_INTERVAL_S="${AI_DETECT_INTERVAL_S:-0.20}"
fi

export AI_ENABLE_VLM="${AI_ENABLE_VLM:-1}"
export AI_VLM_MODEL="${AI_VLM_MODEL:-HuggingFaceTB/SmolVLM-500M-Instruct}"
export AI_VLM_MAX_NEW_TOKENS="${AI_VLM_MAX_NEW_TOKENS:-140}"
export AI_MODEL_DIR="${AI_MODEL_DIR:-models}"

echo "[AI] model=$AI_YOLO_MODEL imgsz=$AI_YOLO_IMGSZ device=$AI_DEVICE vlm=$AI_VLM_MODEL"
uvicorn app.main:app --host 0.0.0.0 --port 8000
