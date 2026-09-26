"""The page says what GnuCash's balancing amount is on the book it is drawn on.

`gnucash_balancing_amount` is one subtraction on every book — what the holdings
are worth at the price nearest this date, less the sum of their splits' values —
but what that figure *means* depends on what the book did, and the answers are
far apart. On one book it is the gain already taken. On another it is the gain
not yet taken. On a third it is part of each and neither on its own, and moves
with the price the sheet is drawn at. On a fourth it is nothing at all while the
book has really lost money.

A reader cannot tell those apart from the number, which is why the page prints
what the number is made of rather than what it means. Beneath the key each
commodity lists the splits GnuCash summed and the accounts holding it, so the
subtraction can be followed; the page states no verdict on it. These hold what
it prints, scenario by scenario.

**Which case a book is in is read from two figures together, never from the
balancing amount alone.** Where it is 0.00 GnuCash has counted nothing twice,
and where it equals `unrealized_gains_fx` it agrees with the cost bases exactly
— both of those are answered without asking what was disposed of. Past them, a
book that has realized something is one whose gain GnuCash is counting a second
time. Two books here have a balancing amount equal to their realized loss — the
one that spent every dollar and the one that kept a thousand back — and in each
the two figures disagree, which is what says so.
"""

from fractions import Fraction

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import block_of, block_total_of, key_of

COLLECTED = 'tests/fixtures/a_usd_invoice_collected_into_a_usd_bank.txt'
SPENT = 'tests/fixtures/the_usd_bank_spent_out_against_its_basis.txt'
PARTLY_SPENT = 'tests/fixtures/the_usd_bank_partly_spent_leaving_a_thousand.txt'
BOUGHT_WITH_CAD = 'tests/fixtures/a_cad_book_earning_usd_three_times.txt'
SECURITY = 'tests/fixtures/a_cad_book_holding_us_listed_shares.txt'
TWO_BROKERS = 'tests/fixtures/a_cad_book_holding_one_security_in_two_accounts.txt'

RATES = 'tests/fixtures/usd_at_the_invoice_rate_then_lower_at_the_year_end.yaml'
HIGHER_RATES = 'tests/fixtures/usd_at_the_invoice_rate_then_higher_at_the_year_end.yaml'
BELOW_RATES = 'tests/fixtures/usd_at_the_invoice_rate_then_far_below_it_at_the_year_end.yaml'

YEAR_END = '2026-12-31'

BOUGHT_FOR_CAD = 'tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt'


def _basis_on(listing, fragment):
    import re
    for line in listing.splitlines():
        if fragment in line:
            found = re.search(r'\b([0-9a-f]{32})\b', line)
            if found:
                return found.group(1)
    raise AssertionError(f'no cost basis on {fragment!r} in:\n{listing}')


def _collected(runner, tmp_path):
    """2,720.00 USD collected from a US dollar invoice into a US dollar bank."""
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), COLLECTED,
                '--fx-rates', RATES, '--include-business-objects')
    assert made.exit_code == 0, made.output
    return book


def _spend(runner, tmp_path, book, fixture):
    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    with open(fixture, encoding='utf-8') as source:
        filled = source.read().replace(
            '{usd_basis}', _basis_on(listing.output, 'Accounts Receivable USD'))
    ledger = tmp_path / 'spend.txt'
    ledger.write_text(filled, encoding='utf-8')
    spent = _run(runner, 'import', str(book), str(ledger), '--fx-rates', RATES)
    assert spent.exit_code == 0, spent.output
    return book


def _sheet(runner, book, rates=RATES):
    """Always with a rates file: without one the holding is priced at nothing.

    Drawn with no `--fx-rates` these books state their recorded cost back —
    3,791.14 — because nothing prices the currency on the sheet's date. The
    existing gains tests pass rates on every draw for the same reason.
    """
    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', YEAR_END,
                 '--fx-rates', rates)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def _groups_of(page):
    """The commodity groups under `gnucash_balancing_amount`, as
    `{mnemonic: {field: text}}`.

    The key groups by the currency each split's value is in, and every group
    states the subtraction it came from: the splits' values added up, what the
    accounts holding that currency hold, the difference between the two, and
    that difference converted. Adding the last of those across the groups is
    the key.

    Only the group's own lines, which sit four tabs in — the splits and the
    account balances it is built from are deeper, and each group carries as
    many of those as the book has.
    """
    groups = {}
    current = None
    for line in block_of(page, 'gnucash_balancing_amount').splitlines():
        if line.startswith('\t\t\t\t\t') or not line.startswith('\t\t\t\t'):
            continue
        field, _, rest = line.strip().partition(': ')
        if not rest:
            continue
        if field == 'commodity.mnemonic':
            current = rest.strip('"')
            groups[current] = {}
        elif current is not None:
            groups[current][field] = rest.split(' #')[0].strip()
    assert groups, f'no commodity group under gnucash_balancing_amount in:\n{page}'
    return groups


def _from_a_plain_book(runner, tmp_path, fixture, name):
    book = tmp_path / f'{name}.gnucash'
    made = _run(runner, 'import', '--new', str(book), fixture)
    assert made.exit_code == 0, made.output
    return book


def _collected_and_bought(runner, tmp_path):
    """US dollars that arrived on a US dollar invoice, and more bought with CAD.

    The two halves are the same currency and neither is disposed of, so nothing
    is realized. They differ in what GnuCash can see: the collected half carries
    no Canadian figure on either of its splits, so GnuCash's summed split values
    fall short of what the cost bases say those dollars cost, while the bought
    half agrees with its cost basis exactly.
    """
    book = _collected(runner, tmp_path)
    added = _run(runner, 'import', str(book), BOUGHT_FOR_CAD, '--fx-rates', RATES)
    assert added.exit_code == 0, added.output
    return book


def test_every_dollar_spent_at_the_rate_they_left_at(tmp_path):
    """19.86 here equals the realized loss to the cent, and the page says why.

    The book holds no US dollars at all. Its holding is 0.00 USD worth 0.00
    CAD, so the figure is the 3,791.14 CAD the disposal was stated at, less
    2,720 dollars that have already left, valued at whatever year-end rate this
    sheet carries — measured, the same book states −152.86 at 1.45 and 527.14 at
    1.2, moving by exactly 2,720 times the change in that rate. The agreement at
    this one rate is arithmetic falling out, not a meaning.

    So the page states the subtraction rather than a verdict on it: the
    commodity groups beneath the key list the splits GnuCash summed and the
    accounts holding each commodity, and a reader who wants to know whether
    this figure is a gain already taken reads it against `realized_gains_fx`
    printed above. Nothing here tells them what to conclude, because the same
    number means different things on different books and only the two figures
    together say which.
    """
    runner = CliRunner()
    page = _sheet(runner, _spend(runner, tmp_path, _collected(runner, tmp_path), SPENT))

    assert block_total_of(page, 'gnucash_balancing_amount') == Fraction('19.86')
    assert block_total_of(page, 'realized_gains_fx') == Fraction('-19.86')

    # The two groups it is made of, each stating its own subtraction. The
    # dollars are gone, so the US dollar group's accounts hold nothing against
    # 2,720.00 of split values; the Canadian group carries what the disposal
    # was booked at.
    groups = _groups_of(page)
    assert groups['USD'] == {'sum_value': '2720.00', 'balance_value': '0.00',
                             'gains_before_conversion': '-2720.00',
                             'balance_sheet_value': '-3771.28'}, groups
    assert groups['CAD'] == {'sum_value': '-19.86', 'balance_value': '3771.28',
                             'gains_before_conversion': '3791.14',
                             'balance_sheet_value': '3791.14'}, groups


def test_a_thousand_kept_back_is_not_the_whole_gain_already_taken(tmp_path):
    """The figure equals the realized part, and the book still holds 1,000.00 USD.

    The arithmetic coincides with the spent-out book's, so a page choosing its
    comment by comparing totals says the same thing here — and would be wrong,
    because 7.30 of this book's loss has not been taken.
    """
    runner = CliRunner()
    page = _sheet(runner,
                  _spend(runner, tmp_path, _collected(runner, tmp_path), PARTLY_SPENT))

    assert block_total_of(page, 'gnucash_balancing_amount') == Fraction('12.56')
    assert key_of(page, 'unrealized_gains_fx') == '-7.30 CAD'

    # 1,000.00 USD is still in the bank, which is what separates this book from
    # the spent-out one: its US dollar group's accounts hold that thousand.
    groups = _groups_of(page)
    assert groups['USD']['balance_value'] == '1000.00', groups
    assert groups['USD']['gains_before_conversion'] == '-1720.00', groups


def test_spent_out_but_priced_above_the_rate_they_left_at(tmp_path):
    """Neither gain: it moves with the rate where the realized loss does not."""
    runner = CliRunner()
    page = _sheet(runner,
                  _spend(runner, tmp_path, _collected(runner, tmp_path), SPENT),
                  HIGHER_RATES)

    assert block_total_of(page, 'gnucash_balancing_amount') == Fraction('-152.86')
    assert block_total_of(page, 'realized_gains_fx') == Fraction('-19.86')
    # Only the US dollar group moves with the price: its difference is
    # converted at the rate the sheet is drawn at, where the Canadian group's
    # is already in the book's own currency.
    assert _groups_of(page)['USD']['balance_sheet_value'] == '-3944.00'


def test_spent_out_but_priced_below_the_rate_they_left_at(tmp_path):
    """The same book at 1.2, where the figure changes sign."""
    runner = CliRunner()
    page = _sheet(runner,
                  _spend(runner, tmp_path, _collected(runner, tmp_path), SPENT),
                  BELOW_RATES)

    assert block_total_of(page, 'gnucash_balancing_amount') == Fraction('527.14')
    assert _groups_of(page)['USD']['balance_sheet_value'] == '-3264.00'


def test_nothing_disposed_and_nothing_measured(tmp_path):
    """The case a reader most needs told: 0.00 stated while the book has lost 19.86.

    Those dollars arrived carrying no Canadian figure, so GnuCash's subtraction
    has nothing to work on and states nothing at any price. The page says so
    rather than printing a bare zero, and says it even though there is no
    commodity line above it to itemize.
    """
    runner = CliRunner()
    page = _sheet(runner, _collected(runner, tmp_path))

    assert block_total_of(page, 'gnucash_balancing_amount') == 0
    assert key_of(page, 'unrealized_gains_fx') == '-19.86 CAD'

    # The US dollar group states why the figure is nothing rather than leaving
    # a bare zero: the splits add to 2,720.00 and the accounts hold 2,720.00,
    # so GnuCash's subtraction had figures to work on and came to nothing.
    groups = _groups_of(page)
    assert groups['USD'] == {'sum_value': '2720.00', 'balance_value': '2720.00',
                             'gains_before_conversion': '0.00',
                             'balance_sheet_value': '0.00'}, groups

    # And every group's converted figure comes to the key, whichever
    # commodities GnuCash's own collector turns out to hold.
    assert sum(Fraction(group['balance_sheet_value']) for group in groups.values()) \
        == block_total_of(page, 'gnucash_balancing_amount'), groups


def test_nothing_disposed_and_the_currency_was_bought_with_canadian_dollars(tmp_path):
    """Bought with the book's own money, so GnuCash's amount is the gain.

    This is Q-044's Scenario 1. Every dollar here was bought with Canadian
    money, so both splits of every purchase carry a Canadian figure and
    GnuCash's subtraction has what it needs. Its amount then agrees with the
    gain this tool measures from the cost bases — which is what the key is on
    the page for, and the thing a reader checks.

    Asserted as that agreement rather than as a number, because the number is
    whatever the book's prices come to; what must hold is that the two ways of
    reaching it arrive at the same place on a book where both can.
    """
    runner = CliRunner()
    page = _sheet(runner,
                  _from_a_plain_book(runner, tmp_path, BOUGHT_WITH_CAD, 'earned'))

    measured = Fraction(key_of(page, 'total_unrealized_gains').split(' ')[0])
    assert block_total_of(page, 'gnucash_balancing_amount') == measured, page

    groups = _groups_of(page)
    assert groups['CAD'] == {'sum_value': '10400.00', 'balance_value': '5000.00',
                             'gains_before_conversion': '-5400.00',
                             'balance_sheet_value': '-5400.00'}, groups


def test_a_security_is_the_gain_not_yet_taken(tmp_path):
    """A holding counted in units and priced, so nothing was disposed of.

    The shares were bought with Canadian dollars, so both splits of the
    purchase carry a Canadian figure and GnuCash's subtraction has what it
    needs. Its amount is then the gain on the holding, which this page also
    measures as `unrealized_gains_other` — the two agree, as they do wherever
    GnuCash's method can work.

    The Canadian group carries the purchase: 3,120.00 of split value against a
    share account whose own commodity is AMZN. The shares are a group of their
    own, being held in a commodity no split is valued in, and it is their
    2,000.00 at the sheet's price that turns that -3,120.00 into the gain.
    """
    runner = CliRunner()
    page = _sheet(runner, _from_a_plain_book(runner, tmp_path, SECURITY, 'shares'))

    assert block_total_of(page, 'gnucash_balancing_amount') \
        == block_total_of(page, 'unrealized_gains_other'), page

    groups = _groups_of(page)
    assert groups['CAD']['gains_before_conversion'] == '-3120.00', groups


def test_the_working_states_the_subtraction_it_came_from(tmp_path):
    """The itemization, which is what makes the figure checkable.

    A bare `0.01 CAD` stated an amount and could be checked against nothing.
    The group now states the subtraction: the splits' values added up, what the
    accounts holding that currency hold, the difference, and the difference
    converted.
    """
    runner = CliRunner()
    page = _sheet(runner, _from_a_plain_book(runner, tmp_path, TWO_BROKERS, 'brokers'))

    groups = _groups_of(page)
    assert groups['CAD'] == {'sum_value': '1000.00', 'balance_value': '980.00',
                             'gains_before_conversion': '-20.00',
                             'balance_sheet_value': '-20.00'}, groups


def test_every_group_states_its_own_subtraction(tmp_path):
    """No group may state a figure without the two terms behind it.

    A key that carried only its total is the one figure on the page a reader
    has to take on trust, which is what the itemization exists to end. So each
    group carries all four lines, and the difference is the two before it.
    """
    runner = CliRunner()
    page = _sheet(runner, _from_a_plain_book(runner, tmp_path, SECURITY, 'shares'))

    for mnemonic, fields in _groups_of(page).items():
        # `splits` is the list's own line rather than a figure, and it carries
        # a note where the list is empty — a commodity whose accounts hold it
        # but whose transactions are stated in another currency has no split
        # valued in it, and says so rather than printing a bare key.
        assert set(fields) - {'splits'} == {'sum_value', 'balance_value',
                                            'gains_before_conversion',
                                            'balance_sheet_value'}, (mnemonic, fields)
        assert (Fraction(fields['gains_before_conversion'])
                == Fraction(fields['balance_value'])
                - Fraction(fields['sum_value'])), (mnemonic, fields)


def test_neither_gain_where_one_holding_carries_no_canadian_figure(tmp_path):
    """The fourth case: nothing disposed of, and the two figures still disagree.

    GnuCash's amount and the amount measured from the cost bases part company
    whenever a holding's splits carry no figure in the book's own currency —
    here the collected half. Nothing has been disposed of, so this is not a gain
    already taken; the two do not agree, so it is not the gain still to come;
    and GnuCash measured something, so it is not the silent case either.

    No figure is asserted. What the amounts come to depends on the rate the page
    carries; what the page must not do is call this either gain.
    """
    runner = CliRunner()
    page = _sheet(runner, _collected_and_bought(runner, tmp_path))

    assert block_total_of(page, 'realized_gains_fx') == 0

    # Both halves show, and they pull opposite ways: the collected dollars make
    # the US dollar group's accounts exceed its split values by the thousand
    # bought with Canadian money, while the Canadian group is short by what
    # that thousand cost.
    groups = _groups_of(page)
    assert groups['USD']['gains_before_conversion'] == '1000.00', groups
    assert groups['CAD']['gains_before_conversion'] == '-1300.00', groups
    assert block_total_of(page, 'gnucash_balancing_amount') == Fraction('86.5')
    assert key_of(page, 'total_unrealized_gains') == '66.64 CAD'
