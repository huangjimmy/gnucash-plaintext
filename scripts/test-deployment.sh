#!/bin/bash
set -e

# Run tests using the locally built python package inside the Docker container
# This simulates how a user would use the installed package, rather than testing from the source directory.

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

# Allow passing a specific tag, default to 'latest'
TAG=${1:-latest}

echo "Testing pip installed package inside container using tag $TAG..."

# Make sure the inner script is executable
chmod +x ./scripts/test-deployment-inner.sh

# Run the inner script inside the Docker container
./scripts/run.sh "$TAG" ./scripts/test-deployment-inner.sh