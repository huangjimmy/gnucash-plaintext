# Build Docker image for GnuCash development
#
# Usage:
#   .\scripts\build.ps1              # Build default (debian:13)
#   .\scripts\build.ps1 debian:12    # Build specific distribution
#   .\scripts\build.ps1 ubuntu:20.04 # Build Ubuntu 20.04

param(
    [string]$BaseImage = "debian:13"
)

$ErrorActionPreference = "Stop"

$ImageName = "gnucash-dev"

# Map base image to tag name
switch ($BaseImage) {
    "debian:13" {
        $Tag = "latest"
        $GnuCashVersion = "5.10"
    }
    "debian:12" {
        $Tag = "debian12"
        $GnuCashVersion = "4.13"
    }
    "debian:11" {
        $Tag = "debian11"
        $GnuCashVersion = "4.4"
    }
    "ubuntu:20.04" {
        $Tag = "ubuntu20"
        $GnuCashVersion = "3.8"
    }
    default {
        Write-Host "Unknown distribution: $BaseImage"
        Write-Host "Supported: debian:13, debian:12, debian:11, ubuntu:20.04"
        exit 1
    }
}

Write-Host "Building ${ImageName}:${Tag} (GnuCash $GnuCashVersion)..."
docker build --build-arg BASE_IMAGE="$BaseImage" -t "${ImageName}:${Tag}" .

Write-Host ""
Write-Host "✅ Build complete: ${ImageName}:${Tag}"
Write-Host ""
Write-Host "Run interactive shell:"
Write-Host "  .\scripts\shell.ps1 $Tag"
