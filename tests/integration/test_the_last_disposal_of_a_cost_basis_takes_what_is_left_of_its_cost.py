"""The disposal that takes the last of a cost basis is valued at what is left of its cost, so the book records the whole realized gain or loss.

Each disposal is valued at the cost of what it draws, rounded to the cent.
Several such values add up to the cost basis's cost give or take the
rounding, so the last disposal takes what is left of it: then the values of
all of them are what the currency cost, and the exchange splits beside them
add up to the realized gain or loss.

Valued at its own share rounded, as every disposal was:

- the reported case, `a_usd_sale_spent_in_three_disposals_that_round_down.txt`:
  2,720.00 USD that cost 3,815.89 CAD, spent at 1.01, 12.06 and 3,802.81,
  which is 3,815.88. The realized loss is 3,815.89 − 3,771.28 = 44.61, and the
  book recorded 44.60;
- the same the other way round,
  `two_usd_bought_for_2_01_cad_and_sold_a_dollar_at_a_time.txt`: 2.00 USD that
  cost 2.01 CAD, sold at 1.01 and 1.01, which is 2.02. The realized gain is
  2.80 − 2.01 = 0.79, and the book recorded 0.78.
"""

from fractions import Fraction

import pytest
from click.testing import CliRunner
from gnucash import GncNumeric

from infrastructure.gnucash.utils import find_account
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import find_split_by_guid
from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
LOSS = FIXTURES + 'a_usd_sale_spent_in_three_disposals_that_round_down'
GAIN = FIXTURES + 'two_usd_bought_for_2_01_cad_and_sold_a_dollar_at_a_time'

CASES = [
    # base, what is left, the realized gain or loss as the exchange account holds it
    pytest.param(LOSS, '3802.82', Fraction('44.61'), id='rounding-down-a-loss'),
    pytest.param(GAIN, '1.00', Fraction('-0.79'), id='rounding-up-a-gain'),
]


def _book(tmp_path, base):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), base + '.txt')
    assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    return book


# The last disposal's split and its exchange split, and what an earlier import
# left on them, in cents: the value of each, and the amount of the exchange
# split, which is in Canadian dollars.
AS_AN_EARLIER_IMPORT_LEFT_IT = {
    LOSS: [('0e0e0000000000000000000000000006', -380281, None),
           ('0e0e0000000000000000000000000007', 4445, 4445)],
    GAIN: [('0f0f0000000000000000000000000003', -101, None),
           ('0f0f0000000000000000000000000004', -39, -39)],
}


def _as_an_earlier_import_left_it(book, base):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        for guid, value, amount in AS_AN_EARLIER_IMPORT_LEFT_IT[base]:
            split = find_split_by_guid(repo.book, guid)
            transaction = split.GetParent()
            transaction.BeginEdit()
            split.SetValue(GncNumeric(value, 100))
            if amount is not None:
                split.SetAmount(GncNumeric(amount, 100))
            transaction.CommitEdit()
        repo.save()
    finally:
        repo.close()


def _exchange_account(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        account = find_account(repo.book.get_root_account(),
                               'Income:Foreign exchange gains/losses')
        balance = account.GetBalance()
        return Fraction(balance.num(), balance.denom())
    finally:
        repo.close()


@pytest.mark.parametrize('base, what_is_left, realized', CASES)
def test_valued_at_what_is_left_it_goes_through_and_the_book_records_the_whole_gain_or_loss(
        tmp_path, base, what_is_left, realized):
    book = _book(tmp_path, base)

    done = _run(CliRunner(), 'import', str(book), base + '_the_last_at_what_is_left.txt')

    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    assert _exchange_account(book) == realized


@pytest.mark.parametrize('base, what_is_left, realized', CASES)
def test_a_book_holding_it_at_its_own_share_is_corrected_in_place(
        tmp_path, base, what_is_left, realized):
    """A book an earlier import wrote holds the last at its own share rounded.

    Restating it at what is left, with its exchange split, draws the same
    currency from the same cost basis and leaves its balance, cost and date as
    they were: only the value moves, to the figure the import requires. So
    `--strategy update` takes it, and the book then records the whole gain or
    loss.
    """
    book = _book(tmp_path, base)
    last = base + '_the_last_at_what_is_left.txt'
    made = _run(CliRunner(), 'import', str(book), last)
    assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    _as_an_earlier_import_left_it(book, base)

    done = _run(CliRunner(), 'import', str(book), last, '--strategy', 'update')

    assert done.exit_code == 0 and 'Updated:      1' in done.output, done.output
    assert _exchange_account(book) == realized


def test_a_value_moved_to_any_other_figure_in_place_is_refused(tmp_path):
    """3,802.80 is neither the share, 3,802.81, nor what is left, 3,802.82.

    Read as a new transaction would be (Q-051), the disposal takes the last of
    the cost basis, and is refused as a new import of it would be, giving what
    is left of the cost.
    """
    book = _book(tmp_path, LOSS)
    last = LOSS + '_the_last_at_what_is_left.txt'
    made = _run(CliRunner(), 'import', str(book), last)
    assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    _as_an_earlier_import_left_it(book, LOSS)

    done = _run(CliRunner(), 'import', str(book), LOSS + '_the_last_at_neither.txt',
                '--strategy', 'update')

    assert done.exit_code != 0, done.output
    assert ('what is left of cost basis 0e0e0000000000000000000000000002 is what the '
            'last of it cost plus what the rounding of the disposals before it left, '
            'i.e. 3802.82 CAD') in done.output, done.output
    assert _exchange_account(book) == Fraction('44.60')


def test_a_disposal_edited_in_place_takes_what_is_left_when_it_draws_the_last_of_it(tmp_path):
    """The 0.72 USD charge of 08-13 at 1.02, on a book whose last disposal an earlier import left a cent short.

    Read as a new transaction would be (Q-051), what the charge drew is given
    back and drawn again, and it is then what takes the last 0.72 of the cost
    basis: what is left of the cost is 1.02, because the disposal an earlier
    import valued at its own share, 3,802.81, left a cent of the cost behind.
    Valued at that, the three disposals add up to what the dollars cost, and
    the book records the whole realized loss, 44.61.
    """
    book = _book(tmp_path, LOSS)
    last = LOSS + '_the_last_at_what_is_left.txt'
    made = _run(CliRunner(), 'import', str(book), last)
    assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    _as_an_earlier_import_left_it(book, LOSS)

    done = _run(CliRunner(), 'import', str(book), LOSS + '_the_first_fee_at_1_02.txt',
                '--strategy', 'update')

    assert done.exit_code == 0, done.output
    assert _exchange_account(book) == Fraction('44.61')


@pytest.mark.parametrize('base, what_is_left, realized', CASES)
def test_valued_at_its_own_share_it_is_refused_giving_what_is_left(
        tmp_path, base, what_is_left, realized):
    book = _book(tmp_path, base)

    done = _run(CliRunner(), 'import', str(book), base + '_the_last_at_its_own_share.txt')

    assert done.exit_code != 0, done.output
    assert 'what is left of cost basis' in done.output, done.output
    assert f'i.e. {what_is_left} CAD' in done.output, done.output
