#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/camera-relay"
source .venv/bin/activate
export CAMERA_TOKEN="${CAMERA_TOKEN:-}"
export BACKEND_TOKEN="${BACKEND_TOKEN:-}"
export MAX_FRAME_SIZE_BYTES="${MAX_FRAME_SIZE_BYTES:-120000}"
export CAMERA_TIMEOUT_SEC="${CAMERA_TIMEOUT_SEC:-10}"
uvicorn app.main:app --host 0.0.0.0 --port 8001
