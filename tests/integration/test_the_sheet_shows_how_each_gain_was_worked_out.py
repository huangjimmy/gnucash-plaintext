"""Every gain figure on the balance sheet shows its working, and the working adds up to it.

A reader can check an account line against their own book, and a section total
by adding the lines above it. A gain can be checked against neither: it is
measured against costs that appear on no line of the page. So the page states
how each gain figure was reached, and these read that working back and add it
up (Q-043).

Four keys state their items rather than a figure — `realized_gains_fx`,
`unrealized_gains_assets_fx`, `unrealized_gains_other` and
`gnucash_balancing_amount`. Each opens with a bare key line and carries its
items nested under it, ending in its own total, in the shape Q-044 fixes:

    unrealized_gains_assets_fx:
        commodities:
            commodity:
                commodity.mnemonic: "USD"
                type: asset
                share_price: 1.5 # current price of commodity in balance sheet currency
                cost_bases:
                    cost_basis:
                        ...
                        unrealized_gains_assets_fx: 300.00 # value - cost_value

So a reader can check every figure from the lines above it, and these assert
each block whole rather than sampling a figure out of it: a changed comment, a
dropped `value:` or a renamed field fails, not only a wrong number.

Each block is asserted against the fixture it was measured from, which is the
fixture Q-044's own example came from — four cost bases at four rates, four
disposals, a stock and a fund both priced, and a US dollar bank spent out.
`--no-itemize` leaves the keys stating their figures and takes the items away.
"""

import re
from fractions import Fraction

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import block_of, key_of, totals_of

EARNED = 'tests/fixtures/a_cad_book_earning_usd_three_times.txt'
SPENT_IN_FOUR = 'tests/fixtures/the_usd_earned_three_times_spent_out_in_four.txt'
FOUR_RATES = ('tests/fixtures/'
              'a_cad_book_that_bought_usd_at_four_rates_and_spends_only_cad.txt')
Q042 = ('tests/fixtures/'
        'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt')
COLLECTED = 'tests/fixtures/a_usd_invoice_collected_into_a_usd_bank.txt'
PARTLY_SPENT = 'tests/fixtures/the_usd_bank_partly_spent_leaving_a_thousand.txt'
RATES = 'tests/fixtures/usd_at_the_invoice_rate_then_lower_at_the_year_end.yaml'
BETWEEN_CENTS = ('tests/fixtures/'
                 'usd_at_a_year_end_rate_that_lands_between_cents.yaml')
YEAR_END = '2026-12-31'


def _itemized(page):
    """The four keys that carry items, as `{name: block text}`."""
    return {name: block_of(page, name)
            for name in ('realized_gains_fx', 'unrealized_gains_assets_fx',
                         'unrealized_gains_other', 'gnucash_balancing_amount')}


def _book(runner, tmp_path, fixture, name='book.gnucash'):
    book = tmp_path / name
    made = _run(runner, 'import', '--new', str(book), fixture)
    assert made.exit_code == 0, made.output
    return book


def _spent_in_four(runner, tmp_path):
    """The book that earns US dollars three times and spends every one in four payments."""
    book = _book(runner, tmp_path, EARNED)
    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    with open(SPENT_IN_FOUR, encoding='utf-8') as source:
        filled = source.read()
    for placeholder, opened in (('{basis_at_130}', '2026-02-01'),
                                ('{basis_at_135}', '2026-04-01'),
                                ('{basis_at_140}', '2026-06-01')):
        guid = next(re.search(r'\b([0-9a-f]{32})\b', line).group(1)
                    for line in listing.output.splitlines()
                    if line.strip().startswith(opened))
        filled = filled.replace(placeholder, guid)
    ledger = tmp_path / 'spend.txt'
    ledger.write_text(filled, encoding='utf-8')
    spent = _run(runner, 'import', str(book), str(ledger))
    assert spent.exit_code == 0, spent.output
    return book


def _partly_spent(runner, tmp_path):
    """The US dollar invoice collected, then spent down to 1,000.00 USD left.

    What those 1,000.00 cost is 189557/136 = 1393.8014…, a figure with a
    remainder — which is what the sub-cent case needs, and what a book whose
    cost basis is untouched cannot produce: an untouched basis cost exactly the
    money it was bought for, and money has no remainder.
    """
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), COLLECTED,
                '--fx-rates', RATES, '--include-business-objects')
    assert made.exit_code == 0, made.output

    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    guid = None
    for line in listing.output.splitlines():
        if 'Accounts Receivable USD' in line:
            found = re.search(r'\b([0-9a-f]{32})\b', line)
            if found:
                guid = found.group(1)
                break
    assert guid, listing.output

    with open(PARTLY_SPENT, encoding='utf-8') as source:
        filled = source.read().replace('{usd_basis}', guid)
    ledger = tmp_path / 'spend.txt'
    ledger.write_text(filled, encoding='utf-8')
    spent = _run(runner, 'import', str(book), str(ledger), '--fx-rates', RATES)
    assert spent.exit_code == 0, spent.output
    return book


def _sheet(runner, book, *flags):
    sheet = _run(runner, 'balance-sheet', str(book), '--as-of', YEAR_END, *flags)
    assert sheet.exit_code == 0, sheet.output
    return sheet.output


class TestTheWorkingAddsUpToTheKey:

    def test_on_a_book_of_cost_bases_a_fallback_and_a_security(self, tmp_path):
        """The Q-042 book: HKD measured from its cost basis, USD from GnuCash's
        own revaluation because its cost basis balance is not what the book
        holds, and AMZN a security. Three sources, four keys.

        **Both kinds of commodity group state the same two columns**, which is
        what lets one subtraction cover the whole block. A group measured from
        cost bases reaches `value` and `cost_value` by adding up the bases it
        lists; a group that cannot reach them that way says
        `measured_from: gnucash_revaluation` and states the cost and the worth
        GnuCash's own subtraction used. Either way the block's total is
        `value - cost_value` over every group — there is no separate fallback
        term added on the end, and a reader adds one column down the page.
        """
        page = _sheet(CliRunner(), _book(CliRunner(), tmp_path, Q042))

        blocks = _itemized(page)
        assert 'commodity.mnemonic: "HKD"' in blocks['unrealized_gains_assets_fx']
        assert 'commodity.mnemonic: "USD"' in blocks['unrealized_gains_assets_fx']
        assert 'measured_from: gnucash_revaluation' in blocks['unrealized_gains_assets_fx']
        assert 'commodity.mnemonic: "AMZN"' in blocks['unrealized_gains_other']
        assert 'commodity.mnemonic: "USD"' in blocks['gnucash_balancing_amount']

        for name in ('unrealized_gains_assets_fx', 'unrealized_gains_other'):
            totals = totals_of(page, name)
            assert totals[name] == totals['value'] - totals['cost_value'], (
                name, totals)

    def test_on_a_book_of_four_disposals_against_three_cost_bases(self, tmp_path):
        """Four realized differences, which must sum to the realized key."""
        runner = CliRunner()
        page = _sheet(runner, _spent_in_four(runner, tmp_path))

        assert block_of(page, 'realized_gains_fx') == '\n'.join((
            '\t\trealized_gains_fx: 250.00',
            '\t\tsplits:',
            '\t\t\tsplit:',
            '\t\t\t\tdate: 2026-07-01',
            '\t\t\t\taccount: "Income:FX Gain"',
            '\t\t\t\tamount: 90.00',
            '\t\t\tsplit:',
            '\t\t\t\tdate: 2026-08-01',
            '\t\t\t\taccount: "Income:FX Gain"',
            '\t\t\t\tamount: 80.00',
            '\t\t\tsplit:',
            '\t\t\t\tdate: 2026-09-01',
            '\t\t\t\taccount: "Income:FX Gain"',
            '\t\t\t\tamount: 60.00',
            '\t\t\tsplit:',
            '\t\t\t\tdate: 2026-10-01',
            '\t\t\t\taccount: "Income:FX Gain"',
            '\t\t\t\tamount: 20.00'))

    def test_on_a_book_of_four_cost_bases_at_four_rates(self, tmp_path):
        """Four bases at four rates, each stating its own gain against one price.

        Every one of these dollars was bought with Canadian ones, so the pair
        the trade happened at is the book's own currency against the foreign
        one: `cost_share_price` and `cost_share_price_in_base` are the same
        number and `cost_rate` is 1. A security priced in a foreign currency is
        where the three come apart.
        """
        runner = CliRunner()
        page = _sheet(runner, _book(runner, tmp_path, FOUR_RATES))

        basis = '\n'.join((
            '\t\t\t\t\tcost_basis:',
            '\t\t\t\t\t\tsplit_guid: <guid>',
            '\t\t\t\t\t\taccount: "Assets:USD Bank"',
            '\t\t\t\t\t\tcost_basis_balance: 1000.00',
            '\t\t\t\t\t\tcost_share_price: {rate} # USD in CAD, on the day it'
            ' was bought',
            '\t\t\t\t\t\tcost_rate: 1 # CAD per CAD, on that same day',
            '\t\t\t\t\t\tcost_share_price_in_base: {rate} # cost_share_price'
            ' * cost_rate',
            '\t\t\t\t\t\tcost_value: {cost} # cost_basis_balance *'
            ' cost_share_price_in_base',
            '\t\t\t\t\t\tvalue: 1500.00 # cost_basis_balance * share_price',
            '\t\t\t\t\t\tunrealized_gains_assets_fx: {gain} # value - cost_value'))
        assert block_of(page, 'unrealized_gains_assets_fx') == '\n'.join((
            '\t\tcommodities:',
            '\t\t\tcommodity:',
            '\t\t\t\tcommodity.mnemonic: "USD"',
            '\t\t\t\ttype: asset',
            '\t\t\t\tshare_price: 1.5 # current price of commodity in balance'
            ' sheet currency',
            '\t\t\t\tcost_bases:',
            basis.format(rate='1.2', cost='1200.00', gain='300.00'),
            basis.format(rate='1.3', cost='1300.00', gain='200.00'),
            basis.format(rate='1.4', cost='1400.00', gain='100.00'),
            basis.format(rate='1.5', cost='1500.00', gain='0.00'),
            "\t\t\t\tcost_basis_balance: 4000.00 # sum of each cost_basis's"
            ' cost_basis_balance',
            "\t\t\t\tcost_value: 5400.00 # sum of each cost_basis's cost_value",
            # What the accounts hold, beside what the cost bases say. Here they
            # agree, because every dollar bought is still in the bank.
            '\t\t\t\taccounts:',
            '\t\t\t\t\taccount:',
            '\t\t\t\t\t\tguid: <guid>',
            '\t\t\t\t\t\tname: "Assets:USD Bank"',
            '\t\t\t\t\t\tbalance: 4000.00',
            "\t\t\t\tbalance_value: 4000.00 # sum of account's balance for all"
            ' accounts',
            '\t\t\t\tvalue: 6000.00 # cost_basis_balance * share_price',
            '\t\t\t\tunrealized_gains_assets_fx: 600.00 # value - cost_value',
            "\t\tcost_value: 5400.00 # sum of each commodity's cost_value",
            "\t\tvalue: 6000.00 # sum of each commodity's value",
            '\t\tunrealized_gains_assets_fx: 600.00 # value - cost_value'))

    def test_where_the_worth_and_the_cost_both_land_between_cents(self, tmp_path):
        """The case every other fixture rounds away.

        A key and its working can only disagree where the two terms behind them
        round in opposite directions by more than half a cent between them, and
        no other fixture here does: each divides exactly, or leaves a remainder
        far too small. So this assertion ran for the whole of its life without
        being able to fail, and a key that stopped agreeing with its own
        working went unnoticed until a review read the two expressions.

        1,000.00 USD costing 189557/136 = 1393.8014… is worth 1386.466 at
        1.386466. Rounding the terms yields 1386.47 − 1393.80 = −7.33; taking
        the difference first yields −7.3354…, which rounds to −7.34. Both are
        −7.33 now, one computation standing behind the key and the line.
        """
        runner = CliRunner()
        page = _sheet(runner, _partly_spent(runner, tmp_path),
                      '--fx-rates', BETWEEN_CENTS)

        block = block_of(page, 'unrealized_gains_assets_fx')
        assert '\t\t\t\t\t\tunrealized_gains_assets_fx: -7.33 # value - cost_value' \
            in block.splitlines(), block
        totals = totals_of(page, 'unrealized_gains_assets_fx')
        assert totals['unrealized_gains_assets_fx'] == Fraction(-733, 100), totals

    def test_every_key_that_carries_items_states_them(self, tmp_path):
        """Such a key without its items would be the one figure taken on trust."""
        runner = CliRunner()
        page = _sheet(runner, _spent_in_four(runner, tmp_path))

        for name, block in _itemized(page).items():
            assert block.strip(), (name, page)


class TestTurningItOff:

    def test_no_itemize_leaves_the_keys_and_takes_the_items(self, tmp_path):
        runner = CliRunner()
        book = _book(runner, tmp_path, Q042)

        page = _sheet(runner, book, '--no-itemize')

        # Every key states its own figure, and none carries items under it.
        #
        # The currency figure is 334.40 lower than it once was and the security
        # figure 288.00 higher, and both come of the same change: the AMZN
        # purchase and sale are stated in Canadian dollars, so their split
        # values are Canadian figures the sheet's rate no longer moves. The
        # 288.00 is the currency movement on the 12 shares still held — 2,400
        # USD of cost at the 0.12 the dollar rose. The old figure left it out:
        # it converted the cost at the sheet's own rate, the same rate the
        # worth is converted at, so the dollar's movement was on both sides of
        # the subtraction and none of it reached the difference.
        assert key_of(page, 'unrealized_gains_assets_fx') == '605.60 CAD'
        assert key_of(page, 'unrealized_gains_other') == '1651.20 CAD'
        assert key_of(page, 'unrealized_gains_fx') == '605.60 CAD'
        assert key_of(page, 'total_unrealized_gains') == '2256.80 CAD'
        assert not [line for line in page.splitlines()
                    if line.startswith('\t\t\tcommodity:')], page

    def test_report_passes_the_flag_through(self, tmp_path):
        """`report` draws the same balance sheet and takes the same flag.

        Both commands wire it to the same renderer, and only `balance-sheet`
        was exercised — so the wiring in `report` could have broken with
        nothing here to notice.
        """
        runner = CliRunner()
        book = _book(runner, tmp_path, Q042)

        drawn = _run(runner, 'report', str(book), 'balance-sheet',
                     '--start', '2026-01-01', '--end', YEAR_END, '--no-itemize')
        assert drawn.exit_code == 0, drawn.output

        assert key_of(drawn.output, 'unrealized_gains_fx') == '605.60 CAD'
        assert not [line for line in drawn.output.splitlines()
                    if line.startswith('\t\t\tcommodity:')], drawn.output

    def test_report_itemizes_by_default(self, tmp_path):
        runner = CliRunner()
        book = _book(runner, tmp_path, Q042)

        drawn = _run(runner, 'report', str(book), 'balance-sheet',
                     '--start', '2026-01-01', '--end', YEAR_END)
        assert drawn.exit_code == 0, drawn.output

        assert block_of(drawn.output, 'unrealized_gains_assets_fx').strip(), drawn.output

    def test_the_items_are_there_without_the_flag(self, tmp_path):
        runner = CliRunner()
        book = _book(runner, tmp_path, Q042)

        assert block_of(_sheet(runner, book),
                        'unrealized_gains_assets_fx').strip(), 'itemized by default'


class TestWhereTheItemsDoNotAppear:

    def test_the_income_statement_carries_no_gain_keys(self, tmp_path):
        """It states no gain, so it has nothing to state the items of."""
        runner = CliRunner()
        book = _book(runner, tmp_path, Q042)

        statement = _run(runner, 'income-statement', str(book),
                         '--fiscal-year-end', YEAR_END)

        assert statement.exit_code == 0, statement.output
        assert 'unrealized_gains_assets_fx' not in statement.output, statement.output
        assert 'gnucash_balancing_amount' not in statement.output, statement.output
