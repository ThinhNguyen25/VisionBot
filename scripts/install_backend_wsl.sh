#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install --upgrade -r requirements-ai.txt
cp -n .env.example .env
echo "Backend installed. Edit backend/.env if your broker/device/model settings differ."
