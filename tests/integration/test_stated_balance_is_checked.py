"""A stated `cost_basis_balance:` is checked before it becomes book state.

The key is authoritative — it is how a book carries sales this tool never saw,
and how an export's own sales avoid being applied twice — so nothing downstream
questions it: a sale is measured against it, and `_require_stated_cost` values
what it sells at the cost basis cost. That makes it the one figure in the file that
can conjure currency, and it is checked the way a stated cost is: at the door,
on both ways in, against the split's own figures.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli


def _import(runner, book, path, *extra):
    return runner.invoke(cli, ['import', '--new', str(book), str(path), *extra])


@pytest.mark.parametrize('stated, expected', [
    ('150.00', 'brings in'),        # more than the split ever brought in
    ('-10.00', 'negative'),         # a balance no sale could produce
    ('60,00', 'not a number'),      # a comma for a point, one wrong character
    ('100.001', 'cannot hold'),     # finer than the currency's smallest unit
])
def test_a_balance_the_split_cannot_have_is_refused(tmp_path, stated, expected):
    """Each way of stating an impossible balance, refused with its reason."""
    runner = CliRunner()
    source = Path('tests/fixtures/stated_balance_beyond_what_arrived.txt').read_text()
    edited = tmp_path / f'stated_{stated}.txt'
    edited.write_text(source.replace('"150.00"', f'"{stated}"'))

    result = _import(runner, tmp_path / f'book_{stated}.gnucash', edited)
    assert 'cost_basis_balance' in result.output, result.output
    assert expected in result.output, result.output
    assert 'Errors:       1' in result.output, result.output


def test_a_balance_on_a_split_whose_amount_is_the_residual_is_checked_too(tmp_path):
    """`$residual$` states no figure, and the split still brings in one.

    The split takes 1000.00 USD from the CAD split's value, and states 1500.00
    available. Read off the line's text alone, `$residual$` is not a number and
    the check had nothing to compare. Measured on 5.10 before: `Errors: 0`, and
    `fx-balances` listed 1,500.00 USD available on a split that brought in
    1,000.00 USD.
    """
    result = _import(CliRunner(), tmp_path / 'book.gnucash',
                     'tests/fixtures/usd_bought_with_its_amount_left_to_the_residual.txt')

    assert 'cost_basis_balance' in result.output, result.output
    assert 'brings in' in result.output, result.output
    assert 'Errors:       1' in result.output, result.output


def test_a_balance_on_a_split_whose_amount_is_mistyped_is_refused_for_the_amount(tmp_path):
    """`--100.00` matches the split line and is no number: the amount's own check refuses it."""
    source = Path('tests/fixtures/stated_balance_beyond_what_arrived.txt').read_text()
    split = '\tAssets:Bank:USD 100.00 USD\n'
    assert split in source, source
    edited = tmp_path / 'two_minus_signs.txt'
    edited.write_text(source.replace(split, '\tAssets:Bank:USD --100.00 USD\n')
                      .replace('"150.00"', '"60.00"'))

    result = _import(CliRunner(), tmp_path / 'book.gnucash', edited)

    assert 'Errors:       1' in result.output, result.output
    assert '--100.00' in result.output, result.output


def test_a_mistyped_balance_does_not_open_the_basis_in_full(tmp_path):
    """The quiet one: a comma for a point, and 40 sold USD comes back.

    An export carries `cost_basis_balance: "60.00"` on a cost basis whose 40.00
    was sold. Mistyped as `60,00` it does not parse — and unchecked, the split
    was still noted as having stated a balance, so the sale below it was
    skipped as already accounted for, while the cost basis itself, having no
    readable balance, was opened at its full 100.00. One wrong character
    returned 40 USD that had gone, with no error and no way to see it: the
    balance now parses, so nothing downstream finds it odd.
    """
    runner = CliRunner()
    source = Path('tests/fixtures/stated_balance_beyond_what_arrived.txt').read_text()
    edited = tmp_path / 'mistyped.txt'
    edited.write_text(source.replace('"150.00"', '"60,00"'))

    book = tmp_path / 'book.gnucash'
    result = _import(runner, book, edited)
    assert 'cost_basis_balance' in result.output, result.output

    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    assert 'Total USD cost basis balance' not in listing, listing


def test_a_balance_on_a_split_that_holds_no_foreign_currency_is_refused(tmp_path):
    """The wrong line of the two, which is how this key gets written wrong.

    A balance on the CAD side of a purchase passes every test that reads the
    figure by itself, and means nothing: no cost basis lives on a split in the
    book's own currency, so nothing ever reads it. The USD split it was meant
    for is then given no balance at all and opens at its full amount — the
    file asked for 60.00 available and the book holds 100.00, silently.

    `cost_basis_cost:` has refused this since it was added, for the same
    reason and with the same wording.
    """
    runner = CliRunner()
    result = _import(runner, tmp_path / 'book.gnucash',
                     'tests/fixtures/stated_balance_on_a_base_currency_split.txt')

    assert 'cost_basis_balance' in result.output, result.output
    assert 'CAD split' in result.output, result.output
    assert 'Errors:       1' in result.output, result.output


def test_a_balance_on_a_split_holding_fund_units_is_taken(tmp_path):
    """A fund unit is a holding with a cost, so a balance on it is read (Q-046).

    The file states 1.000 of the 1.000 units bought as still unsold, which is
    what the purchase itself would open, and the run takes it. Every other
    question this file asks of a stated balance is asked of this one too: that
    it parses, that it is positive, that it fits the unit the commodity is
    counted to, and that it is no more than the split brought in.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _import(runner, book,
                     'tests/fixtures/stated_balance_on_a_fund_split.txt')

    assert 'Errors:       0' in result.output, result.output
    listing = runner.invoke(cli, ['fx-balances', str(book)]).output
    # Two decimal places because FUNDX itself divides into 100, whatever the
    # account's own smallest unit says: the commodity is what a quantity of it
    # is counted to (CLAUDE.md finding 30).
    assert 'Total FUNDX cost basis balance: 1.00' in listing, listing
    assert '100 CAD/FUNDX' in listing, listing


def test_a_balance_on_an_account_never_opened_is_refused_for_the_account(tmp_path):
    """No account to judge the balance against, so the account is what the run reports."""
    result = _import(CliRunner(), tmp_path / 'book.gnucash',
                     'tests/fixtures/stated_balance_on_an_account_never_opened.txt')

    assert "'Assets:Bank:USD' not found" in result.output, result.output
    assert 'Errors:       1' in result.output, result.output
