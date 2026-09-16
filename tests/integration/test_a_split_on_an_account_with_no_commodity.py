"""A book holding a split on an account with no commodity is answered, not crashed on.

Nothing this tool writes makes such an account, and GnuCash's own account
dialog will not either, but a book from another tool can hold one, and GnuCash
loads it and keeps it, split and all, through a save and a reload
(tests/research/whether_a_reload_keeps_a_security_currency_or_an_account_with_no_commodity_probe.py).
A split there is an amount of nothing in particular: no currency to convert, no
unit to write it at. Each command says which account it is, rather than failing
on the missing commodity inside Python.
"""

from datetime import datetime

import gnucash
import pytest
from click.testing import CliRunner
from gnucash import Account, GncNumeric, Split, Transaction

from infrastructure.gnucash.kvp import set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.conftest import _run


@pytest.fixture
def book(tmp_path):
    """10.00 moved from cash onto `No Commodity`, whose split also stores a
    `cost_basis_balance`, as a hand edit can leave one."""
    path = tmp_path / 'book.gnucash'
    repo = GnuCashRepository(str(path))
    repo.open(SessionMode.NEW)
    try:
        book = repo.book
        cad = book.get_table().lookup('CURRENCY', 'CAD')
        root = book.get_root_account()

        def account(name, commodity, kind):
            made = Account(book)
            made.BeginEdit()
            made.SetName(name)
            made.SetType(kind)
            if commodity is not None:
                made.SetCommodity(commodity)
            root.append_child(made)
            made.CommitEdit()
            return made

        cash = account('Cash', cad, gnucash.ACCT_TYPE_CASH)
        bare = account('No Commodity', None, gnucash.ACCT_TYPE_ASSET)
        transaction = Transaction(book)
        transaction.BeginEdit()
        transaction.SetCurrency(cad)
        transaction.SetDescription('Onto an account with no commodity')
        transaction.SetDatePostedSecs(datetime(2026, 1, 5, 12))
        for on, cents in ((bare, 1000), (cash, -1000)):
            split = Split(book)
            split.SetParent(transaction)
            split.SetAccount(on)
            split.SetAmount(GncNumeric(cents, 100))
            split.SetValue(GncNumeric(cents, 100))
            if on is bare:
                set_custom_metadata(split, {'cost_basis_balance': '10.00'})
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()
    return path


def test_verify_costs_says_the_balance_is_on_an_account_with_no_commodity(book):
    result = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')

    assert result.exit_code == 1, result.output
    assert 'Traceback' not in result.output, result.output
    assert "its account 'No Commodity' has no commodity" in result.output, result.output


@pytest.mark.parametrize('options', [[], ['--all-accounts']], ids=['export', 'all-accounts'])
def test_the_export_refuses_and_says_which_account(tmp_path, book, options):
    result = _run(CliRunner(), 'export', str(book), str(tmp_path / 'out.txt'), *options)

    assert result.exit_code != 0, result.output
    assert "'No Commodity' has no commodity" in result.output, result.output
    assert 'NoneType' not in result.output, result.output


def test_the_beancount_export_refuses_and_says_which_account(tmp_path, book):
    result = _run(CliRunner(), 'export-beancount', str(book), str(tmp_path / 'out.beancount'))

    assert result.exit_code != 0, result.output
    assert "'No Commodity' has no commodity" in result.output, result.output
    assert 'NoneType' not in result.output, result.output


def test_account_balance_refuses_and_says_which_account(book):
    result = _run(CliRunner(), 'account-balance', str(book), '--as-of', '2026-12-31')

    assert result.exit_code != 0, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        result.exception)
    assert "'No Commodity' has no commodity" in result.output, result.output
