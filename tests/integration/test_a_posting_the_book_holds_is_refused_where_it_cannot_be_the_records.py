"""A `posted_txn_guid:` giving a transaction that cannot be the invoice's posting is refused.

A `posted:` block may give the guid of a posting the book already holds, and the
import then attaches the invoice to that transaction rather than posting it
again. A posting puts the invoice's total on the account it posts to as one
split, and that split is what the invoice's lot holds. A transaction with no
split on that account, or with two, has no such split, so the import refuses
the invoice rather than attach it.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES = 'tests/fixtures/'


@pytest.mark.parametrize('transaction, invoice, said', [
    ('a_bank_purchase_with_its_guid.txt',
     'an_invoice_posted_through_a_transaction_with_no_receivable_split.txt',
     'linked posted tx 7a6b5c4d3e2f10a9b8c7d6e5f4a3b2c1 has no split for the '
     "declared posting account 'Assets:Accounts Receivable'"),
    ('a_sale_booked_to_the_receivable_in_two_splits.txt',
     'an_invoice_posted_through_a_transaction_with_two_receivable_splits.txt',
     'linked posted tx 8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e has '),
], ids=['no-receivable-split', 'two-receivable-splits'])
def test_the_invoice_is_refused(tmp_path, transaction, invoice, said):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output
    booked = CliRunner().invoke(cli, ['import', str(book), FIXTURES + transaction])
    assert booked.exit_code == 0, booked.output

    result = CliRunner().invoke(cli, ['import', str(book), FIXTURES + invoice,
                                      '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert said in result.output, result.output
