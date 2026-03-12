# Start the development environment with VS Code Server
#
# Usage:
#   .\scripts\dev-start.ps1

$ErrorActionPreference = "Stop"

Write-Host "Starting GnuCash Plaintext development environment..."
Write-Host ""

# Check if base image exists
$BaseImageExists = docker image inspect gnucash-dev:latest 2>$null
if (-not $BaseImageExists) {
    Write-Host "Base image gnucash-dev:latest not found. Building..."
    .\scripts\build.ps1
    Write-Host ""
}

# Check if dev image exists
$DevImageExists = docker image inspect gnucash-dev-vscode:latest 2>$null
if (-not $DevImageExists) {
    Write-Host "Dev image not found. Docker compose will build it (this may take a few minutes)..."
    Write-Host ""
}

Write-Host "Starting docker compose..."
docker compose up --build
