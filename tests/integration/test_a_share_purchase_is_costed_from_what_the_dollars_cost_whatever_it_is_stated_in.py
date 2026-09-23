"""A purchase with no Canadian figure costs its shares from what the spent dollars cost, whatever it is stated in.

The cost is what the cost basis gave up: 2,000.00 USD that cost 1.30 is
2,600.00 CAD. The transaction's own figures say how that divides across what
was bought, as shares of what was paid — they are in whatever currency the
transaction is stated in, which need not be the currency spent.

`tests/fixtures/shares_bought_with_us_dollars_in_a_transaction_stated_in_hong_kong_dollars.txt`
states the purchase in Hong Kong dollars. Read as a count of US dollars, its
15,600.00 HKD was multiplied by the 1.30 CAD a US dollar cost, and the shares
were costed at 405.60 a share where they cost 52.00.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.integration.text_report_pages import book_from

LEDGER = 'shares_bought_with_us_dollars_in_a_transaction_stated_in_hong_kong_dollars.txt'


def test_dollars_valued_at_nothing_are_refused_with_that_said(tmp_path):
    """Nothing says how their cost divides, and a division by zero said nothing."""
    done = CliRunner().invoke(
        cli, ['import', '--new', str(tmp_path / 'book.gnucash'),
              'tests/fixtures/shares_bought_with_dollars_valued_at_nothing.txt'])

    assert 'Errors:       1' in done.output, done.output
    assert ('error: Buy 50 USD_TECH for 2,000.00 USD, valued at nothing: the '
            'currency that paid for what this transaction buys is valued at '
            'nothing in it, so nothing says how what that currency cost divides '
            'across what it bought. State each split at what it is worth.') \
        in done.output, done.output


def test_the_shares_cost_what_the_dollars_cost(tmp_path):
    """2,000.00 USD at 1.30 for 50 shares: 52.00 a share."""
    listing = CliRunner().invoke(
        cli, ['fx-balances', str(book_from(tmp_path, LEDGER))]).output

    assert '52 CAD/USD_TECH' in listing, listing
    assert 'Total USD cost basis balance: 8,000.00 USD' in listing, listing
