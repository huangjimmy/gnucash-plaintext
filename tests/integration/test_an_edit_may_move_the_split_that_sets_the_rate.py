"""An edit in place may move the split that sets a cost basis's rate to another account, and a refused edit says what it changed and a route that works.

`tests/fixtures/a_usd_arrival_booked_to_the_directors_account.txt` holds a
2,720.00 USD arrival stated in US dollars, its other split on the director's
account for 3,791.14 CAD, and a 0.72 USD fee drawn on the cost basis it opened.

Stated in US dollars, the cost basis is priced at the Canadian dollar split's
amount over the dollars' amount. The split's account plays no part in that, so
moving it to income, every figure the same, is an ordinary correction and goes
through. Restating its amount re-prices the cost basis and is refused, and the
refusal says which split and which figure, and — because a fee draws on the
cost basis — lists the fee and gives the command that deletes the two together.
Sent to delete the arrival alone, the reader met a second refusal: it cannot be
deleted while something draws on its cost basis.
"""

from datetime import date
from fractions import Fraction

from click.testing import CliRunner

from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import (
    brought_in_by,
    cost_basis_items_by_currency_and_side,
    find_split_by_guid,
    iter_splits,
)
from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
THE_BOOK = FIXTURES + 'a_usd_arrival_booked_to_the_directors_account.txt'
MOVED_TO_INCOME = FIXTURES + 'a_usd_arrival_booked_to_the_directors_account_moved_to_income.txt'
AMOUNT_CHANGED = FIXTURES + 'a_usd_arrival_booked_to_the_directors_account_amount_changed.txt'
REBOOKED_INTO_A_CAD_BANK = (
    FIXTURES + 'a_usd_arrival_booked_to_the_directors_account_rebooked_into_a_cad_bank.txt')
REBOOKED_KEEPING_THE_SPLIT = (
    FIXTURES
    + 'a_usd_arrival_booked_to_the_directors_account_rebooked_into_a_cad_bank_keeping_the_split.txt')
FEE_GIVEN_A_SECOND_SPLIT = (
    FIXTURES + 'a_usd_arrival_booked_to_the_directors_account_fee_given_a_second_split.txt')
FEE_DRAWN_ON_NO_COST_BASIS = (
    FIXTURES + 'a_usd_arrival_booked_to_the_directors_account_fee_drawn_on_no_cost_basis.txt')
ARRIVAL_A_DAY_LATER = FIXTURES + 'a_usd_arrival_booked_to_the_directors_account_dated_a_day_later.txt'
FEE_A_DAY_LATER = FIXTURES + 'a_usd_arrival_booked_to_the_directors_account_fee_dated_a_day_later.txt'
DIVIDED = (FIXTURES
           + 'a_usd_arrival_booked_to_the_directors_account_divided_between_income_and_the_director.txt')
MOVED_TO_ANOTHER_USD_BANK = (
    FIXTURES + 'a_usd_arrival_booked_to_the_directors_account_moved_to_another_usd_bank.txt')
CONVERTED_TO_EUROS = (
    FIXTURES + 'a_usd_arrival_booked_to_the_directors_account_then_converted_to_euros.txt')

GIVEN_A_ZERO_AMOUNT_CAD_SPLIT = (
    FIXTURES + 'a_usd_arrival_booked_to_the_directors_account_given_a_zero_amount_cad_split.txt')
GIVEN_A_ZERO_AMOUNT_USD_SPLIT = (
    FIXTURES + 'a_usd_arrival_booked_to_the_directors_account_given_a_zero_amount_usd_split.txt')
MOVED_KEEPING_THE_ZERO_AMOUNT_CAD_SPLIT = (
    FIXTURES + 'a_usd_arrival_booked_to_the_directors_account'
    '_moved_to_income_keeping_the_zero_amount_cad_split.txt')
YEN_ARRIVAL = FIXTURES + 'a_jpy_arrival_booked_to_the_directors_account.txt'
YEN_ARRIVAL_GIVEN_A_ZERO_AMOUNT_JPY_SPLIT = (
    FIXTURES + 'a_jpy_arrival_booked_to_the_directors_account_given_a_zero_amount_jpy_split.txt')
RESTATED_AND_A_DAY_LATER = (
    FIXTURES
    + 'a_usd_arrival_booked_to_the_directors_account_amount_changed_and_dated_a_day_later.txt')
YEN_ARRIVAL_RESTATED_IN_CAD = (
    FIXTURES + 'a_jpy_arrival_booked_to_the_directors_account_restated_in_cad.txt')

THE_ARRIVAL = 'e1d60fe6bc104e018c50c67dd61665ec'
THE_FEE = '0d0d0000000000000000000000000001'
THE_CONVERSION = '0d0d0000000000000000000000000002'
THE_EURO_FEE = '0d0d0000000000000000000000000004'


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), THE_BOOK)
    assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    return book


def _read(book):
    """The cost bases, and the account every Canadian dollar split is on."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        bases = sorted((row['account'], row['balance'], row['cost'])
                       for row in cost_basis_items_by_currency_and_side(
                           repo.book, date(2026, 12, 31)))
        where = sorted(get_account_full_name(split.GetAccount())
                       for split in iter_splits(repo.book)
                       if split.GetParent().GetDescription() == 'Received money')
    finally:
        repo.close()
    return bases, where


def _what_the_arrival_brought_in(book):
    """What the arrival's US dollar split records it brought in, after the edit is saved."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return brought_in_by(find_split_by_guid(repo.book, '3cdacfb099e9c7fbe795b8aa317313bd'))
    finally:
        repo.close()


class TestMovingTheSplitThatSetsTheRate:
    def test_the_edit_goes_through(self, tmp_path):
        book = _book(tmp_path)
        done = _run(CliRunner(), 'import', str(book), MOVED_TO_INCOME, '--strategy', 'update')

        assert done.exit_code == 0, done.output
        assert 'Updated:      1' in done.output, done.output
        assert _read(book)[1] == ['Assets:Wise USD', 'Income:Sales']

    def test_the_cost_basis_is_priced_as_it_was(self, tmp_path):
        book = _book(tmp_path)
        before = _read(book)[0]
        _run(CliRunner(), 'import', str(book), MOVED_TO_INCOME, '--strategy', 'update')

        assert _read(book)[0] == before, (before, _read(book)[0])


class TestKeepingAZeroAmountCadSplit:
    def test_moving_the_other_split_goes_through_and_the_cost_basis_is_priced_as_it_was(
            self, tmp_path):
        """A 0.00 CAD split beside the one that sets the rate, kept as it is."""
        book = _book(tmp_path)
        given = _run(CliRunner(), 'import', str(book), GIVEN_A_ZERO_AMOUNT_CAD_SPLIT,
                     '--strategy', 'update')
        assert given.exit_code == 0 and 'Updated:      1' in given.output, given.output
        before = _read(book)[0]

        done = _run(CliRunner(), 'import', str(book), MOVED_KEEPING_THE_ZERO_AMOUNT_CAD_SPLIT,
                    '--strategy', 'update')

        assert done.exit_code == 0 and 'Updated:      1' in done.output, done.output
        assert _read(book) == (before, ['Assets:Due from shareholder', 'Assets:Wise USD',
                                        'Income:Sales'])


class TestAddingAZeroAmountUsdSplitBesideTheCostBasis:
    def test_the_fee_drawn_on_it_the_same_day_is_not_counted_before_it(self, tmp_path):
        """The US dollar bank is read again, and the 0.72 USD fee came after the arrival."""
        book = _book(tmp_path)
        before = _read(book)[0]

        done = _run(CliRunner(), 'import', str(book), GIVEN_A_ZERO_AMOUNT_USD_SPLIT,
                    '--strategy', 'update')

        assert done.exit_code == 0 and 'Updated:      1' in done.output, done.output
        assert _read(book)[0] == before, (before, _read(book)[0])
        assert _what_the_arrival_brought_in(book) == Fraction('2720.00')


class TestDividingTheSplitThatSetsTheRate:
    """2,000.00 to income and 1,791.14 left on the director's account: the totals stand."""

    def test_the_edit_goes_through_and_the_cost_basis_is_priced_as_it_was(self, tmp_path):
        book = _book(tmp_path)
        before = _read(book)[0]
        done = _run(CliRunner(), 'import', str(book), DIVIDED, '--strategy', 'update')

        assert done.exit_code == 0, done.output
        assert _read(book) == (before, ['Assets:Due from shareholder', 'Assets:Wise USD',
                                        'Income:Sales'])


class TestMovingTheCostBasisItself:
    def test_moving_the_usd_split_to_another_bank_is_refused(self, tmp_path):
        """The cost basis would go with it and the fee drawn on it would stay behind."""
        book = _book(tmp_path)
        done = _run(CliRunner(), 'import', str(book), MOVED_TO_ANOTHER_USD_BANK,
                    '--strategy', 'update')

        assert done.exit_code != 0, done.output
        assert ("cost basis 3cdacfb099e9c7fbe795b8aa317313bd on 'Assets:Wise USD' "
                "would be on 'Assets:Wise USD 2'") in done.output, done.output


class TestRemovingOrAddingWhatACostBasisRestsOn:
    def test_rebooking_the_arrival_in_canadian_dollars_is_refused(self, tmp_path):
        """The US dollar split goes, and its cost basis with it, under the fee drawn on it."""
        book = _book(tmp_path)
        done = _run(CliRunner(), 'import', str(book), REBOOKED_INTO_A_CAD_BANK,
                    '--strategy', 'update')

        assert done.exit_code != 0, done.output
        assert ("cost basis 3cdacfb099e9c7fbe795b8aa317313bd on 'Assets:Wise USD' "
                'would be gone — every split drawing on it would give a cost basis '
                'the book no longer holds'
                ) in done.output, done.output

    def test_rebooking_it_keeping_the_split_still_gives_the_fee_to_delete_first(self, tmp_path):
        """The split no longer opens a cost basis as the edit leaves it; the fee still draws on it."""
        book = _book(tmp_path)
        done = _run(CliRunner(), 'import', str(book), REBOOKED_KEEPING_THE_SPLIT,
                    '--strategy', 'update')

        assert done.exit_code != 0, done.output
        assert ("cost basis 3cdacfb099e9c7fbe795b8aa317313bd on 'Assets:Wise USD' "
                'would be gone') in done.output, done.output
        assert f'delete-transactions --by-guid {THE_FEE} {THE_ARRIVAL}' in done.output, done.output

    def test_a_second_split_drawing_on_the_cost_basis_is_drawn_on_it(self, tmp_path):
        """Read as a new transaction would be (Q-051), the fee draws both its splits: 1.00 USD in all."""
        book = _book(tmp_path)
        done = _run(CliRunner(), 'import', str(book), FEE_GIVEN_A_SECOND_SPLIT,
                    '--strategy', 'update')

        assert done.exit_code == 0, done.output
        [(account, balance, _cost)] = _read(book)[0]
        assert (account, balance) == ('Assets:Wise USD', Fraction('2719.00'))


class TestMovingTheDate:
    """A cost basis's date is part of it, and moving it is refused while the fee draws on it.

    The fee's own date is not: the fee's edit is read as a new transaction
    would be (Q-051), and a new fee dated a day later draws what it drew.
    """

    def test_the_arrival_moved_a_day_later_is_refused(self, tmp_path):
        book = _book(tmp_path)
        done = _run(CliRunner(), 'import', str(book), ARRIVAL_A_DAY_LATER, '--strategy', 'update')

        assert done.exit_code != 0, done.output
        assert 'it is dated 2026-08-13 and would be dated 2026-08-14' in done.output, done.output
        assert f'delete-transactions --by-guid {THE_FEE} {THE_ARRIVAL}' in done.output, done.output

    def test_under_atomic_the_fee_moved_a_day_later_is_read_as_new(self, tmp_path):
        book = _book(tmp_path)
        done = _run(CliRunner(), 'import', str(book), FEE_A_DAY_LATER, '--strategy', 'update',
                    '--atomic')

        assert done.exit_code == 0, done.output
        [(account, balance, _cost)] = _read(book)[0]
        assert (account, balance) == ('Assets:Wise USD', Fraction('2719.28'))

    def test_under_atomic_the_refusal_gives_the_date_and_not_a_figure_it_defers(self, tmp_path):
        book = _book(tmp_path)
        done = _run(CliRunner(), 'import', str(book), RESTATED_AND_A_DAY_LATER,
                    '--strategy', 'update', '--atomic')

        assert done.exit_code != 0, done.output
        assert 'it is dated 2026-08-13 and would be dated 2026-08-14' in done.output, done.output
        assert 'would cost' not in done.output, done.output

    def test_the_fee_moved_a_day_later_is_read_as_new(self, tmp_path):
        book = _book(tmp_path)
        done = _run(CliRunner(), 'import', str(book), FEE_A_DAY_LATER, '--strategy', 'update')

        assert done.exit_code == 0, done.output
        [(account, balance, _cost)] = _read(book)[0]
        assert (account, balance) == ('Assets:Wise USD', Fraction('2719.28'))


class TestRestatingWhatSetsTheRate:
    def _refused(self, tmp_path):
        book = _book(tmp_path)
        done = _run(CliRunner(), 'import', str(book), AMOUNT_CHANGED, '--strategy', 'update')
        assert done.exit_code != 0, done.output
        return book, done.output

    def test_the_refusal_says_which_split_and_which_figure(self, tmp_path):
        _, output = self._refused(tmp_path)

        assert ('the book holds -3791.14 CAD on '
                "'Assets:Due from shareholder' valued at -2720.00") in output, output
        assert ('the file states -3800.00 CAD on '
                "'Assets:Due from shareholder' valued at -2720.00") in output, output

    def test_a_cleared_pick_is_refused_as_a_spend_giving_no_cost_basis(self, tmp_path):
        """Every figure the same and the pick cleared: read as new, the fee spends dollars held giving no cost basis."""
        book = _book(tmp_path)
        before = _read(book)[0]
        done = _run(CliRunner(), 'import', str(book), FEE_DRAWN_ON_NO_COST_BASIS,
                    '--strategy', 'update')

        assert done.exit_code != 0, done.output
        assert ('this transaction spends 0.72 USD the book held, which draws down a '
                'cost basis, but no split says which one') in done.output, done.output
        assert _read(book)[0] == before

    def test_it_lists_what_draws_on_the_cost_basis(self, tmp_path):
        _, output = self._refused(tmp_path)

        assert "2026-08-13 'Wise charges' (0.72 USD)" in output, output

    def test_the_command_it_gives_deletes_them_together(self, tmp_path):
        """The one command the refusal gives deletes the fee and the arrival, fee first."""
        book, output = self._refused(tmp_path)
        command = f'delete-transactions --by-guid {THE_FEE} {THE_ARRIVAL}'
        assert command in output, output

        deleted = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid',
                       THE_FEE, THE_ARRIVAL, '-o', str(tmp_path / 'undo.txt'))

        assert deleted.exit_code == 0, deleted.output
        assert _read(book) == ([], []), _read(book)


class TestAnEditChangingTheCurrency:
    def test_the_yen_arrival_restated_in_canadian_dollars_is_priced_at_its_new_figures(self, tmp_path):
        """Nothing draws on the yen's cost basis, so the edit is read as a new transaction would be (Q-051)."""
        book = tmp_path / 'book.gnucash'
        made = _run(CliRunner(), 'import', '--new', str(book), YEN_ARRIVAL)
        assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output

        done = _run(CliRunner(), 'import', str(book), YEN_ARRIVAL_RESTATED_IN_CAD,
                    '--strategy', 'update')

        assert done.exit_code == 0, done.output
        [(_account, _balance, cost)] = _read(book)[0]
        assert cost == Fraction(910, 100000)


class TestAddingAZeroAmountJpySplitOnTheYenBank:
    def test_it_goes_through_and_the_cost_basis_is_what_it_was(self, tmp_path):
        """Every split on the yen bank is read again, from what it held before the edit."""
        book = tmp_path / 'book.gnucash'
        made = _run(CliRunner(), 'import', '--new', str(book), YEN_ARRIVAL)
        assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
        before = _yen_bases(book)

        done = _run(CliRunner(), 'import', str(book), YEN_ARRIVAL_GIVEN_A_ZERO_AMOUNT_JPY_SPLIT,
                    '--strategy', 'update')

        assert done.exit_code == 0 and 'Updated:      1' in done.output, done.output
        assert _yen_bases(book) == before == [('Assets:Wise JPY', '100000', '9/1000')], before


def _yen_bases(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return sorted((row['account'], str(row['balance']), str(row['cost']))
                      for row in cost_basis_items_by_currency_and_side(
                          repo.book, date(2026, 12, 31)))
    finally:
        repo.close()


class TestAChainOfCostBases:
    """The fee draws on the conversion's euros, and the conversion on the arrival's dollars."""

    def _refused(self, tmp_path):
        book = _book(tmp_path)
        converted = _run(CliRunner(), 'import', str(book), CONVERTED_TO_EUROS)
        assert converted.exit_code == 0 and 'Errors:       0' in converted.output, converted.output
        done = _run(CliRunner(), 'import', str(book), AMOUNT_CHANGED, '--strategy', 'update')
        assert done.exit_code != 0, done.output
        return book, done.output

    def test_the_command_deletes_the_whole_chain_the_last_step_first(self, tmp_path):
        """The euro fee draws on both cost bases, and is listed once, before the conversion."""
        book, output = self._refused(tmp_path)
        command = (f'delete-transactions --by-guid {THE_FEE} {THE_EURO_FEE} '
                   f'{THE_CONVERSION} {THE_ARRIVAL}')
        assert command in output, output
        assert "2026-08-15 'Wise euro charges' (1.00 EUR, 0.10 USD)" in output, output

        deleted = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid',
                       THE_FEE, THE_EURO_FEE, THE_CONVERSION, THE_ARRIVAL,
                       '-o', str(tmp_path / 'undo.txt'))

        assert deleted.exit_code == 0, deleted.output
        assert _read(book) == ([], []), _read(book)


class TestAFeeOfTwoSplits:
    def test_it_is_listed_with_both_amounts(self, tmp_path):
        """0.72 and 0.28 USD drawn on the cost basis: listed as 1.00 USD."""
        book = _book(tmp_path)
        _run(CliRunner(), 'delete-transactions', str(book), '--by-guid', THE_FEE,
             '-o', str(tmp_path / 'undo.txt'))
        fee = _run(CliRunner(), 'import', str(book), FEE_GIVEN_A_SECOND_SPLIT)
        assert fee.exit_code == 0 and 'Errors:       0' in fee.output, fee.output

        done = _run(CliRunner(), 'import', str(book), AMOUNT_CHANGED, '--strategy', 'update')

        assert done.exit_code != 0, done.output
        assert "2026-08-13 'Wise charges' (1.00 USD)" in done.output, done.output
