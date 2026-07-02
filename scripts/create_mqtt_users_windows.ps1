param(
  [Parameter(Mandatory=$true)]
  [string]$DeviceId,

  [Parameter(Mandatory=$true)]
  [string]$DevicePassword,

  [Parameter(Mandatory=$true)]
  [string]$BackendPassword
)

$ErrorActionPreference = "Stop"

$BrokerDir = Resolve-Path (Join-Path $PSScriptRoot "..\broker")
$PasswordFile = Join-Path $BrokerDir "passwords"

if (Test-Path $PasswordFile) {
  Remove-Item $PasswordFile
}

docker run --rm -v "${BrokerDir}:/mosquitto/config" eclipse-mosquitto:2 mosquitto_passwd -b -c /mosquitto/config/passwords backend $BackendPassword
docker run --rm -v "${BrokerDir}:/mosquitto/config" eclipse-mosquitto:2 mosquitto_passwd -b /mosquitto/config/passwords $DeviceId $DevicePassword

Write-Host ""
Write-Host "Created broker/passwords with users:"
Write-Host "  backend"
Write-Host "  $DeviceId"
Write-Host ""
Write-Host "ESP32-CAM portal MQTT username should be: $DeviceId"
Write-Host "ESP32-CAM portal MQTT password should be: $DevicePassword"
