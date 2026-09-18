"""A realized figure that was never worked out is not stated as zero.

`realized_gains_fx` is summed from what each disposal's `$residual$` split came
to in the book's own currency, and every cost this tool records is in that
currency. A page asked for in another currency therefore has nothing to sum,
and a book kept in another currency has no recorded cost to sum from.

Printed anyway, that comes out as `realized_gains_fx: 0.00 USD` — a zero given
as a fact. Measured on a book that bought 1,000.00 USD at 1.30 and sold every
one at 1.40: its own page states `realized_gains_fx: 100.00 CAD`, and the same
book asked for in US dollars stated `0.00 USD`, which says the book realized
nothing.

So the two realized keys are left off where the figure was not measured, the
way a book using trading accounts leaves off all of them. A key states
something the book has; absence is the honest answer where nothing was worked
out, and it is how this suite already asserts the trading-accounts case.

The unrealized keys stay either way: those come from GnuCash's own revaluation,
which is computed in whatever currency the page is drawn in.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import key_of

A_CAD_BOOK = 'tests/fixtures/a_cad_book_holding_us_listed_shares.txt'
A_BOOK_KEPT_IN_HKD = 'tests/fixtures/a_book_kept_in_hkd.txt'


def _states(page, key):
    """Whether the page carries this key.

    Asked of whole lines, never as a substring: the page states
    `unrealized_gains_fx`, which contains `realized_gains_fx`, so
    `'realized_gains_fx' not in page` is false however the page is drawn.
    """
    return any(line.strip().startswith(f'{key}: ') for line in page.splitlines())


def _sheet(tmp_path, ledger, as_of, *extra):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), ledger)
    assert made.exit_code == 0, made.output
    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', as_of, *extra)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


class TestAPageDrawnInTheBooksOwnCurrency:
    """The figure is measured, so the keys are stated — zero included."""

    def test_both_realized_keys_are_stated(self, tmp_path):
        page = _sheet(tmp_path, A_CAD_BOOK, '2026-12-31')

        assert key_of(page, 'realized_gains_fx') == '0.00 CAD'
        assert key_of(page, 'total_realized_gains') == '0.00 CAD'


class TestAPageAskedForInAnotherCurrency:
    """Nothing to sum, so nothing is stated."""

    def test_neither_realized_key_is_on_the_page(self, tmp_path):
        page = _sheet(tmp_path, A_CAD_BOOK, '2026-12-31', '--currency', 'USD')

        assert not _states(page, 'realized_gains_fx'), page
        assert not _states(page, 'total_realized_gains'), page

    def test_the_unrealized_keys_are_still_stated(self, tmp_path):
        """Those are GnuCash's own revaluation, in whatever currency is asked."""
        page = _sheet(tmp_path, A_CAD_BOOK, '2026-12-31', '--currency', 'USD')

        assert key_of(page, 'unrealized_gains_fx').endswith(' USD'), page
        assert key_of(page, 'total_unrealized_gains').endswith(' USD'), page

    def test_the_sheet_still_balances(self, tmp_path):
        page = _sheet(tmp_path, A_CAD_BOOK, '2026-12-31', '--currency', 'USD')

        assert key_of(page, 'total_assets') == key_of(
            page, 'total_liabilities_and_equity')


class TestABookKeptInAnotherCurrency:
    """Every cost this tool records is in Canadian dollars, so a book kept in
    Hong Kong dollars has none for a realized figure to be summed from."""

    def test_neither_realized_key_is_on_the_page(self, tmp_path):
        page = _sheet(tmp_path, A_BOOK_KEPT_IN_HKD, '2026-03-31')

        assert not _states(page, 'realized_gains_fx'), page
        assert not _states(page, 'total_realized_gains'), page

    def test_the_sheet_still_balances(self, tmp_path):
        page = _sheet(tmp_path, A_BOOK_KEPT_IN_HKD, '2026-03-31')

        assert key_of(page, 'total_assets') == '37330.00 HKD'
        assert key_of(page, 'total_liabilities_and_equity') == '37330.00 HKD'
