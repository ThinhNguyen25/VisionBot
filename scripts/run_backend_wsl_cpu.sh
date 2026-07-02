#!/usr/bin/env bash
set -euo pipefail
# Backward-compatible CPU runner. Prefer run_backend_wsl_auto.sh for auto CPU/GPU selection.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
source .venv/bin/activate
set -a
[ -f .env ] && source .env
set +a
export MQTT_HOST="${MQTT_HOST:-localhost}"
export MQTT_PORT="${MQTT_PORT:-1883}"
export MQTT_USERNAME="${MQTT_USERNAME:-}"
export MQTT_PASSWORD="${MQTT_PASSWORD:-}"
export COMMAND_ACK_TIMEOUT_S="${COMMAND_ACK_TIMEOUT_S:-3.0}"
export AI_DEVICE="cpu"
export AI_ENABLE_YOLO="${AI_ENABLE_YOLO:-1}"
export AI_YOLO_MODEL="${AI_YOLO_MODEL:-yolo11n.onnx}"
export AI_YOLO_IMGSZ="${AI_YOLO_IMGSZ:-320}"
export AI_CONF_THRESHOLD="${AI_CONF_THRESHOLD:-0.25}"
export AI_DETECT_INTERVAL_S="${AI_DETECT_INTERVAL_S:-0.20}"
export AI_ENABLE_VLM="${AI_ENABLE_VLM:-1}"
export AI_VLM_MODEL="${AI_VLM_MODEL:-HuggingFaceTB/SmolVLM-500M-Instruct}"
export AI_VLM_MAX_NEW_TOKENS="${AI_VLM_MAX_NEW_TOKENS:-140}"
uvicorn app.main:app --host 0.0.0.0 --port 8000
