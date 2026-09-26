"""A payment block states exactly one account the money came from.

`account:` is the key, and `bank_account:` its older spelling. A block may
carry both where they agree. Two that disagree leave the account unknown, and
a block carrying neither states no account at all, so the import refuses each.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


@pytest.mark.parametrize('fixture, said', [
    ('tests/fixtures/a_payment_stating_two_different_accounts.txt',
     "payment declares both account: 'Assets:Bank' and bank_account: "
     "'Equity:Owner' — they must name the same account"),
    ('tests/fixtures/a_payment_stating_no_account.txt',
     'payment block has no account: (or bank_account:)'),
], ids=['two-accounts', 'no-account'])
def test_the_invoice_is_refused(tmp_path, fixture, said):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output

    result = CliRunner().invoke(cli, ['import', str(book), fixture,
                                      '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert said in result.output, result.output
