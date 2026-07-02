#!/usr/bin/env bash
set -euo pipefail

BROKER_IP="${1:-}"
BROKER_DNS="${2:-localhost}"

if [ -z "$BROKER_IP" ]; then
  echo "Usage: ./scripts/generate_certs_linux.sh <broker_ip> [broker_dns]"
  exit 1
fi

CERT_DIR="$(cd "$(dirname "$0")/.." && pwd)/broker/certs"
mkdir -p "$CERT_DIR"

cat > "$CERT_DIR/server-openssl.cnf" <<EOF
[ req ]
default_bits       = 2048
prompt             = no
default_md         = sha256
distinguished_name = dn
req_extensions     = req_ext

[ dn ]
CN = $BROKER_IP

[ req_ext ]
subjectAltName = @alt_names

[ alt_names ]
IP.1 = $BROKER_IP
DNS.1 = $BROKER_DNS
DNS.2 = localhost
EOF

cd "$CERT_DIR"

openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -subj "/CN=VisionBot Local Root CA"

openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -config server-openssl.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 825 -sha256 -extensions req_ext -extfile server-openssl.cnf

echo "Certificates generated in: $CERT_DIR"
echo "Broker certificate SAN includes IP: $BROKER_IP"
echo ""
echo "Paste this CA into ESP32-CAM portal as MQTT Root CA PEM."
echo "Single-line portal form:"
python3 - <<'PY'
from pathlib import Path
p = Path("ca.crt").read_text()
print(p.replace("\r", "").replace("\n", "\\n"))
PY
