#!/bin/bash
#
# Test against all supported OS/Python versions
#
# Usage:
#   ./scripts/test-all-versions.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Supported versions (OS versions map to different Python versions)
VERSIONS=("latest" "debian12" "debian11" "ubuntu24" "ubuntu22" "ubuntu20")

echo "Testing against all supported versions..."
echo ""

FAILED_VERSIONS=()
PASSED_VERSIONS=()

for version in "${VERSIONS[@]}"; do
    echo "========================================="
    echo "Testing: $version"
    echo "========================================="

    if ./scripts/test.sh "$version"; then
        PASSED_VERSIONS+=("$version")
        echo "✓ $version passed"
    else
        FAILED_VERSIONS+=("$version")
        echo "✗ $version failed"
    fi
    echo ""
done

echo "========================================="
echo "Summary"
echo "========================================="
echo "Passed (${#PASSED_VERSIONS[@]}): ${PASSED_VERSIONS[*]}"
echo "Failed (${#FAILED_VERSIONS[@]}): ${FAILED_VERSIONS[*]}"
echo ""

if [ ${#FAILED_VERSIONS[@]} -gt 0 ]; then
    echo "❌ Failed versions: ${FAILED_VERSIONS[*]}"
    exit 1
else
    echo "✅ All versions passed"
    exit 0
fi
