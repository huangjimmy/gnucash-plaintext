"""A balance sheet measures against the costs the book had on its own date.

A `cost_basis_balance` records what a cost basis has left **now**. Read as it
stands, a sheet drawn at an earlier date measures the currency the book held
then against costs it had not yet paid — and every `report --fiscal-year-end`
for a year already closed is drawn at such a date.

This book buys 1,000.00 USD at 1.30 in January, sells every one of them on
1 August against that cost basis, and buys 1,000.00 more the same day at 1.50.
It holds 1,000.00 USD before and after, and its cost bases hold 1,000.00 USD
before and after — only the cost behind them changes, from 1,300.00 to
1,500.00.

So a 30 June sheet priced at 1.35 is the case that tells the two apart. Read as
of that date it is a gain of 50.00: 1,350.00 of worth against the 1,300.00
those January dollars cost. Read as the bases stand at the end of the book it
was a loss of 150.00, because the quantities matched while the costs did not —
nothing refused it, the page showed its working against a cost basis the book
had not yet opened, and `total_assets` stood 200.00 above the other side.
"""

import re
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import block_of, block_total_of, key_of

BOUGHT = ('tests/fixtures/'
          'a_cad_book_that_bought_usd_before_selling_and_rebuying_it.txt')
SOLD_AND_REBOUGHT = 'tests/fixtures/the_usd_sold_and_rebought_at_a_higher_rate.txt'

# August's sale, as `realized_gains_fx` states it, and the nothing a sheet
# drawn before it states instead.
THE_AUGUST_GAIN = '\n'.join((
    '\t\trealized_gains_fx: 200.00',
    '\t\tsplits:',
    '\t\t\tsplit:',
    '\t\t\t\tdate: 2026-08-01',
    '\t\t\t\taccount: "Income:FX Gain"',
    '\t\t\t\tamount: 200.00'))
NOTHING_REALIZED = '\n'.join((
    '\t\trealized_gains_fx: 0.00',
    '\t\tsplits: # there is no split'))


def _book(tmp_path):
    """The January purchase, then August's sale and repurchase on top of it.

    The sale states the guid of the cost basis it draws on, and a guid is minted
    fresh on each import, so it is read from `fx-balances` and substituted —
    the way every other disposal fixture here is applied.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    bought = _run(runner, 'import', '--new', str(book), BOUGHT)
    assert bought.exit_code == 0, bought.output

    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    found = re.search(r'\b([0-9a-f]{32})\b', listing.output)
    assert found, listing.output

    ledger = tmp_path / 'sold.txt'
    ledger.write_text(
        Path(SOLD_AND_REBOUGHT).read_text(encoding='utf-8').replace(
            '{usd_basis}', found.group(1)),
        encoding='utf-8')
    sold = _run(runner, 'import', str(book), str(ledger))
    assert sold.exit_code == 0, sold.output
    return book


def _sheet(tmp_path, as_of):
    drawn = _run(CliRunner(), 'balance-sheet', str(_book(tmp_path)),
                 '--as-of', as_of)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


class TestDrawnBeforeTheSaleThatChangedTheCost:
    """30 June: the book holds the January dollars, at what January cost."""

    def test_the_gain_is_measured_against_the_cost_of_the_day(self, tmp_path):
        page = _sheet(tmp_path, '2026-06-30')

        assert key_of(page, 'unrealized_gains_fx') == '50.00 CAD'
        assert key_of(page, 'total_unrealized_gains') == '50.00 CAD'

    def test_nothing_is_realized_yet(self, tmp_path):
        """August's sale is after this date, so it has not happened here."""
        page = _sheet(tmp_path, '2026-06-30')

        assert block_of(page, 'realized_gains_fx') == NOTHING_REALIZED

    def test_the_working_cites_the_cost_basis_the_book_then_had(self, tmp_path):
        """The cost basis under the key is January's, at what January paid.

        `cost_value:` is the basis's balance at the cost it was opened at, so
        the 1,300.00 of January stands there and the 1,500.00 of August — a
        cost basis this sheet's date is before — appears nowhere on the page.
        """
        page = _sheet(tmp_path, '2026-06-30')

        block = block_of(page, 'unrealized_gains_assets_fx')
        assert ('\t\t\t\t\t\tcost_value: 1300.00'
                ' # cost_basis_balance * cost_share_price_in_base'
                ) in block.splitlines(), block
        assert '1500.0' not in block, block

    def test_the_sheet_balances(self, tmp_path):
        page = _sheet(tmp_path, '2026-06-30')

        assert key_of(page, 'total_assets') == '10050.00 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '10050.00 CAD'


class TestDrawnAtTheYearEnd:
    """After both, and unchanged by reading the bases as of the date."""

    def test_the_august_gain_is_realized_and_nothing_is_left_unrealized(self, tmp_path):
        page = _sheet(tmp_path, '2026-12-31')

        assert block_of(page, 'realized_gains_fx') == THE_AUGUST_GAIN
        assert key_of(page, 'unrealized_gains_fx') == '0.00 CAD'

    def test_the_sheet_balances(self, tmp_path):
        page = _sheet(tmp_path, '2026-12-31')

        assert key_of(page, 'total_assets') == '10200.00 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '10200.00 CAD'


class TestDrawnBeforeAnythingWasBought:
    """31 January: the purchase is in, at the price it was made at."""

    def test_no_gain_either_way(self, tmp_path):
        page = _sheet(tmp_path, '2026-01-31')

        assert block_of(page, 'realized_gains_fx') == NOTHING_REALIZED
        assert key_of(page, 'unrealized_gains_fx') == '0.00 CAD'
        assert key_of(page, 'total_assets') == '10000.00 CAD'
