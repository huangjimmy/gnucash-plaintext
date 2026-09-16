"""A `posted:` block that gives no receivable is refused for the field it leaves out.

A posted invoice is posted to the account its `posted:` block gives in
`ar_account:`. Left out, there is no account to post to and none to weigh the
payment's figures against, so the invoice is refused for the missing field, in
a new book and in one that already holds the accounts.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture

GIVEN = '\t\tar_account: "Assets:Accounts Receivable"\n'
REFUSED = "is missing the required field 'ar_account'"


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


@pytest.mark.parametrize('new_book', [True, False], ids=['new-book', 'existing-book'])
def test_it_is_refused(tmp_path, new_book):
    invoice = _fixture('q014_invoice_posted_paid')
    assert GIVEN in invoice, invoice
    book = tmp_path / 'book.gnucash'
    ledger = tmp_path / 'ledger.txt'
    if new_book:
        ledger.write_text(ACCOUNTS + '\n' + invoice.replace(GIVEN, ''))
        result = _run('import', '--new', book, ledger, '--include-business-objects')
    else:
        accounts = tmp_path / 'accounts.txt'
        accounts.write_text(ACCOUNTS)
        assert _run('import', '--new', book, accounts).exit_code == 0
        ledger.write_text(invoice.replace(GIVEN, ''))
        result = _run('import', book, ledger, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert REFUSED in result.output, result.output
