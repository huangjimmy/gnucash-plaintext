"""A payment into an account with no commodity is refused, and the refusal states the account.

GnuCash keeps an account with no commodity through a save and a reload, split
and all (tests/research/whether_a_reload_keeps_a_security_currency_or_an_account_with_no_commodity_probe.py),
so a book can hold one. A payment into it has no currency to be recorded in.
Measured on 5.10 before this: the import ended with `'NoneType' object has no
attribute 'get_mnemonic'`, and said nothing about which account.
"""

import gnucash
from click.testing import CliRunner
from gnucash import Account

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
UNPAID = 'tests/fixtures/inv_001_posted_and_unpaid.txt'
PAID_INTO_HOLDING = 'tests/fixtures/inv_001_paid_into_holding.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def test_it_is_refused_stating_the_account(tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, ACCOUNTS).exit_code == 0
    made = _run('import', book, UNPAID, '--include-business-objects')
    assert made.exit_code == 0, made.output
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

    result = _run('import', book, PAID_INTO_HOLDING, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert "'Holding' has no commodity" in result.output, result.output
    assert 'NoneType' not in result.output, result.output
