"""A transaction block giving a split on an account with no commodity is refused, as `export` refuses it.

GnuCash keeps an account with no commodity through a save and a reload. A split
is written as an amount of its account's commodity, so `export` refuses a book
holding a split on one, and says which. Measured on 5.10: `import` took the
same split at exit 0, as a new transaction and with `--strategy update` alike,
and wrote a book the export then refused.
"""

from pathlib import Path

import gnucash
from click.testing import CliRunner
from gnucash import Account

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
FIXTURES = Path('tests/fixtures')
SPENT = FIXTURES / 'money_spent_from_the_bank_on_supplies.txt'
INTO_HOLDING = FIXTURES / 'money_moved_into_an_account_with_no_commodity.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output


def _a_book_with_an_account_with_no_commodity(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, ACCOUNTS)
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.NORMAL)
    try:
        holding = Account(repo.book)
        holding.BeginEdit()
        holding.SetName('Holding')
        holding.SetType(gnucash.ACCT_TYPE_ASSET)
        repo.book.get_root_account().append_child(holding)
        holding.CommitEdit()
        repo.save()
    finally:
        repo.close()
    return book


def test_a_new_transaction_is_refused(tmp_path):
    book = _a_book_with_an_account_with_no_commodity(tmp_path)

    result = _run('import', book, INTO_HOLDING)

    assert result.exit_code != 0, result.output
    assert "'Holding' has no commodity" in result.output, result.output
    exported = _run('export', book, tmp_path / 'out.txt')
    assert exported.exit_code == 0, exported.output


def test_an_edit_moving_a_split_there_is_refused(tmp_path):
    book = _a_book_with_an_account_with_no_commodity(tmp_path)
    _done('import', book, SPENT)

    result = _run('import', book, INTO_HOLDING, '--strategy', 'update')

    assert result.exit_code != 0, result.output
    assert "'Holding' has no commodity" in result.output, result.output
    out = tmp_path / 'out.txt'
    exported = _run('export', book, out)
    assert exported.exit_code == 0, exported.output
    assert 'Expenses:Supplies 10.00 CAD' in out.read_text()
