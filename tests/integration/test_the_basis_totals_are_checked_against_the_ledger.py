"""What a currency's bases hold between them, against what the ledger says.

`--verify-costs` asks each basis about itself: is its balance between zero and
what it brought in, and does a stored cost agree with the transaction. Both are
questions about one split, and a book can pass every one of them while the
currency as a whole does not add up.

The book-wide question is per currency: what the bases hold between them
against what arrived less what was sold against a basis. Two sides written by
different mechanisms — a KVP on one, the transactions themselves on the other —
so they can disagree, and nothing was looking.

Reported, not refused. A book that disagrees here is a book to go and look at,
and the run says which currency, both figures and the difference; it is not a
reason to refuse to read the book, which is what `--verify-costs` is for.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

BUY = 'tests/fixtures/fx_buy_and_borrow_usd.txt'
RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'


def _book(tmp_path):
    gnc = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(gnc), BUY,
                                      '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    return gnc


def _quietly_lower_one_balance(book, to='20.00'):
    """Take currency off a basis without recording a sale.

    Which is what a hand-edit, a half-finished script, or a bug in this tool
    leaves behind — and what no per-basis check can see: 20.00 is between zero
    and the 100.00 that arrived, so the basis passes every question asked of
    it on its own.
    """
    from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.foreign_currency import establishes_cost_basis, iter_splits

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        for split in iter_splits(repo.book):
            if not establishes_cost_basis(split):
                continue
            held = dict(get_custom_metadata(split) or {})
            if held.get('cost_basis_balance') != '100.00':
                continue
            held['cost_basis_balance'] = to
            transaction = split.GetParent()
            transaction.BeginEdit()
            set_custom_metadata(split, held)
            transaction.CommitEdit()
            repo.save()
            return
        raise AssertionError('no basis to lower')
    finally:
        repo.close()


@pytest.fixture
def book_that_adds_up(tmp_path):
    return _book(tmp_path)


@pytest.fixture
def book_that_does_not(tmp_path):
    gnc = _book(tmp_path)
    _quietly_lower_one_balance(gnc)
    return gnc


class TestASaleAgainstABasisWithNoBalanceRecorded:
    """Both sides skip the same bases, or the check invents a discrepancy.

    A basis with no balance recorded is left out of what the bases hold and
    out of what arrived — nothing knows how much of it is unsold. Its sales
    were counted anyway, so the ledger figure came down while the basis's own
    arrival never went up, and the run reported currency accounted for by no
    basis on a book that is entirely consistent.
    """

    def test_no_warning_on_a_consistent_book(self, tmp_path):
        from infrastructure.gnucash.kvp import (
            get_custom_metadata,
            set_custom_metadata,
        )
        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )
        from services.foreign_currency import establishes_cost_basis, iter_splits

        book = _book(tmp_path)
        # Sell against one basis, then take that basis's balance away — the
        # state a book from the GnuCash GUI is in, and what `_mark_spent_credit`
        # and `_strip_a_settlements_basis` leave behind.
        listed = CliRunner().invoke(cli, ['fx-balances', str(book)])
        guid = next(line.split()[1] for line in listed.output.splitlines()
                    if 'Assets:Bank:USD' in line)
        sale = tmp_path / 'sale.txt'
        sale.write_text(
            Path('tests/fixtures/fx_sell_40_usd_at_its_own_cost.txt').read_text()
            .replace('{basis}', guid))
        assert CliRunner().invoke(cli, ['import', str(book), str(sale),
                                        '--fx-rates', RATES]).exit_code == 0

        # Only the basis the sale named. Stripping every basis leaves nothing
        # on either side and no currency to compare, so the check says nothing
        # whatever it does — a test that cannot fail. The book must keep one
        # basis with a balance for the sums to be sums at all.
        from services.foreign_currency import split_guid

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.NORMAL)
        try:
            stripped = 0
            for split in iter_splits(repo.book):
                if not establishes_cost_basis(split):
                    continue
                if str(split_guid(split)).replace('-', '').lower() != guid:
                    continue
                held = dict(get_custom_metadata(split) or {})
                held.pop('cost_basis_balance', None)
                transaction = split.GetParent()
                transaction.BeginEdit()
                set_custom_metadata(split, held)
                transaction.CommitEdit()
                stripped += 1
            assert stripped == 1, f'expected to strip one basis, did {stripped}'
            repo.save()
        finally:
            repo.close()

        result = CliRunner().invoke(cli, ['fx-balances', str(book),
                                          '--verify-costs'])

        # Any warning at all, not one wording of it: counted unconditionally
        # the sale made the bases look 40.00 USD *over* what arrived, which is
        # the other branch of the same message.
        assert 'warning: the USD cost bases' not in result.output, result.output


class TestABookThatAddsUp:
    def test_nothing_is_said_about_the_totals(self, book_that_adds_up):
        result = CliRunner().invoke(cli, ['fx-balances', str(book_that_adds_up),
                                          '--verify-costs'])

        assert result.exit_code == 0, result.output
        assert 'accounted for by no basis' not in result.output, result.output


class TestABookThatDoesNot:
    def test_every_basis_still_passes_on_its_own(self, book_that_does_not):
        """Which is why this check has to exist: 20.00 of a 100.00 basis is
        a balance every per-basis question accepts."""
        result = CliRunner().invoke(cli, ['fx-balances', str(book_that_does_not),
                                          '--verify-costs'])

        assert 'disagree with their own figures' not in result.output, \
            result.output

    def test_the_currency_and_both_figures_are_named(self, book_that_does_not):
        result = CliRunner().invoke(cli, ['fx-balances', str(book_that_does_not),
                                          '--verify-costs'])

        assert 'USD' in result.output, result.output
        assert '120.00' in result.output, result.output      # what they hold
        assert '200.00' in result.output, result.output      # what arrived
        assert '80.00' in result.output, result.output       # the difference

    def test_it_is_a_warning_and_not_a_refusal(self, book_that_does_not):
        """The book is readable; it is the book that needs looking at."""
        result = CliRunner().invoke(cli, ['fx-balances', str(book_that_does_not),
                                          '--verify-costs'])

        assert result.exit_code == 0, result.output

    def test_the_listing_alone_does_not_say_it(self, book_that_does_not):
        """`fx-balances` without the flag reports what it always did."""
        result = CliRunner().invoke(cli, ['fx-balances',
                                          str(book_that_does_not)])

        assert result.exit_code == 0, result.output
        assert 'accounted for by no basis' not in result.output, result.output
