#!/bin/bash
set -e
echo "Building package..."
# Install build tools
python3 -m pip install build --break-system-packages 2>/dev/null || python3 -m pip install build
python3 -m build

echo "Installing package..."
# Install the built wheel
python3 -m pip install dist/*.whl --break-system-packages 2>/dev/null || python3 -m pip install dist/*.whl

echo "Creating temp dir for testing outside source tree..."
mkdir -p /tmp/deployment-test
cd /tmp/deployment-test

# Copy a fixture to test with
cp /workspace/tests/fixtures/business_objects.txt ./test.txt

# Use absolute paths to avoid GnuCash backend issues
GC_FILE="$(pwd)/test.gnucash"

echo "Running import..."
gnucash-plaintext import --new "$GC_FILE" test.txt --include-business-objects

echo "Running export..."
gnucash-plaintext export "$GC_FILE" test_exported.txt --include-business-objects

echo "Running print invoice..."
gnucash-plaintext print-invoice "$GC_FILE" --invoice-id "INV-2026-001" -o test.pdf

echo "Checking if PDF was created..."
if [ -f "test.pdf" ]; then
    echo "Success! test.pdf was created."
    ls -l test.pdf
else
    echo "Error: test.pdf was not created!"
    exit 1
fi
