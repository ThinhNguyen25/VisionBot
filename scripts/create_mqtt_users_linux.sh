#!/usr/bin/env bash
set -euo pipefail

DEVICE_ID="${1:-}"
DEVICE_PASSWORD="${2:-}"
BACKEND_PASSWORD="${3:-}"

if [ -z "$DEVICE_ID" ] || [ -z "$DEVICE_PASSWORD" ] || [ -z "$BACKEND_PASSWORD" ]; then
  echo "Usage: ./scripts/create_mqtt_users_linux.sh <device_id> <device_password> <backend_password>"
  exit 1
fi

BROKER_DIR="$(cd "$(dirname "$0")/.." && pwd)/broker"
rm -f "$BROKER_DIR/passwords"

docker run --rm -v "$BROKER_DIR:/mosquitto/config" eclipse-mosquitto:2 mosquitto_passwd -b -c /mosquitto/config/passwords backend "$BACKEND_PASSWORD"
docker run --rm -v "$BROKER_DIR:/mosquitto/config" eclipse-mosquitto:2 mosquitto_passwd -b /mosquitto/config/passwords "$DEVICE_ID" "$DEVICE_PASSWORD"

echo "Created broker/passwords with users:"
echo "  backend"
echo "  $DEVICE_ID"
