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

# The balance sheet and the income statement are drawn by a customized GnuCash
# report carried as package data, and an installed wheel is the only place that
# shows the file is both in the package and loadable from it. The suite runs
# from the source folder, where a report the wheel leaves out still passes every
# test — which is how a wheel once shipped the module without the report it
# loads. Drawing a page here runs the Scheme itself.
echo "Running balance sheet on a book holding foreign currency..."
cp /workspace/examples/multi-currency/some_of_the_dollars_kept_back.txt ./fx.txt
FX_FILE="$(pwd)/fx.gnucash"
AS_OF=$(grep -oE -- '--as-of [0-9-]+' fx.txt | head -1 | awk '{print $2}')

gnucash-plaintext import --new "$FX_FILE" fx.txt --include-business-objects
gnucash-plaintext balance-sheet "$FX_FILE" --as-of "$AS_OF" > fx_page.txt

# Every gain the page states is worked out on the page beneath it, as keys
# nested inside the block: the key opens a block, states its own figure inside
# it, and lists the entries it was measured from. Their absence means the
# report drew a page without running its own working.
#
# Keys, not comments. Q-043 wrote this working as `# realized_gains_fx:`
# comment lines and this check looked for one; Q-044 made them real keys, so
# the comment stopped being written and the check failed on a page that states
# its working perfectly well. Anchoring on the nested figure is what makes the
# check follow the thing it is about — a `#` line proves only that a comment
# was printed.
echo "Checking the page shows how each gain was worked out..."
if ! grep -qE '^[[:blank:]]+realized_gains_fx:[[:blank:]]+-?[0-9]' fx_page.txt; then
    echo "Error: the page states no working for realized_gains_fx!"
    cat fx_page.txt
    exit 1
fi

# And the entries beneath that figure, which are the working itself.
if ! grep -qE '^[[:blank:]]+split:$' fx_page.txt; then
    echo "Error: the page lists no split behind realized_gains_fx!"
    cat fx_page.txt
    exit 1
fi

# The example carries its own prices, so the page needs no rates file, and the
# page it should draw is commented at its own foot. `gnucash_balancing_amount`
# is left out of the comparison: it is GnuCash's own figure for what the sheet
# needs to balance, not a gain, and the two are equal only by coincidence.
echo "Checking each gain against the figure the example publishes..."
KEYS='(realized_gains_fx|total_realized_gains|unrealized_gains_assets_fx|unrealized_gains_liabilities_fx|unrealized_gains_fx|unrealized_gains_other|total_unrealized_gains)'
grep -E "^# [[:blank:]]*$KEYS:" fx.txt | sed 's/^# //' > fx_published.txt
grep -E "^[[:blank:]]*$KEYS:" fx_page.txt > fx_drawn.txt

if [ ! -s fx_drawn.txt ]; then
    echo "Error: the page states no gains at all!"
    cat fx_page.txt
    exit 1
fi

# The two are compared as strings rather than with `diff`, which the Arch and
# openSUSE images do not carry: there the comparison itself failed, and the
# message said the page differed when nothing had compared it.
if [ "$(cat fx_published.txt)" = "$(cat fx_drawn.txt)" ]; then
    echo "Success! The installed package draws the page the example publishes."
else
    echo "Error: the installed package draws a different page from the one the example publishes!"
    echo "--- what the example publishes ---"
    cat fx_published.txt
    echo "--- what the installed package draws ---"
    cat fx_drawn.txt
    exit 1
fi
