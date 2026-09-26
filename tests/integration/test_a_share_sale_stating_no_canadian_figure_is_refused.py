"""A share sale written wholly in a foreign currency is refused, as the matching repayment is.

Shares with a cost basis in Canadian dollars leave at what they cost, and the
difference between that and what they fetched is realized as they go —
`$residual$` states it, in the book's own currency. A sale written wholly in
US dollars has no split in that currency to state it, and the dollars it brings
in arrive with no cost to open a cost basis at.

Imported regardless, it drew the shares' cost basis down and left the gain
stated nowhere. `tests/fixtures/shares_sold_in_a_transaction_stating_no_canadian_figure.txt`
sells 8 of 20 shares that cost 260.00 CAD each for 2,080.00 USD.
"""

from click.testing import CliRunner

from cli.main import cli

LEDGER = 'tests/fixtures/shares_sold_in_a_transaction_stating_no_canadian_figure.txt'


def test_the_sale_is_refused_and_says_how_to_write_it(tmp_path):
    done = CliRunner().invoke(
        cli, ['import', '--new', str(tmp_path / 'book.gnucash'), LEDGER])

    assert 'Errors:       1' in done.output, done.output
    assert ('error: Sell 8 USD_TECH for 2,080.00 USD, written wholly in US '
            'dollars: this transaction sells 8.0000 USD_TECH, which cost 260 '
            'CAD/USD_TECH, and is written wholly in USD, so no split in it can '
            'state what the sale realized. Write it in CAD, the shares at what '
            'they cost and the currency at what it fetched, and put the '
            'difference on a `$residual$` split.') in done.output, done.output


def test_the_shares_keep_their_cost_basis(tmp_path):
    """Nothing is drawn down by a sale that was not imported."""
    book = tmp_path / 'book.gnucash'
    CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    listing = CliRunner().invoke(cli, ['fx-balances', str(book)]).output

    assert 'Total USD_TECH cost basis balance: 20.0000 USD_TECH' in listing, listing
