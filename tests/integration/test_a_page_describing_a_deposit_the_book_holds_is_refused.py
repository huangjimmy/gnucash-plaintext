"""A page's payment block describing a deposit the book already holds is refused.

INV-001 is posted and unpaid. The bank holds, on the payment's day, 100.00 of
supplies paid out and then Acme's 100.00 deposit, entered on the receivable and
applied to no invoice. A page printed from another book gives INV-001's payment
by a `txn_guid:` this book does not hold, and describes that deposit: the same
day, figure, account and memo.

The money is already here, so recording the block would enter it twice. The
refusal gives the deposit, and says nothing of an invoice it settles, because
it settles none. The payment going out that day is the other way round, so it
is not the movement the block describes. Measured on 5.10.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
PAGE = 'tests/fixtures/inv_001_paid_by_a_transaction_the_book_lacks.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


@pytest.mark.parametrize('deposit', [
    'tests/fixtures/an_unpaid_invoice_beside_its_deposit_unapplied.txt',
    'tests/fixtures/an_unpaid_invoice_beside_its_deposit_parked_as_credit.txt',
], ids=['in-no-lot', 'in-a-credit-lot'])
def test_it_is_refused_as_money_the_book_already_has(tmp_path, deposit):
    """Loose on the receivable or parked as Acme's credit, the deposit settles
    no invoice, so the refusal gives none."""
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, ACCOUNTS).exit_code == 0
    made = _run('import', book, deposit, '--include-business-objects')
    assert made.exit_code == 0, made.output

    result = _run('import', book, PAGE, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert 'describes one it already has' in result.output, result.output
    assert "2026-01-15 'Acme' for 100.00 in Assets:Bank" in result.output, result.output
    assert 'already settling' not in result.output, result.output
    listed = _run('find-orphan-payments', book)
    assert 'No orphan bank-side payment transactions found.' in listed.output, listed.output
