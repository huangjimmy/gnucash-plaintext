#!/bin/bash
# Run the bank import matching demo inside Docker.
#
# Usage (from repo root):
#   ./scripts/run.sh latest bash /workspace/demos/bank_import_matching/run.sh
#
# Or with a specific GnuCash version:
#   ./scripts/run.sh debian12 bash /workspace/demos/bank_import_matching/run.sh

set -e

cd /workspace
pip install -e . --quiet --break-system-packages 2>/dev/null \
    || pip install -e . --quiet

python3 demos/bank_import_matching/demo.py
