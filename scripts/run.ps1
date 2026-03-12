# Run arbitrary command in GnuCash development container
#
# Usage:
#   .\scripts\run.ps1 python3 --version
#   .\scripts\run.ps1 debian12 python3 script.py
#   .\scripts\run.ps1 latest gnucash-plaintext --help

param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"

# Check if first arg looks like a tag
$KnownTags = @("latest", "debian12", "debian11", "ubuntu20")
if ($Arguments.Count -gt 0 -and $KnownTags -contains $Arguments[0]) {
    $Tag = $Arguments[0]
    $Arguments = $Arguments[1..($Arguments.Count-1)]
} else {
    $Tag = "latest"
}

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

docker run --rm -v "${PWD}:/workspace" $ImageName $Arguments
