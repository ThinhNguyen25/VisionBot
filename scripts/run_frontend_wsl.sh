#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"
set -a
[ -f .env ] && source .env
set +a
export VITE_API_BASE="${VITE_API_BASE:-http://localhost:8000}"
export VITE_DEVICE_ID="${VITE_DEVICE_ID:-VB-CAM-E9BFB4}"
npm run dev -- --host 0.0.0.0
