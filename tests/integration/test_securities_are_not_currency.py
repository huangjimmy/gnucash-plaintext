"""Shares are not foreign currency.

A cost basis answers an FX question: what did this currency cost in the book's
own, and how much of it is left to sell. A security has no such question — it
is counted in units and priced, not converted — and a single-currency book
holding investments has no foreign currency in it at all.

Judging by "not the book's currency" alone swept every stock and fund split
into the machinery: they grew cost-basis KVPs on import, `fx-balances` listed
them as though `50 CAD/USTECH` were an exchange rate, and correcting a share
count with `--strategy update` was refused for touching a cost basis.
"""

from click.testing import CliRunner

from cli.main import cli

FIXTURE = 'tests/fixtures/stock_purchase_in_cad_book.txt'


def test_a_share_purchase_establishes_no_cost_basis(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book), FIXTURE])
    assert result.exit_code == 0, result.output

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'No foreign-currency cost bases found' in listing, listing
    assert 'USTECH' not in listing, listing

    exported = tmp_path / 'out.txt'
    result = runner.invoke(cli, ['export', str(book), str(exported)])
    assert result.exit_code == 0, result.output
    assert 'cost_basis' not in exported.read_text(), exported.read_text()


def test_a_share_count_can_still_be_corrected(tmp_path):
    """The edit guard is about cost bases, and a security has none."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = runner.invoke(cli, ['import', '--new', str(book), FIXTURE])
    assert result.exit_code == 0, result.output

    exported = tmp_path / 'out.txt'
    result = runner.invoke(cli, ['export', str(book), str(exported)])
    assert result.exit_code == 0, result.output

    edited = tmp_path / 'edited.txt'
    text = exported.read_text()
    assert '10.0000 FUND.USTECH' in text, text
    edited.write_text(text.replace('10.0000 FUND.USTECH', '12.0000 FUND.USTECH'))

    result = runner.invoke(cli, ['import', str(book), str(edited),
                                 '--strategy', 'update'])
    assert result.exit_code == 0, result.output
    assert 'cost basis' not in result.output, result.output


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
    assert 'Available USD: 100.00' in listing, listing
    assert '1.35 CAD/USD' in listing, listing
