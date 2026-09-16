"""`payment_split_guid:` is refused, and the refusal gives the key's new name.

A payment block gives the split it settles with `txn_split_guid:`. A ledger
written before the key was renamed still says `payment_split_guid:`, and read
as an unknown key that line would be ignored: the payment would be recorded
from its date and amount rather than on the split the file gives.
"""

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
LEDGER = 'tests/fixtures/a_payment_giving_the_old_payment_split_guid_key.txt'


def test_the_invoice_is_refused_with_the_new_name(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output

    result = CliRunner().invoke(cli, ['import', str(book), LEDGER,
                                      '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert 'payment_split_guid: is no longer accepted' in result.output, result.output
    assert 'txn_split_guid:' in result.output, result.output
