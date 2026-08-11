"""Closing books whose accounts are kept finer than the currency.

An account may have a smaller Smallest Fraction than its commodity — fuel at
thousandths is the everyday reason — and GnuCash stores amounts on it at that
unit. So a year-end balance need not be a whole number of cents, and the
closing entry has to bring it back to one.

Each figure reaches the cent through GnuCash's rounding, and equity takes back
the negation of what was actually placed. Truncating each side separately
toward zero — `int(value * 100)` — meant the two roundings did not have to
agree: the accounts closed to 18.19 and 27.24 while equity was truncated from
their raw sum of 45.436 to 45.43, and GnuCash scrubbed in `Imbalance-CAD 0.01`
on the one transaction of the year whose whole purpose is that the books come
out level.

The book is built through the bindings because this tool's own importer will
not write a figure finer than the currency; `close-books` exists to run against
books GnuCash wrote.
"""

import os
import tempfile

import pytest
from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode


def _book_holding(*numerators):
    """A CAD book whose expense accounts are kept to thousandths."""
    import gnucash
    from gnucash import Account, GncNumeric, Session, Split
    from gnucash import Transaction as Tx

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)
    try:
        from gnucash import SessionOpenMode
        session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        session = Session(f'xml://{path}', is_new=True)

    book = session.book
    root = book.get_root_account()
    cad = book.get_table().lookup('CURRENCY', 'CAD')

    def child(parent, name, kind, scu=100):
        account = Account(book)
        account.SetName(name)
        account.SetType(kind)
        account.SetCommodity(cad)
        account.SetCommoditySCU(scu)
        parent.append_child(account)
        return account

    assets = child(root, 'Assets', gnucash.ACCT_TYPE_ASSET)
    bank = child(assets, 'Bank', gnucash.ACCT_TYPE_BANK, 1000)
    expenses = child(root, 'Expenses', gnucash.ACCT_TYPE_EXPENSE)
    fuel = child(expenses, 'Fuel', gnucash.ACCT_TYPE_EXPENSE, 1000)
    oil = child(expenses, 'Oil', gnucash.ACCT_TYPE_EXPENSE, 1000)
    equity = child(root, 'Equity', gnucash.ACCT_TYPE_EQUITY)
    child(equity, 'Retained Earnings', gnucash.ACCT_TYPE_EQUITY)

    for account, numerator in zip((fuel, oil), numerators):
        transaction = Tx(book)
        transaction.BeginEdit()
        transaction.SetCurrency(cad)
        transaction.SetDate(1, 6, 2026)
        transaction.SetDescription(f'Spent on {account.GetName()}')
        out = Split(book)
        out.SetParent(transaction)
        out.SetAccount(account)
        out.SetValue(GncNumeric(numerator, 1000))
        out.SetAmount(GncNumeric(numerator, 1000))
        back = Split(book)
        back.SetParent(transaction)
        back.SetAccount(bank)
        back.SetValue(GncNumeric(-numerator, 1000))
        back.SetAmount(GncNumeric(-numerator, 1000))
        transaction.CommitEdit()

    session.save()
    session.end()
    return path


@pytest.fixture
def book_with_thousandths():
    """18.191 and 27.245 — where the two roundings disagree by a cent.

    Truncating each side toward zero gives -18.19, -27.24 and +45.43, which
    happens to sum to zero: the entry balances while stating a figure for Oil
    that is a cent short of what it holds.
    """
    path = _book_holding(18191, 27245)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def book_of_half_cents():
    """0.005 twice — where truncation does not even balance.

    Each side truncates to 0.00 and equity truncates 0.010 to 0.01, so the
    splits sum to a cent and GnuCash scrubs in `Imbalance-CAD`. Rounded, both
    sides are 0.01 and equity is -0.02.
    """
    path = _book_holding(5, 5)
    yield path
    if os.path.exists(path):
        os.unlink(path)


def _closing_entry(path):
    """The closing transaction's splits, as (account, value) strings."""
    repo = GnuCashRepository(path)
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        rows = None
        for raw in query.run():
            transaction = Transaction(instance=raw)
            if 'Closing' not in transaction.GetDescription():
                continue
            rows = [(split.GetAccount().get_full_name(),
                     f'{split.GetValue().num()}/{split.GetValue().denom()}')
                    for split in transaction.GetSplitList()]
        query.destroy()
        return rows
    finally:
        repo.close()


class TestThePremise:
    def test_the_book_really_holds_sub_cent_balances(self, book_with_thousandths):
        """Otherwise the rest is about a rounding that never happens."""
        repo = GnuCashRepository(book_with_thousandths)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            query = Query()
            query.search_for('Trans')
            query.set_book(repo.book)
            held = sorted(
                f'{split.GetAmount().num()}/{split.GetAmount().denom()}'
                for raw in query.run()
                for split in Transaction(instance=raw).GetSplitList()
                if 'Expenses' in split.GetAccount().get_full_name())
            query.destroy()
            assert held == ['18191/1000', '27245/1000'], held
        finally:
            repo.close()


class TestTheClosingEntry:
    def test_it_closes(self, book_with_thousandths):
        result = CliRunner().invoke(
            cli, ['close-books', book_with_thousandths, '--closing-date', '2026-12-31'])

        assert result.exit_code == 0, result.output

    def test_nothing_is_scrubbed_into_an_imbalance(self, book_with_thousandths):
        """What two independently truncated sides produced."""
        assert CliRunner().invoke(
            cli, ['close-books', book_with_thousandths,
                  '--closing-date', '2026-12-31']).exit_code == 0

        rows = _closing_entry(book_with_thousandths)
        assert rows is not None, 'no closing entry was written'
        assert not [name for name, _v in rows if 'Imbalance' in name], rows

    def test_the_splits_sum_to_zero(self, book_with_thousandths):
        assert CliRunner().invoke(
            cli, ['close-books', book_with_thousandths,
                  '--closing-date', '2026-12-31']).exit_code == 0

        rows = _closing_entry(book_with_thousandths)
        assert sum(int(v.split('/')[0]) for _n, v in rows) == 0, rows

    def test_each_account_closes_at_the_cent(self, book_with_thousandths):
        """18.191 rounds to 18.19 and 27.245 to 27.25 — GnuCash's rounding."""
        assert CliRunner().invoke(
            cli, ['close-books', book_with_thousandths,
                  '--closing-date', '2026-12-31']).exit_code == 0

        rows = dict(_closing_entry(book_with_thousandths))
        assert rows['Expenses.Fuel'] == '-1819/100', rows
        assert rows['Expenses.Oil'] == '-2725/100', rows

    def test_equity_takes_back_exactly_what_was_placed(self,
                                                       book_with_thousandths):
        """44.44, the sum of the rounded sides — not 45.436 truncated."""
        assert CliRunner().invoke(
            cli, ['close-books', book_with_thousandths,
                  '--closing-date', '2026-12-31']).exit_code == 0

        # Closing is per currency, so equity lands on the CAD sub-account.
        rows = dict(_closing_entry(book_with_thousandths))
        assert rows['Equity.Retained Earnings.CAD'] == '4544/100', rows

    def test_the_book_validates_afterwards(self, book_with_thousandths):
        assert CliRunner().invoke(
            cli, ['close-books', book_with_thousandths,
                  '--closing-date', '2026-12-31']).exit_code == 0

        checked = CliRunner().invoke(cli, ['validate', book_with_thousandths])
        assert checked.exit_code == 0, checked.output
        assert 'Imbalance' not in checked.output, checked.output


class TestWhenTruncationDoesNotEvenBalance:
    """Two half-cents: each truncates away, and equity keeps the whole cent.

    The figures above balance by luck — what truncation costs there is a cent
    on Oil's own line, not an unbalanced entry. Here the luck runs out: the
    accounts close to 0.00 and 0.00 while equity closes to 0.01, and GnuCash
    balances what it is handed by inventing `Imbalance-CAD` for the
    difference. On the closing entry, of all of them.
    """

    def test_the_splits_sum_to_zero(self, book_of_half_cents):
        assert CliRunner().invoke(
            cli, ['close-books', book_of_half_cents,
                  '--closing-date', '2026-12-31']).exit_code == 0

        rows = _closing_entry(book_of_half_cents)
        assert rows is not None, 'no closing entry was written'
        assert sum(int(v.split('/')[0]) for _n, v in rows) == 0, rows

    def test_no_imbalance_split_was_invented(self, book_of_half_cents):
        assert CliRunner().invoke(
            cli, ['close-books', book_of_half_cents,
                  '--closing-date', '2026-12-31']).exit_code == 0

        rows = _closing_entry(book_of_half_cents)
        assert not [name for name, _v in rows if 'Imbalance' in name], rows

    def test_each_half_cent_closes_to_a_cent(self, book_of_half_cents):
        """Half-up, which is how GnuCash rounds money."""
        assert CliRunner().invoke(
            cli, ['close-books', book_of_half_cents,
                  '--closing-date', '2026-12-31']).exit_code == 0

        rows = dict(_closing_entry(book_of_half_cents))
        assert rows['Expenses.Fuel'] == '-1/100', rows
        assert rows['Expenses.Oil'] == '-1/100', rows
        assert rows['Equity.Retained Earnings.CAD'] == '2/100', rows
