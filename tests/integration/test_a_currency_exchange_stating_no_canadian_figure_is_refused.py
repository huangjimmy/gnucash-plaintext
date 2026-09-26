"""US dollars exchanged for Hong Kong dollars in a transaction stating no Canadian figure are refused.

The US dollars leave their cost basis at what they cost in Canadian dollars; the
Hong Kong dollars arrive with no cost to open one at, and no split can state
what the exchange realized. Imported, 1,300.00 CAD of cost left the book with
nothing to show for it. So it is refused, as a share sale written wholly in a
foreign currency is.

`tests/fixtures/us_dollars_exchanged_for_hong_kong_dollars_stating_no_canadian_figure.txt`.
"""

from click.testing import CliRunner

from cli.main import cli

LEDGER = ('tests/fixtures/us_dollars_exchanged_for_hong_kong_dollars_'
          'stating_no_canadian_figure.txt')


def test_the_exchange_is_refused_and_says_how_to_write_it(tmp_path):
    done = CliRunner().invoke(
        cli, ['import', '--new', str(tmp_path / 'book.gnucash'), LEDGER])

    assert 'Errors:       1' in done.output, done.output
    assert ('error: Exchange 1,000.00 USD for 7,800.00 HKD, stated in HKD: this '
            'transaction sells 1000.00 USD, which cost 1.3 CAD/USD, for '
            '7800.00 HKD, and is written wholly in HKD, so no split in it can '
            'state what the exchange realized, and the HKD arrive with no cost '
            'to open a cost basis at. Write it in CAD, each split valued at '
            'what it is worth in CAD, and put the difference on a '
            '`$residual$` split.') in done.output, done.output


def test_the_us_dollars_keep_their_cost_basis(tmp_path):
    book = tmp_path / 'book.gnucash'
    CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    listing = CliRunner().invoke(cli, ['fx-balances', str(book)]).output

    assert 'Total USD cost basis balance: 1,000.00 USD' in listing, listing
