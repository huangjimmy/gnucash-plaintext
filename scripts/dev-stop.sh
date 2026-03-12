#!/bin/bash
# Stop the development environment
#
# Usage:
#   ./scripts/dev-stop.sh

set -e

echo "Stopping GnuCash Plaintext development environment..."
docker compose down
echo "Stopped."
