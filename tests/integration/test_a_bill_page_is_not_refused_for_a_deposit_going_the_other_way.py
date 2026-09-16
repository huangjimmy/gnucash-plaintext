"""A bill's page is not refused for a same-day deposit of its size going the other way.

BILL-001 is posted and unpaid, and the bank holds a customer's 50.00 deposit on
the day the bill's page says it was paid, with the same memo. The page gives
its payment by a `txn_guid:` this book does not hold. Before recording the
payment from the block, the import asks whether the book already holds the
movement the block describes. A bill's payment sends money out and the deposit
brought money in, so it is not that movement: the payment is recorded.
"""

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
BOOK = 'tests/fixtures/bill_001_unpaid_beside_a_deposit_of_its_size.txt'
PAGE = 'tests/fixtures/bill_001_paid_by_a_transaction_the_book_lacks.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def test_the_payment_is_recorded_from_the_block(tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, ACCOUNTS).exit_code == 0
    made = _run('import', book, BOOK, '--include-business-objects')
    assert made.exit_code == 0, made.output

    result = _run('import', book, PAGE, '--include-business-objects')

    assert result.exit_code == 0, result.output
    assert 'recording the payment from the block' in result.output, result.output
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0
    text = out.read_text()
    assert text.count('\tAssets:Bank -50.00 CAD\n') == 1, text
    assert text.count('\tAssets:Bank 50.00 CAD\n') == 1, text
