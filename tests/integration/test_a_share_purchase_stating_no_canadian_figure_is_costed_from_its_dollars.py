"""A purchase written wholly in a foreign currency takes its cost from the currency it spent.

Two routes can put a book-currency cost on a holding, and the finished book
looks the same either way:

* where any split of the transaction carries a figure in the book's own
  currency, the cost is read out of the transaction — value over amount,
  through the rate that split states;
* where none does, there is nothing to read, and the cost comes from the cost
  basis the currency left. That rate travels onto whatever those units bought.

This is the second. `tests/fixtures/shares_bought_in_a_transaction_stating_no_canadian_figure.txt`
buys two US-listed shares in one transaction stated wholly in US dollars, so no
Canadian figure appears in it anywhere, and 2,200.00 USD leave a cost basis
carrying 1.30.

**What travels is the rate, not the total.** 2,860.00 CAD of cost goes with those
dollars and divides the way the dollars divided: 2,000.00 USD to USD_TECH at
2,600.00, and 200.00 USD to USD_CORP at 260.00. Handing the whole 2,860.00 to
the holding most of it bought would price USD_TECH at 57.20 and leave USD_CORP
at nothing.

`tests/fixtures/a_broker_fee_two_us_loans_and_part_of_the_shares_sold.txt` is
the first route: its fee split is in Canadian dollars, and that one figure is
enough for the cost to be derived from the transaction.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run
from tests.integration.text_report_pages import book_from, key_of

LEDGER = 'shares_bought_in_a_transaction_stating_no_canadian_figure.txt'


def _sheet(book):
    drawn = _run(CliRunner(), 'balance-sheet', str(book),
                 '--as-of', '2029-12-31', '--no-itemize')
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


class TestTheCostDividesTheWayTheDollarsDid:
    def test_each_holding_is_costed_at_its_own_share_of_them(self, tmp_path):
        """52.00 a share and 26.00 a share, not 57.20 and nothing."""
        listing = CliRunner().invoke(
            cli, ['fx-balances', str(book_from(tmp_path, LEDGER))]).output

        assert '52 CAD/USD_TECH' in listing, listing
        assert '26 CAD/USD_CORP' in listing, listing

    def test_the_dollars_that_paid_are_drawn_down(self, tmp_path):
        """10,000.00 bought, 2,200.00 spent, 1,100.00 back from the sale."""
        listing = CliRunner().invoke(
            cli, ['fx-balances', str(book_from(tmp_path, LEDGER))]).output

        assert 'Total USD cost basis balance: 8,900.00 USD' in listing, listing
        assert 'Total USD held in accounts: 8,900.00 USD' in listing, listing


class TestWhatTheSheetThenSays:
    def test_the_gain_on_the_shares_is_measured_against_the_carried_cost(self, tmp_path):
        """20 shares costing 52.00 fetched 1,100.00 USD at 1.20, so 280.00 is realized."""
        page = _sheet(book_from(tmp_path, LEDGER))

        assert key_of(page, 'realized_gains_other') == '280.00 CAD'
        assert key_of(page, 'realized_gains_fx') == '0.00 CAD'

    def test_what_is_still_held_is_worth_more_than_it_cost(self, tmp_path):
        """30 USD_TECH cost 1,560.00 and are worth 1,980.00; 10 USD_CORP cost 260.00 and are worth 240.00."""
        page = _sheet(book_from(tmp_path, LEDGER))

        assert key_of(page, 'unrealized_gains_other') == '400.00 CAD'

    def test_the_page_balances(self, tmp_path):
        page = _sheet(book_from(tmp_path, LEDGER))

        assert key_of(page, 'total_assets') == '14900.00 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '14900.00 CAD'

    def test_the_itemized_entry_states_the_price_in_us_dollars_and_the_rate(self, tmp_path):
        """The purchase was written in US dollars, so that is the pair price it states."""
        drawn = _run(CliRunner(), 'balance-sheet', str(book_from(tmp_path, LEDGER)),
                     '--as-of', '2029-12-31')
        assert drawn.exit_code == 0, drawn.output

        assert ('\t\t\t\t\t\tcost_share_price: 40 # USD_TECH in USD, on the day'
                ' it was bought') in drawn.output.splitlines(), drawn.output
        assert ('\t\t\t\t\t\tcost_rate: 1.3 # CAD per USD, on that same day'
                ) in drawn.output.splitlines(), drawn.output
        assert ('\t\t\t\t\t\tcost_share_price_in_base: 52 # cost_share_price *'
                ' cost_rate') in drawn.output.splitlines(), drawn.output
