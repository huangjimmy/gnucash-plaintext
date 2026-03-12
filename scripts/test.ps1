# Run tests in GnuCash development container
#
# Usage:
#   .\scripts\test.ps1              # Run all tests with latest image
#   .\scripts\test.ps1 debian12     # Run with specific tag
#   .\scripts\test.ps1 latest tests/unit  # Run specific tests

param(
    [string]$Tag = "latest",
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$TestPath
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

if ($TestPath.Count -eq 0) {
    $TestPath = @("tests/")
}

Write-Host "Running tests in $ImageName..."
docker run --rm -v "${PWD}:/workspace" $ImageName /workspace/scripts/test-in-docker.sh $TestPath
