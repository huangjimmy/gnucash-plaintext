"""`validate` reports an account with no name.

The import refuses an account with an empty name, and so does GnuCash's own
account dialog, but a book written by another tool can hold one. It has no path
of its own for anything to give, so `validate` reports it as an error.
"""

import gnucash
from click.testing import CliRunner
from gnucash import Account

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.conftest import _run


def test_the_account_is_reported(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), 'tests/fixtures/q019_accounts.txt')
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        unnamed = Account(repo.book)
        unnamed.BeginEdit()
        unnamed.SetType(gnucash.ACCT_TYPE_ASSET)
        unnamed.SetCommodity(repo.book.get_table().lookup('CURRENCY', 'CAD'))
        repo.book.get_root_account().append_child(unnamed)
        unnamed.CommitEdit()
        repo.save()
    finally:
        repo.close()

    result = _run(runner, 'validate', str(book))

    assert 'Account has empty name' in result.output, result.output
    assert '1 error(s)' in result.output, result.output
