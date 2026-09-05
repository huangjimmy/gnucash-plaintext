"""The period figure GnuCash computes, and the one this tool computes itself.

`xaccAccountGetNoclosingBalanceChangeForPeriod` arrived after GnuCash 3.4, and
it is the only call the income statement needs that 3.4 has not.
`services/income_statement.py` therefore carries
`_change_over_the_period_without_closings`, which walks the account's own
splits and skips the ones whose transaction is flagged closing.

That fallback runs on exactly one supported build and the engine answers on
every other, so left alone it would be a figure nobody checks — right where a
wrong one is quietly a wrong tax return. These compare the two on every build
that can make the comparison, over a book whose books have been closed, which
is the case where a closing entry exists to be excluded at all.

Book: Income 1000, Expenses 300 in 2026 — the same fixture the closing-entry
tests use, so the numbers here are the ones recorded there.
"""

from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import numeric_to_fraction
from repositories.gnucash_repository import GnuCashRepository
from services.income_statement import _change_over_the_period_without_closings

BOOK = str(Path('tests/fixtures/closing_book.txt'))
#: The same accounts, with activity on 2026-01-01 and 2026-12-31 and outside
#: the year on either side. The book above has neither: both its transactions
#: are interior, so the two implementations agree there without the date
#: comparison ever deciding anything — and the fallback compares calendar days
#: where the engine compares time64s, which is exactly where they could part.
ON_THE_EDGES = str(
    Path('tests/fixtures/closing_book_with_activity_on_the_boundaries.txt'))
START = date(2026, 1, 1)
END = date(2026, 12, 31)
PAST_THE_END = END + timedelta(days=1)


def _a_closed_book(runner, tmp_path, ledger=BOOK, name='book.gnucash'):
    """The fixture book, with `close-books` run over it.

    Closed, because an open book has no closing entry in it and the fallback
    would then agree with the engine by having nothing to leave out.
    """
    gf = tmp_path / name
    assert runner.invoke(cli, ['import', '--new', str(gf), ledger]).exit_code == 0
    closed = runner.invoke(cli, ['close-books', str(gf),
                                 '--closing-date', '2026-12-31'])
    assert closed.exit_code == 0, closed.output
    return gf


def _income_and_expense_accounts(book):
    from gnucash.gnucash_core_c import ACCT_TYPE_EXPENSE, ACCT_TYPE_INCOME
    return [a for a in book.get_root_account().get_descendants()
            if a.GetType() in (ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE)]


class TestTheTwoAgree:
    """Same account, same period, both answers."""

    def test_every_income_and_expense_account_reads_the_same(self, tmp_path):
        runner = CliRunner()
        repo = GnuCashRepository(str(_a_closed_book(runner, tmp_path)))
        repo.open()
        try:
            accounts = _income_and_expense_accounts(repo.book)
            assert accounts, 'the fixture book has no income or expense account'
            for account in accounts:
                if not hasattr(account, 'GetNoclosingBalanceChangeForPeriod'):
                    pytest.skip('this GnuCash computes no noclosing change')
                engine = numeric_to_fraction(
                    account.GetNoclosingBalanceChangeForPeriod(
                        START, PAST_THE_END, False))
                ours = _change_over_the_period_without_closings(
                    account, START, PAST_THE_END)
                assert ours == engine, account.GetName()
        finally:
            repo.close()

    def test_and_neither_counts_the_closing_entry(self, tmp_path):
        """Otherwise the test above passes on two figures that are both wrong.

        Closing zeroes income and expense, so the plain change over the year
        is 0 for every one of these accounts while the figure the statement
        wants is the activity — 1000 and 300. If the fallback counted the
        closing splits it would read 0 too, and match an engine call asked the
        same wrong question.
        """
        runner = CliRunner()
        repo = GnuCashRepository(str(_a_closed_book(runner, tmp_path)))
        repo.open()
        try:
            found = {}
            for account in _income_and_expense_accounts(repo.book):
                with_closings = numeric_to_fraction(
                    account.GetBalanceChangeForPeriod(
                        START, PAST_THE_END, False))
                without = _change_over_the_period_without_closings(
                    account, START, PAST_THE_END)
                found[account.GetName()] = (with_closings, without)
            activity = {name: without for name, (_, without) in found.items()
                        if without != 0}
            assert activity, f'every account read zero: {found}'
            for name, (with_closings, without) in found.items():
                if without != 0:
                    assert with_closings == 0, (
                        f'{name}: the books are closed, so the change '
                        f'including closings should be zero, not {with_closings}')
        finally:
            repo.close()


class TestTheDaysAtEitherEnd:
    """Where the two could part: the fallback compares calendar days and the
    engine compares time64s, so the first and last day of the period are the
    figures worth checking. A fiscal year whose opening or closing day carries
    a transaction is the ordinary case.
    """

    def test_the_two_agree_with_activity_on_both_edges(self, tmp_path):
        runner = CliRunner()
        book = _a_closed_book(runner, tmp_path, ledger=ON_THE_EDGES,
                              name='edges.gnucash')
        repo = GnuCashRepository(str(book))
        repo.open()
        try:
            for account in _income_and_expense_accounts(repo.book):
                if not hasattr(account, 'GetNoclosingBalanceChangeForPeriod'):
                    pytest.skip('this GnuCash computes no noclosing change')
                engine = numeric_to_fraction(
                    account.GetNoclosingBalanceChangeForPeriod(
                        START, PAST_THE_END, False))
                ours = _change_over_the_period_without_closings(
                    account, START, PAST_THE_END)
                assert ours == engine, account.GetName()
        finally:
            repo.close()

    def test_and_the_edges_are_in_while_the_days_outside_are_not(self, tmp_path):
        """The figures, so a test that agreed on two wrong numbers would fail.

        Sales take 11.00 on 2026-01-01 and 1000.00 in June, and not the 7.00
        of 2025-12-31 or the 17.00 of 2027-01-01. Office spends 300.00 in July
        and 13.00 on 2026-12-31, the year's last day.
        """
        runner = CliRunner()
        book = _a_closed_book(runner, tmp_path, ledger=ON_THE_EDGES,
                              name='edges.gnucash')
        repo = GnuCashRepository(str(book))
        repo.open()
        try:
            read = {account.GetName():
                    _change_over_the_period_without_closings(
                        account, START, PAST_THE_END)
                    for account in _income_and_expense_accounts(repo.book)}
        finally:
            repo.close()

        assert read['Sales'] == Fraction(-1011), read
        assert read['Office'] == Fraction(313), read
