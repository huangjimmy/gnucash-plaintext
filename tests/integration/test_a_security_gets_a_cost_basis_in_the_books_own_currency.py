"""A share is a holding with a cost, and the cost is in the book's own currency.

Q-046: every commodity a book holds that is not its own currency is the same
kind of thing. A holding is a quantity, a cost per unit in the book's currency
and a price per unit in the book's currency, and the difference between the two
is the gain — unrealized while it is held, realized when it goes. A share is
counted in shares and a dollar in dollars, and once both are converted that
distinction has no consequence.

So a share purchase opens a cost basis like any other arrival, and the same
rules follow it: a transaction that holds one cannot be edited in place, and a
disposal says which cost basis it came out of.
"""

from click.testing import CliRunner

from cli.main import cli

FIXTURE = 'tests/fixtures/stock_purchase_in_cad_book.txt'


def test_a_share_purchase_opens_a_cost_basis_at_what_it_cost(tmp_path):
    """10 units bought for 500.00 CAD cost 50.00 a unit, and that is the cost."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book), FIXTURE])
    assert result.exit_code == 0, result.output

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert '50 CAD/USTECH' in listing, listing
    assert 'Total USTECH cost basis balance: 10.0000' in listing, listing


def test_the_cost_basis_travels_through_an_export_and_back(tmp_path):
    """The export writes the balance, and re-importing reads the same book."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), FIXTURE]).exit_code == 0

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported)]).exit_code == 0
    assert 'cost_basis_balance: "10.0000"' in exported.read_text(), exported.read_text()

    fresh = tmp_path / 'fresh.gnucash'
    again = runner.invoke(cli, ['import', '--new', str(fresh), str(exported)])
    assert again.exit_code == 0, again.output
    listing = runner.invoke(cli, ['fx-balances', str(fresh)]).output
    assert 'Total USTECH cost basis balance: 10.0000' in listing, listing


def test_a_share_count_is_corrected_by_an_edit_in_place(tmp_path):
    """The rule every cost basis follows, now that a share has one.

    A purchase whose cost basis nothing else draws on is read, edited, as a
    new transaction would be (Q-051): 12 shares for the money that bought 10
    opens a cost basis of 12 at the price the two figures make, and the
    balance says what the amounts say.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book), FIXTURE]).exit_code == 0

    exported = tmp_path / 'out.txt'
    assert runner.invoke(cli, ['export', str(book), str(exported)]).exit_code == 0
    text = exported.read_text()
    assert '10.0000 FUND.USTECH' in text, text
    edited = tmp_path / 'edited.txt'
    edited.write_text(text.replace('10.0000 FUND.USTECH', '12.0000 FUND.USTECH'))

    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])

    assert result.exit_code == 0, result.output
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'Total USTECH cost basis balance: 12.0000 USTECH' in listing, listing
    assert 'Total USTECH held in accounts: 12.0000 USTECH' in listing, listing
    verified = runner.invoke(cli, ['fx-balances', str(book), '--verify-costs'])
    assert verified.exit_code == 0, verified.output


def test_a_currency_in_a_securities_typed_account_is_still_currency(tmp_path):
    """What decides it is the commodity, not how the account is typed.

    A `Stock` account denominated in USD holds foreign currency: the type is a
    classification, and the namespace of what it holds is CURRENCY. Dropping
    those types from the debit-side set — on the reasoning that nothing with a
    currency commodity could be typed that way — left this book reporting no
    cost basis at all, with 100.00 USD in it.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(
        cli, ['import', '--new', str(book),
              'tests/fixtures/currency_in_a_stock_typed_account.txt'])
    assert result.exit_code == 0, result.output

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'Total USD cost basis balance: 100.00' in listing, listing
    assert '1.35 CAD/USD' in listing, listing
