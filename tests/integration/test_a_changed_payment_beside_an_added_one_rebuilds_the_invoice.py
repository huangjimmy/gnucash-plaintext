"""A file changing a payment's date and adding another payment rebuilds the invoice.

INV-001 is part paid: 60.00 on 2026-01-15. The file is read back with that
payment dated 2026-01-16 and a second payment of 40.00 added. The payment the
book holds pairs with no block, so this is not only an added payment, and the
invoice is rebuilt from the file: both payments are recorded, and the 60.00 the
book held is left orphaned, which the import warns of once the book is saved.
Measured on 5.10.
"""

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIRST = 'tests/fixtures/inv_001_paid_60_on_the_15th.txt'
CHANGED_AND_ADDED = 'tests/fixtures/inv_001_paid_60_on_the_16th_and_40_on_the_20th.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def test_both_are_recorded_and_the_old_payment_is_warned_of(tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, ACCOUNTS).exit_code == 0
    made = _run('import', book, FIRST, '--include-business-objects')
    assert made.exit_code == 0, made.output

    result = _run('import', book, CHANGED_AND_ADDED, '--include-business-objects')

    assert result.exit_code == 0, result.output
    assert 'invoice "INV-001": updated' in result.output, result.output
    saved = result.output.index('Changes saved')
    assert 'is now orphaned' in result.output[saved:], result.output
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0
    text = out.read_text()
    assert text.count('\tAssets:Bank 60.00 CAD\n') == 2, text
    assert text.count('\tAssets:Bank 40.00 CAD\n') == 1, text
    listed = _run('find-orphan-payments', book)
    assert 'Found 1 orphan bank-side payment transaction' in listed.output, listed.output
