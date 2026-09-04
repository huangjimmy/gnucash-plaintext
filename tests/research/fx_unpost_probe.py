"""Probe: what unposting does to a foreign-currency cost basis (Q-035).

Run:  ./scripts/run.sh latest bash -c 'cd /workspace &&
      python3 -m pip install -e . --break-system-packages -q &&
      python3 tests/research/fx_unpost_probe.py'

A posted invoice's A/R split *is* the cost basis, and unposting destroys the
posting transaction. So:

  1. what happens to a basis that a sale has already picked?
  2. what does `fx-balances` report afterwards?
  3. does re-posting restore the basis, or mint a new guid the sale cannot see?
  4. same three questions on the bill side.
  5. and for a converted payment, what becomes of the realized FX split?
"""

import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from click.testing import CliRunner  # noqa: E402

from tests.conftest import _run  # noqa: E402

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
runner = CliRunner()

# `_run` rather than a local wrapper, and not only to save a line: importing
# `tests.conftest` is what deletes the backup and log files a second save
# inside one second would collide on. This probe is run as a script —
# `python3 tests/research/fx_unpost_probe.py` — so pytest loads no conftest
# for it, and GnuCash's ERR_FILEIO_BACKUP_ERROR is swallowed by the CLI's
# save handler: the command exits 0 and the book on disk is the one before
# the write. A probe that reports what was never saved is worse than one
# that fails.


def hr(title):
    print()
    print('=' * 72)
    print(title)
    print('=' * 72)


def balances(book):
    out = _run(runner, 'fx-balances', book).output
    print(out.rstrip() or '(no cost bases)')
    return out


def export(book, path):
    _run(runner, 'export', book, path, '--include-business-objects')
    with open(path) as handle:
        return handle.read()


def basis_guid(book):
    out = _run(runner, 'fx-balances', book).output
    match = re.search(r'\b([0-9a-f]{32})\b', out)
    return match.group(1) if match else None


def probe_invoice(workdir):
    hr('INVOICE — post, sell against the basis, then unpost')
    book = os.path.join(workdir, 'inv.gnucash')
    result = _run(runner, 'import', '--new', book, 'tests/fixtures/fx_usd_invoice_cad_income.txt',
                 '--include-business-objects', '--fx-rates', RATES)
    print(f'import posted invoice: exit={result.exit_code}')
    guid = basis_guid(book)
    print(f'\ncost basis after posting: {guid}')
    balances(book)

    # 40 USD of a basis that cost 1.40: 56.00 CAD consumed, sold for 55.60.
    sale = os.path.join(workdir, 'sale.txt')
    with open('tests/fixtures/fx_sell_usd_partial.txt') as handle:
        text = (handle.read()
                .replace('{basis_a}', guid)
                .replace('share_price: "1.35"', 'share_price: "1.40"')
                .replace('value: "-54.00"', 'value: "-56.00"'))
    with open(sale, 'w') as handle:
        handle.write(text)
    result = _run(runner, 'import', book, sale)
    print(f'\nsell 40 USD against it: exit={result.exit_code}')
    if result.exit_code != 0 or 'error' in result.output:
        print(result.output.rstrip())
    balances(book)

    result = _run(runner, 'unpost-invoices', book, 'INV-USD-001')
    print(f'\nunpost: exit={result.exit_code}')
    print(result.output.rstrip())

    print('\ncost bases after unpost:')
    balances(book)

    text = export(book, os.path.join(workdir, 'after.txt'))
    still_referenced = guid in text
    print(f'\nthe sale still names {guid}: {still_referenced}')
    declares_guid = 'guid: "' + guid + '"'
    print('that split still exists in the book: '
          f'{declares_guid in text}')

    hr('INVOICE — re-post and see whether the basis comes back')
    result = _run(runner, 'import', book, 'tests/fixtures/fx_usd_invoice_cad_income.txt',
                 '--include-business-objects', '--fx-rates', RATES)
    print(f're-import (re-post): exit={result.exit_code}')
    new_guid = basis_guid(book)
    print(f'basis guid now: {new_guid} (was {guid}) — same: {new_guid == guid}')
    balances(book)


def probe_bill(workdir):
    hr('BILL — post, then unpost')
    book = os.path.join(workdir, 'bill.gnucash')
    result = _run(runner, 'import', '--new', book, 'tests/fixtures/fx_usd_bill_cad_expense.txt',
                 '--include-business-objects', '--fx-rates', RATES)
    print(f'import posted bill: exit={result.exit_code}')
    guid = basis_guid(book)
    print(f'\ncost basis after posting: {guid}')
    balances(book)

    result = _run(runner, 'unpost-bills', book, 'BILL-USD-001')
    print(f'\nunpost: exit={result.exit_code}')
    print(result.output.rstrip())
    print('\ncost bases after unpost:')
    balances(book)


def probe_converted_payment(workdir):
    hr('INVOICE — unpost one whose payment realized a gain')
    book = os.path.join(workdir, 'paid.gnucash')
    result = _run(runner, 'import', '--new', book,
                 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt',
                 '--include-business-objects', '--fx-rates', RATES)
    print(f'import paid invoice: exit={result.exit_code}')
    balances(book)

    result = _run(runner, 'unpost-invoices', book, 'INV-USD-PAY')
    print(f'\nunpost: exit={result.exit_code}')
    print(result.output.rstrip())

    text = export(book, os.path.join(workdir, 'paid_after.txt'))
    print(f'\nFX gain split still in the book: {"Income:FX Gain" in text}')
    for line in text.splitlines():
        if 'FX Gain' in line or 'Accounts Receivable' in line or 'Assets:Bank ' in line:
            print(f'   {line.strip()}')
    print('\ncost bases after unpost:')
    balances(book)


def main():
    workdir = tempfile.mkdtemp()
    try:
        probe_invoice(workdir)
        probe_bill(workdir)
        probe_converted_payment(workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == '__main__':
    main()
