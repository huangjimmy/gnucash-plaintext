# Start interactive shell in GnuCash development container
#
# Usage:
#   .\scripts\shell.ps1         # Use latest image
#   .\scripts\shell.ps1 debian12 # Use specific tag

param(
    [string]$Tag = "latest"
)

$ErrorActionPreference = "Stop"

$ImageName = "gnucash-dev:$Tag"

# Check if image exists
$ImageExists = docker image inspect $ImageName 2>$null
if (-not $ImageExists) {
    Write-Host "Image $ImageName not found. Building..."
    switch ($Tag) {
        "latest" { .\scripts\build.ps1 "debian:13" }
        "debian12" { .\scripts\build.ps1 "debian:12" }
        "debian11" { .\scripts\build.ps1 "debian:11" }
        "ubuntu20" { .\scripts\build.ps1 "ubuntu:20.04" }
        default {
            Write-Host "Unknown tag: $Tag"
            exit 1
        }
    }
}

Write-Host "Starting interactive shell in $ImageName..."
docker run -it --rm -v "${PWD}:/workspace" $ImageName bash
