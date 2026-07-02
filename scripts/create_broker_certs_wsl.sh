#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERT_DIR="$ROOT/broker/certs"
mkdir -p "$CERT_DIR"
cd "$CERT_DIR"

read -rp "Enter laptop Wi-Fi IP for ESP32-CAM broker, e.g. 192.168.1.66: " WIFI_IP
if [ -z "$WIFI_IP" ]; then
  echo "Missing IP. Abort."
  exit 1
fi

cat > server-san.cnf <<EOF2
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = visionbot-mqtt

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = $WIFI_IP
EOF2

if [ ! -f ca.key ] || [ ! -f ca.crt ]; then
  echo "Creating new CA. Keep ca.key private; do not push to GitHub."
  openssl genrsa -out ca.key 4096
  openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -subj "/CN=VisionBot Local CA"
else
  echo "Reusing existing ca.key/ca.crt"
fi

openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -config server-san.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 825 -sha256 -extensions req_ext -extfile server-san.cnf
openssl verify -CAfile ca.crt server.crt
openssl x509 -in server.crt -noout -text | grep -A2 "Subject Alternative Name" || true

echo "Done. Restart broker and paste ca.crt content into ESP32-CAM portal Root CA."
