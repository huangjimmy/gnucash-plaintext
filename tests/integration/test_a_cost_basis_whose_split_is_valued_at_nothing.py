"""A cost basis on a split the transaction prices at nothing states its cost whole.

The itemized entry usually divides what a unit cost into the price the trade
happened at and the rate into the book's currency, because the two multiplied
out are the figure every gain is measured against and a reader cannot check it
otherwise.

There is nothing to divide where the transaction gives no price. This book moves
1,000.00 USD in an entry stated in Hong Kong dollars and valued at nothing, so
the split's value over its amount is zero; what says the dollars cost 1.30 is
the `cost_basis_cost:` on the split itself. The entry then states that cost as
both figures, at a rate of 1 — the same shape a currency bought with the book's
own money takes, and for the same reason: there is one number, not two.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run
from tests.integration.text_report_pages import book_from

LEDGER = 'a_cost_basis_whose_split_is_valued_at_nothing.txt'


def test_the_cost_basis_is_opened_at_the_stated_cost(tmp_path):
    listing = CliRunner().invoke(
        cli, ['fx-balances', str(book_from(tmp_path, LEDGER))]).output

    assert '1.3 CAD/USD' in listing, listing
    assert 'Total USD cost basis balance: 1,000.00 USD' in listing, listing


def test_the_entry_states_the_cost_as_both_figures_at_a_rate_of_one(tmp_path):
    drawn = _run(CliRunner(), 'balance-sheet', str(book_from(tmp_path, LEDGER)),
                 '--as-of', '2033-12-31')
    assert drawn.exit_code == 0, drawn.output

    lines = drawn.output.splitlines()
    assert ('\t\t\t\t\t\tcost_share_price: 1.3 # USD in CAD, on the day it was'
            ' bought') in lines, drawn.output
    assert '\t\t\t\t\t\tcost_rate: 1 # CAD per CAD, on that same day' in lines, drawn.output
    assert ('\t\t\t\t\t\tcost_share_price_in_base: 1.3 # cost_share_price *'
            ' cost_rate') in lines, drawn.output
