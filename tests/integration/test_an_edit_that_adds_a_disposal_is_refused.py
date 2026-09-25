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

from pathlib import Path

import pytest
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
    assert ('this edit makes the transaction a sale of 100.00 USD the book held for '
            '140.00 CAD: Assets:USD Bank, a Bank account in USD, is credited 100.00 USD; '
            'Assets:CAD Bank, a Bank account in CAD, is debited 140.00 CAD. A sale requires '
            'a consumption of one or more cost bases, but no split says which. An edit '
            'runs none of the checks a disposal meets. Delete the transaction and '
            'import it afresh, giving `cost_basis_split_guid:` on the split that '
            'disposes of it.') in done.output, done.output


def test_the_same_edit_taking_the_canadian_dollars_as_the_residual_is_refused_as_a_sale(tmp_path):
    """`Assets:CAD Bank $residual$ CAD` is debited the 140.00 that balances the other split, so it is read as what the sale fetched."""
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), BOOK])
    assert 'Errors:       0' in made.output, made.output
    edit = tmp_path / 'edit.txt'
    edit.write_text(Path(EDIT).read_text().replace(
        'Assets:CAD Bank 140.00 CAD', 'Assets:CAD Bank $residual$ CAD'))

    done = CliRunner().invoke(cli, ['import', str(book), str(edit), '--strategy', 'update'])

    assert ('this edit makes the transaction a sale of 100.00 USD the book held for '
            '140.00 CAD: Assets:USD Bank, a Bank account in USD, is credited 100.00 USD; '
            'Assets:CAD Bank, a Bank account in CAD, is debited 140.00 CAD.') in done.output, \
        done.output


@pytest.mark.parametrize('line, typo', [
    ('Assets:CAD Bank 140.00 CAD', 'Assets:CAD Bnak'),
    ('Assets:USD Bank -100.00 USD', 'Assets:USD Bnak'),
])
def test_the_same_edit_with_a_split_on_an_account_the_book_does_not_have_is_refused(
        tmp_path, line, typo):
    """A typo in either split's account: refused for the account, and the book left as it was."""
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), BOOK])
    assert 'Errors:       0' in made.output, made.output
    edit = tmp_path / 'edit.txt'
    edit.write_text(Path(EDIT).read_text().replace(line, typo + line[len(typo):]))
    on_disk = book.read_bytes()

    done = CliRunner().invoke(cli, ['import', str(book), str(edit), '--strategy', 'update'])

    assert done.exit_code == 1, done.output
    assert f'error: Sell 100.00 USD at 1.40: Account not found: {typo}' in done.output, \
        done.output
    assert book.read_bytes() == on_disk


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
