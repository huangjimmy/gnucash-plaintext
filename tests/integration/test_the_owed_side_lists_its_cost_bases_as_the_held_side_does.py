"""The currency a book owes is listed with its cost bases, as the currency it holds is.

`unrealized_gains_assets_fx` and `unrealized_gains_liabilities_fx` are measured
the same way: from each side's own cost bases, priced at the sheet's date. So a
page states the two the same way. Drawn with `--no-itemize`, each is one line.
Drawn with `--itemize`, each is a block listing its cost bases, what they cost,
what they are worth and the accounts they are held in.

Until this was fixed the held side listed its cost bases and the owed side was
always one line, whichever way the page was drawn. A reader could check the 50.00
gain on the 500.00 USD the book holds and not the 100.00 loss on the 1,000.00 USD
it owes, though `unrealized_gains_fx` is the two added together.

The book holds 500.00 USD and owes 1,000.00 USD, both at 1.30 CAD/USD, and is
priced at 1.40 CAD/USD on the sheet's date.
"""

from fractions import Fraction

import pytest
from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import block_of, block_total_of, key_of, totals_of

LEDGER = 'tests/fixtures/a_cad_book_that_borrowed_usd_and_kept_half_of_it_in_usd.txt'
AS_OF = '2026-02-28'


def _sheet(tmp_path, *flags):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), LEDGER)
    assert made.exit_code == 0, made.output
    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF, *flags)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def _shape(block):
    """The block's keys in order, with the figures and the guids left out."""
    return [line.split(':')[0] for line in block.splitlines()]


class TestDrawnWithItsItems:

    def test_each_side_lists_its_own_cost_basis(self, tmp_path):
        page = _sheet(tmp_path)

        held = block_of(page, 'unrealized_gains_assets_fx')
        owed = block_of(page, 'unrealized_gains_liabilities_fx')

        assert 'account: "Assets:USD Bank"' in held, held
        assert 'account: "Liabilities:USD Loan"' in owed, owed
        assert 'Liabilities:USD Loan' not in held, held
        assert 'Assets:USD Bank' not in owed, owed

    def test_the_two_blocks_have_the_same_shape(self, tmp_path):
        page = _sheet(tmp_path)

        held = _shape(block_of(page, 'unrealized_gains_assets_fx'))
        owed = _shape(block_of(page, 'unrealized_gains_liabilities_fx'))

        assert [key.replace('assets', 'liabilities') for key in held] == owed

    def test_the_owed_side_states_what_the_loan_cost_and_is_worth(self, tmp_path):
        page = _sheet(tmp_path)

        owed = block_of(page, 'unrealized_gains_liabilities_fx')
        totals = totals_of(page, 'unrealized_gains_liabilities_fx')

        assert '\t\t\t\ttype: liability' in owed, owed
        assert '\t\t\t\t\t\tcost_basis_balance: -1000.00' in owed, owed
        assert '\t\t\t\t\t\tbalance: -1000.00' in owed, owed
        assert totals == {'cost_value': Fraction(-1300),
                          'value': Fraction(-1400),
                          'unrealized_gains_liabilities_fx': Fraction(-100)}, totals

    def test_the_held_side_states_what_the_dollars_cost_and_are_worth(self, tmp_path):
        page = _sheet(tmp_path)

        assert totals_of(page, 'unrealized_gains_assets_fx') == {
            'cost_value': Fraction(650),
            'value': Fraction(700),
            'unrealized_gains_assets_fx': Fraction(50)}

    def test_the_two_blocks_add_to_the_total(self, tmp_path):
        page = _sheet(tmp_path)

        assert key_of(page, 'unrealized_gains_fx') == '-50.00 CAD'


class TestDrawnWithoutItsItems:

    def test_each_side_is_one_line(self, tmp_path):
        page = _sheet(tmp_path, '--no-itemize')

        assert key_of(page, 'unrealized_gains_assets_fx') == '50.00 CAD'
        assert key_of(page, 'unrealized_gains_liabilities_fx') == '-100.00 CAD'
        assert 'cost_basis:' not in page, page


# Every gain key that lists what it is made of. `realized_gains_not_recorded`
# is written only where there is one, so the second book is one that has one:
# 2,720.00 USD spent in three disposals whose values, each rounded to the cent,
# leave 0.01 of the cost out of the realized loss the book records.
GAIN_KEYS = ('unrealized_gains_assets_fx', 'unrealized_gains_liabilities_fx',
             'realized_gains_fx', 'unrealized_gains_other',
             'realized_gains_not_recorded', 'gnucash_balancing_amount')

BOOKS = (
    pytest.param(LEDGER, AS_OF, (), id='holds-and-owes-usd'),
    pytest.param('tests/fixtures/a_usd_sale_spent_in_three_disposals_that_round_down.txt',
                 '2027-04-25',
                 ('--fx-rates', 'tests/fixtures/fx_rates_usd_at_1_4096.yaml'),
                 id='a-cent-of-cost-not-recorded'),
)


@pytest.mark.parametrize('ledger,as_of,rates', BOOKS)
def test_every_gain_key_is_a_block_itemized_and_one_line_without(tmp_path, ledger, as_of, rates):
    """Each gain key is stated alike: a block with `--itemize`, one line without, one figure both ways."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), ledger)
    assert made.exit_code == 0, made.output
    itemized = _run(runner, 'balance-sheet', str(book), '--as-of', as_of, *rates)
    assert itemized.exit_code == 0, itemized.output
    plain = _run(runner, 'balance-sheet', str(book), '--as-of', as_of, *rates, '--no-itemize')
    assert plain.exit_code == 0, plain.output

    stated = [key for key in GAIN_KEYS if f'\n\t{key}: ' in plain.output]
    listed = [key for key in GAIN_KEYS if f'\n\t{key}:\n' in itemized.output
              or f'\n\t{key}: #' in itemized.output]
    assert stated == listed, (stated, listed)
    for key in stated:
        figure = Fraction(key_of(plain.output, key).split(' ')[0])
        assert block_total_of(itemized.output, key) == figure, key
        assert f'\n\t{key}:\n' not in plain.output, (key, plain.output)
    if 'a_usd_sale' in ledger:
        assert stated == list(GAIN_KEYS), stated
