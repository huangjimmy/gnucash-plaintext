"""`auto_apply_credit: true` is refused on an invoice or a bill that is not posted.

The owner's credit settles what a posting put on the receivable or the
payable. A record with no `posted:` block has put nothing there, so there is
nothing for the credit to settle, and the import says the block needs a
posting.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


@pytest.mark.parametrize('fixture, said', [
    ('tests/fixtures/an_unposted_invoice_asking_for_the_owners_credit.txt',
     'Invoice INV-UNPOSTED-CREDIT: auto_apply_credit requires a posted: block'),
    ('tests/fixtures/an_unposted_bill_asking_for_the_owners_credit.txt',
     'Bill BILL-UNPOSTED-CREDIT: auto_apply_credit requires a posted: block'),
], ids=['invoice', 'bill'])
def test_the_record_is_refused(tmp_path, fixture, said):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output

    result = CliRunner().invoke(cli, ['import', str(book), fixture,
                                      '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert said in result.output, result.output
