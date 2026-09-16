"""`close-books` says which income account has no commodity rather than crashing on it.

Nothing this tool writes makes an account without a commodity, and GnuCash's
own dialog will not either, but a book from another tool can hold one and
GnuCash keeps it through a save and a reload
(`tests/research/whether_a_reload_keeps_a_security_currency_or_an_account_with_no_commodity_probe.py`).

Closing the books groups every income and expense balance by its account's
currency, so such an account has no group to go in. Read as impossible it was
an `AttributeError` on `NoneType`; skipped, its balance would be left out of
retained earnings with nothing said, which is a wrong figure rather than a
refused run. So it is refused by name, as `export`, `export-beancount` and
`fx-balances --verify-costs` refuse the same state.
"""

from datetime import datetime

import gnucash
import pytest
from click.testing import CliRunner
from gnucash import Account, GncNumeric, Split, Transaction

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.conftest import _run


@pytest.fixture
def book(tmp_path):
    """100.00 of income on an account with no commodity, against a CAD bank."""
    path = tmp_path / 'book.gnucash'
    repo = GnuCashRepository(str(path))
    repo.open(SessionMode.NEW)
    try:
        made = repo.book
        cad = made.get_table().lookup('CURRENCY', 'CAD')
        root = made.get_root_account()

        def account(name, commodity, kind):
            account = Account(made)
            account.BeginEdit()
            account.SetName(name)
            account.SetType(kind)
            if commodity is not None:
                account.SetCommodity(commodity)
            root.append_child(account)
            account.CommitEdit()
            return account

        bank = account('Bank', cad, gnucash.ACCT_TYPE_BANK)
        earned = account('No Commodity', None, gnucash.ACCT_TYPE_INCOME)
        transaction = Transaction(made)
        transaction.BeginEdit()
        transaction.SetCurrency(cad)
        transaction.SetDescription('Earned on an account with no commodity')
        transaction.SetDatePostedSecs(datetime(2026, 6, 30, 12))
        for on, cents in ((bank, 10000), (earned, -10000)):
            split = Split(made)
            split.SetParent(transaction)
            split.SetAccount(on)
            split.SetAmount(GncNumeric(cents, 100))
            split.SetValue(GncNumeric(cents, 100))
        transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()
    return path


def test_closing_refuses_and_says_which_account(book):
    result = _run(CliRunner(), 'close-books', str(book), '--closing-date', '2026-12-31')

    assert result.exit_code != 0, result.output
    assert "'No Commodity' has no commodity" in result.output, result.output
    assert 'NoneType' not in result.output, result.output
    assert 'Traceback' not in result.output, result.output


def test_a_preview_refuses_it_too(book):
    """`--dry-run` reads the same balances, so it meets the same account."""
    result = _run(CliRunner(), 'close-books', str(book),
                  '--closing-date', '2026-12-31', '--dry-run')

    assert result.exit_code != 0, result.output
    assert "'No Commodity' has no commodity" in result.output, result.output


def test_validate_reports_it(book):
    """The command a reader runs *on* such a book says so as well."""
    result = _run(CliRunner(), 'validate', str(book))

    assert 'No Commodity' in result.output, result.output
    assert 'commodity' in result.output.lower(), result.output
