"""An invoice or a bill with two `posted:` blocks is refused.

A record is posted once, to one account on one day. Two blocks state two
postings, and nothing says which is the record's, so the import refuses it
rather than post it to the first and read the second as nothing.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


@pytest.mark.parametrize('fixture, said', [
    ('tests/fixtures/an_invoice_with_two_posted_blocks.txt',
     'Invoice INV-POSTED-TWICE: multiple posted: blocks are not allowed'),
    ('tests/fixtures/a_bill_with_two_posted_blocks.txt',
     'Bill BILL-POSTED-TWICE: multiple posted: blocks are not allowed'),
], ids=['invoice', 'bill'])
def test_the_record_is_refused(tmp_path, fixture, said):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output

    result = CliRunner().invoke(cli, ['import', str(book), fixture,
                                      '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert said in result.output, result.output
