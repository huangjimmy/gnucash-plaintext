"""A disposal giving no cost basis is refused with its amount written as the ledger writes it.

45.50 USD, not `91/2` — the figure is what was spent, at the currency's own
decimals, as every other refusal on the way in writes one.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.integration.text_report_pages import book_from

BOOK = 'a_cad_book_that_bought_a_thousand_usd.txt'
SPEND = 'tests/fixtures/a_spend_of_45_50_usd_giving_no_cost_basis.txt'


def test_the_amount_is_written_at_the_currencys_decimals(tmp_path):
    done = CliRunner().invoke(cli, ['import', str(book_from(tmp_path, BOOK)), SPEND])

    assert ('error: Sell 45.50 USD at 1.40: this transaction is a sale of 45.50 USD '
            'the book held for 63.70 CAD') in done.output, done.output
