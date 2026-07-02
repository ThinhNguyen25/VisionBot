param(
  [Parameter(Mandatory=$true)]
  [string]$BrokerIp,

  [string]$BrokerDns = "localhost"
)

$ErrorActionPreference = "Stop"

$CertDir = Join-Path $PSScriptRoot "..\broker\certs"
New-Item -ItemType Directory -Force -Path $CertDir | Out-Null

$OpenSslCnf = Join-Path $CertDir "server-openssl.cnf"

@"
[ req ]
default_bits       = 2048
prompt             = no
default_md         = sha256
distinguished_name = dn
req_extensions     = req_ext

[ dn ]
CN = $BrokerIp

[ req_ext ]
subjectAltName = @alt_names

[ alt_names ]
IP.1 = $BrokerIp
DNS.1 = $BrokerDns
DNS.2 = localhost
"@ | Set-Content -Path $OpenSslCnf -Encoding ascii

Push-Location $CertDir

openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt -subj "/CN=VisionBot Local Root CA"

openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -config server-openssl.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 825 -sha256 -extensions req_ext -extfile server-openssl.cnf

Pop-Location

Write-Host ""
Write-Host "Certificates generated in: $CertDir"
Write-Host "Broker certificate SAN includes IP: $BrokerIp"
Write-Host ""
Write-Host "Paste this CA into ESP32-CAM portal as MQTT Root CA PEM."
Write-Host "For portal single-line form, use this command:"
Write-Host ""
Write-Host '  (Get-Content .\broker\certs\ca.crt -Raw).Replace("`r","").Replace("`n","\n")'
Write-Host ""
