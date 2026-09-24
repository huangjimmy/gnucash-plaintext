"""A balance sheet states the realized gain the book did not record, and balances.

The reported page, from a book whose three disposals of 2,720.00 USD were
valued at 1.01, 12.06 and 3,802.81 — 3,815.88 of the 3,815.89 the dollars
cost — so that its exchange account records a realized loss of 44.60 where it
is 3,815.89 − 3,771.28 = 44.61:

    total_assets: 17373.89 CAD
    total_unrealized_gains: 23.97 CAD
    total_liabilities_and_equity: 17373.90 CAD

`retained_earnings` carries the 44.60 the book recorded, and nothing on the
page stated the 0.01 it left out, so equity stood 0.01 above the assets. The
unrealized gain is right: 1,020.00 USD held at 1.4096, less the 1,413.82 they
cost, 23.972. The page now states the other 0.01 as
`realized_gains_not_recorded: -0.01` and adds it into `total_equity`.

The same the other way round: 2.00 USD that cost 2.01 CAD, sold at 1.01 and
1.01, 2.02 of the 2.01, record a realized gain of 0.78 where it is 0.79, and
the page states `realized_gains_not_recorded: 0.01`.

The book is built with the import's own figures, then the last disposal and
its exchange split are set to what the reported book holds, with GnuCash, as
an earlier import left them or as an owner could write them.
"""

import re
from fractions import Fraction

import pytest
from click.testing import CliRunner
from gnucash import GncNumeric

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import find_split_by_guid
from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
LOSS = FIXTURES + 'a_usd_sale_spent_in_three_disposals_that_round_down'
GAIN = FIXTURES + 'two_usd_bought_for_2_01_cad_and_sold_a_dollar_at_a_time'
OWED = FIXTURES + 'two_usd_owed_on_a_card_for_2_01_cad_and_paid_off_a_dollar_at_a_time'

# The last disposal's split and its exchange split, and what the reported book
# holds on them, in cents: each disposal valued at its own share rounded. The
# value of each, and the amount of the exchange split, which is in Canadian
# dollars; the disposal's amount in US dollars stays as it is.
AS_REPORTED = {
    LOSS: [('0e0e0000000000000000000000000006', -380281, None),
           ('0e0e0000000000000000000000000007', 4445, 4445)],
    GAIN: [('0f0f0000000000000000000000000003', -101, None),
           ('0f0f0000000000000000000000000004', -39, -39)],
    OWED: [('0c0c0000000000000000000000000003', 101, None),
           ('0c0c0000000000000000000000000004', 39, 39)],
}
PAGE = {
    LOSS: ('2027-04-25', FIXTURES + 'fx_rates_usd_at_1_4096.yaml'),
    GAIN: ('2026-12-31', FIXTURES + 'fx_rates_usd_at_1_40.yaml'),
    OWED: ('2026-12-31', FIXTURES + 'fx_rates_usd_at_1_40.yaml'),
}
UNREALIZED = {LOSS: Fraction('23.97'), GAIN: Fraction('0.10')}


def _book(tmp_path, base):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), base + '.txt')
    assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    last = _run(CliRunner(), 'import', str(book), base + '_the_last_at_what_is_left.txt')
    assert last.exit_code == 0 and 'Errors:       0' in last.output, last.output
    return book


def _as_reported(book, base):
    """The last disposal and its exchange split as the reported book holds them."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        for guid, value, amount in AS_REPORTED[base]:
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


def _page(book, base):
    as_of, rates = PAGE[base]
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', as_of,
                '--fx-rates', rates, '--no-itemize')
    assert page.exit_code == 0, page.output
    figures = {key: Fraction(figure) for key, figure in re.findall(
        r'^\t([a-z_]+): (-?[0-9.]+) CAD', page.output, re.MULTILINE)}
    return page.output, figures


@pytest.mark.parametrize('base, not_recorded', [
    pytest.param(LOSS, Fraction('-0.01'), id='a-loss-of-0.01-not-recorded'),
    pytest.param(GAIN, Fraction('0.01'), id='a-gain-of-0.01-not-recorded'),
])
def test_it_is_stated_and_the_page_balances(tmp_path, base, not_recorded):
    book = _book(tmp_path, base)
    _as_reported(book, base)

    _, figures = _page(book, base)

    assert figures['unrealized_gains_assets_fx'] == UNREALIZED[base], figures
    assert figures['realized_gains_not_recorded'] == not_recorded, figures
    assert figures['total_assets'] == figures['total_liabilities_and_equity'], figures


def test_itemized_it_lists_the_cost_basis_it_comes_from(tmp_path):
    """The 2,720.00 USD cost basis: nothing held, and 0.01 of its cost left in the book."""
    book = _book(tmp_path, LOSS)
    _as_reported(book, LOSS)
    as_of, rates = PAGE[LOSS]

    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', as_of, '--fx-rates', rates)

    assert page.exit_code == 0, page.output
    assert ('\trealized_gains_not_recorded:\n'
            '\t\tcost_bases:\n'
            '\t\t\tcost_basis:\n'
            '\t\t\t\tsplit_guid: 0e0e0000000000000000000000000002\n'
            '\t\t\t\taccount: "Assets:Wise USD"\n'
            '\t\t\t\tcost_basis_balance: 0\n'
            '\t\t\t\tcost_share_price_in_base: 381589/272000\n'
            '\t\t\t\tcost_value: 0.00 # cost_basis_balance * cost_share_price_in_base\n'
            '\t\t\t\tcost_held: 0.01 # what it cost, less what the disposals drawn on it'
            ' were valued at\n'
            '\t\t\t\trealized_gains_not_recorded: -0.01 # cost_value - cost_held\n'
            "\t\trealized_gains_not_recorded: -0.01 # sum of each cost_basis's"
            ' realized_gains_not_recorded\n') in page.output, page.output


@pytest.mark.parametrize('base, not_recorded', [
    pytest.param(LOSS, Fraction('-0.01'), id='a-loss-of-0.01-not-recorded'),
    pytest.param(GAIN, Fraction('0.01'), id='a-gain-of-0.01-not-recorded'),
])
def test_a_book_rebuilt_from_its_own_export_states_it_too(tmp_path, base, not_recorded):
    """The export states each cost basis's balance, 0.00 once it is spent, and every disposal.

    Which of them came last is not known from a file stating the balance
    already, so each is taken at its own share or at what is left: the book
    is rebuilt as it was, and its page states what it did not record.
    """
    book = _book(tmp_path, base)
    _as_reported(book, base)
    ledger = tmp_path / 'ledger.txt'
    exported = _run(CliRunner(), 'export', str(book), str(ledger))
    assert exported.exit_code == 0, exported.output
    rebuilt = tmp_path / 'rebuilt.gnucash'

    made = _run(CliRunner(), 'import', '--new', str(rebuilt), str(ledger))

    assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    _, figures = _page(rebuilt, base)
    assert figures['realized_gains_not_recorded'] == not_recorded, figures
    assert figures['total_assets'] == figures['total_liabilities_and_equity'], figures


def test_on_a_currency_owed_it_is_stated_with_the_loss_sign(tmp_path):
    """2.00 USD owed on a card for 2.01 CAD, paid off at 1.01 and 1.01: a loss of 0.01 not recorded."""
    book = _book(tmp_path, OWED)
    _as_reported(book, OWED)

    _, figures = _page(book, OWED)

    assert figures['realized_gains_not_recorded'] == Fraction('-0.01'), figures
    assert figures['total_assets'] == figures['total_liabilities_and_equity'], figures


def test_it_is_stated_while_the_currency_is_still_held(tmp_path):
    """Before the last disposal: the two charges' rounding already comes to a cent.

    0.72 and 8.60 USD at 381589/272000 cost 1.0100… and 12.0649…, recorded at
    1.01 and 12.06, so the book holds 3,802.82 of the cost of the 2,710.68 USD
    left, which cost 3,802.8109 at the cost basis's rate: 3,802.81 at the cent.
    """
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), LOSS + '.txt')
    assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output

    _, figures = _page(book, LOSS)

    assert figures['realized_gains_not_recorded'] == Fraction('-0.01'), figures
    assert figures['total_assets'] == figures['total_liabilities_and_equity'], figures


@pytest.mark.parametrize('base', [pytest.param(LOSS, id='the-whole-loss-recorded'),
                                  pytest.param(GAIN, id='the-whole-gain-recorded')])
def test_a_book_recording_the_whole_realized_gain_states_none(tmp_path, base):
    output, figures = _page(_book(tmp_path, base), base)

    assert 'realized_gains_not_recorded' not in output, output
    assert figures['unrealized_gains_assets_fx'] == UNREALIZED[base], figures
    assert figures['total_assets'] == figures['total_liabilities_and_equity'], figures
