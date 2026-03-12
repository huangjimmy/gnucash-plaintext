# Stop the development environment
#
# Usage:
#   .\scripts\dev-stop.ps1

$ErrorActionPreference = "Stop"

Write-Host "Stopping GnuCash Plaintext development environment..."
docker compose down
Write-Host "Stopped."
