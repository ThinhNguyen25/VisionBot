#!/usr/bin/env bash
set -euo pipefail
REPO_NAME="${1:-VisionBot}"
VISIBILITY="${2:-private}"
cd "$(dirname "$0")/.."
if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI chưa có. Cài bằng: sudo apt install gh hoặc xem README."
  exit 1
fi
if [ ! -d .git ]; then
  git init
fi
git add .
git commit -m "VisionBot v1.1.4 final controls model preload" || true
if ! git remote get-url origin >/dev/null 2>&1; then
  gh repo create "$REPO_NAME" --"$VISIBILITY" --source=. --remote=origin --push
else
  git push -u origin main || git push -u origin master
fi
