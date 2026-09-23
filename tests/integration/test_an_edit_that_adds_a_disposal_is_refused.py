"""An edit that turns a transaction into a foreign-currency disposal is refused.

A new transaction that spends currency the book keeps a cost basis for is
refused unless it gives the guid of the one it came out of, and a transfer,
a share sale and a purchase written wholly in a foreign currency meet checks of
their own. An in-place edit (`--strategy update`) ran none of them: a Canadian
dollar bank fee edited into 100.00 US dollars spent, giving no guid, was
accepted, and the cost basis went on holding every dollar it held before.

So an edit that adds a split spending foreign currency on a side the book keeps
a cost basis for is refused, and sent to the route that runs every check:
delete the transaction and import it afresh. A split the transaction already
had, with the same figure, is not added by the edit, so correcting the memo of
an old spend still goes through.

`tests/fixtures/a_cad_fee_a_later_edit_turns_into_a_us_dollar_spend.txt` and
`tests/fixtures/the_fee_edited_into_a_us_dollar_spend_giving_no_cost_basis.txt`.
"""

from click.testing import CliRunner

from cli.main import cli

BOOK = 'tests/fixtures/a_cad_fee_a_later_edit_turns_into_a_us_dollar_spend.txt'
EDIT = 'tests/fixtures/the_fee_edited_into_a_us_dollar_spend_giving_no_cost_basis.txt'


def _edited(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), BOOK])
    assert 'Errors:       0' in made.output, made.output
    done = CliRunner().invoke(cli, ['import', str(book), EDIT, '--strategy', 'update'])
    return book, done


def test_the_edit_is_refused_and_sent_to_delete_and_import(tmp_path):
    _, done = _edited(tmp_path)

    assert 'Errors:       1' in done.output, done.output
    assert ('this edit spends 100.00 USD the book held, which a cost basis '
            'stands for, and an edit runs none of the checks a disposal meets. '
            'Delete the transaction and import it afresh, giving '
            '`cost_basis_split_guid:` on the split that spent it.') \
        in done.output, done.output


def test_in_a_book_keeping_no_cost_basis_for_them_the_edit_goes_through(tmp_path):
    """As a new transaction spending dollars no cost basis stands for does."""
    book = tmp_path / 'book.gnucash'
    CliRunner().invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/a_cad_fee_a_later_edit_turns_into_a_us_dollar_spend_'
        'in_a_book_keeping_no_cost_basis.txt'])

    done = CliRunner().invoke(cli, ['import', str(book), EDIT, '--strategy', 'update'])

    assert 'Updated:      1' in done.output, done.output
    assert 'Errors:       0' in done.output, done.output


def test_the_book_is_left_as_it_was(tmp_path):
    book, _ = _edited(tmp_path)
    listing = CliRunner().invoke(cli, ['fx-balances', str(book)]).output

    assert 'Total USD cost basis balance: 1,000.00 USD' in listing, listing
    assert 'Total USD held in accounts: 1,000.00 USD' in listing, listing
