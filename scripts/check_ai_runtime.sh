#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [ -d .venv ]; then
  source .venv/bin/activate
fi

echo "== NVIDIA check =="
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi || true
else
  echo "nvidia-smi not found: NVIDIA GPU/CUDA path is not available from this WSL session."
fi

echo
echo "== Python / torch check =="
python - <<'PY'
try:
    import torch
    print('torch:', torch.__version__)
    print('cuda available:', torch.cuda.is_available())
    if torch.cuda.is_available():
        print('gpu:', torch.cuda.get_device_name(0))
except Exception as exc:
    print('torch check failed:', exc)
PY

echo
echo "== ONNX Runtime providers =="
python - <<'PY'
try:
    import onnxruntime as ort
    print(ort.get_available_providers())
except Exception as exc:
    print('onnxruntime check failed:', exc)
PY
