#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"
if ! command -v node >/dev/null 2>&1; then
  echo "Node is missing. Install Node 20+ first. See README.md."
  exit 1
fi
node - <<'NODE'
const major = Number(process.versions.node.split('.')[0]);
if (major < 20) {
  console.error(`Node ${process.versions.node} is too old. Install Node 20+.`);
  process.exit(1);
}
NODE
npm install
cp -n .env.example .env
echo "Frontend installed. Run ../scripts/run_frontend_wsl.sh"
