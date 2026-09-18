"""Every gain figure on the balance sheet shows its working, and the working adds up to it.

A reader can check an account line against their own book, and a section total
by adding the lines above it. A gain can be checked against neither: it is
measured against costs that appear on no line of the page. So the page states
how each gain figure was reached, and these read that working back and add it
up (Q-043).

The working is written as `#` comment lines, which every reader of this format
skips, so it can be there without changing what a page means to a program.
`--no-itemize` turns it off.

What each line looks like, and how its figure is found:

    #   asset 5500.00 HKD cost 1000.00 CAD, at 0.2 worth 1100.00 CAD = 100.00 CAD
    #   Assets:USD Bank 840.00 CAD
    #   2026-07-01 Income:FX Gain 90.00 CAD

The first is measured from the book's own cost bases and states its arithmetic,
so its figure is what follows the `=`. The other two are a thing and what it
came to, so the figure is the last amount on the line.
"""

import re
from fractions import Fraction

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import key_of

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


def _figure_on(line):
    """The money a working line comes to, as an exact rational."""
    text = line.rsplit(' = ', 1)[-1] if ' = ' in line else line
    parts = text.split()
    assert len(parts) >= 2, line
    return Fraction(parts[-2])


def workings_of(page):
    """The page's working, as `{key name: [figure, ...]}`.

    A group opens with a line naming one key and nothing else — `#
    realized_gains_fx:` — and the lines under it are its items. The prose above
    the groups ends in no colon and opens none, and `nothing` is a group with
    no items rather than an item of zero.
    """
    groups = {}
    current = None
    for line in page.splitlines():
        bare = line.strip()
        if not bare.startswith('#'):
            continue
        body = bare.lstrip('#').strip()
        if not body:
            continue
        if body.endswith(':') and ' ' not in body[:-1]:
            current = body[:-1]
            groups[current] = []
            continue
        if current is None or body == 'nothing':
            continue
        groups[current].append(_figure_on(body))
    return groups


def _stated(page, name):
    return Fraction(key_of(page, name).split()[0])


def _every_group_adds_up(page):
    """Each group's items summed against the key it is under.

    `gnucash_balancing_amount` is the one exception, and the page says so
    itself. It is GnuCash's own figure carried across unchanged, while the
    lines under it are the accounts GnuCash revalued, each rounded to money.
    Rounding the key to match them would make it agree with its own working and
    stop agreeing with GnuCash's page, which is the only reason it is there. So
    it is held to within a cent of its lines rather than to their exact sum —
    asserting equality would be this suite requiring a guarantee the page
    disclaims, and passing only while no fixture lands on the odd cent.
    """
    groups = workings_of(page)
    assert groups, page
    for name, figures in groups.items():
        stated = _stated(page, name)
        if name == 'gnucash_balancing_amount':
            assert abs(sum(figures) - stated) <= Fraction(1, 100), (
                name, figures, page)
            continue
        assert sum(figures) == stated, (name, figures, page)
    return groups


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
    cost basis is untouched cannot give: an untouched basis cost exactly the
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
        holds, and AMZN a security. Three sources, four keys."""
        page = _sheet(CliRunner(), _book(CliRunner(), tmp_path, Q042))

        groups = _every_group_adds_up(page)
        assert 'unrealized_gains_assets_fx' in groups, groups
        assert 'unrealized_gains_other' in groups, groups
        assert 'gnucash_balancing_amount' in groups, groups

    def test_on_a_book_of_four_disposals_against_three_cost_bases(self, tmp_path):
        """Four realized differences, which must sum to the realized key."""
        runner = CliRunner()
        page = _sheet(runner, _spent_in_four(runner, tmp_path))

        groups = _every_group_adds_up(page)
        assert len(groups['realized_gains_fx']) == 4, groups
        assert sum(groups['realized_gains_fx']) == Fraction(250), groups

    def test_on_a_book_of_four_cost_bases_at_four_rates(self, tmp_path):
        runner = CliRunner()
        page = _sheet(runner, _book(runner, tmp_path, FOUR_RATES))

        _every_group_adds_up(page)

    def test_where_the_worth_and_the_cost_both_land_between_cents(self, tmp_path):
        """The case every other fixture rounds away.

        A key and its working can only disagree where the two terms behind them
        round in opposite directions by more than half a cent between them, and
        no other fixture here does: each divides exactly, or leaves a remainder
        far too small. So this assertion ran for the whole of its life without
        being able to fail, and a key that stopped agreeing with its own
        working went unnoticed until a review read the two expressions.

        1,000.00 USD costing 189557/136 = 1393.8014… is worth 1386.466 at
        1.386466. Rounding the terms gives 1386.47 − 1393.80 = −7.33; taking
        the difference first gives −7.3354…, which rounds to −7.34. Both are
        −7.33 now, one computation standing behind the key and the line.
        """
        runner = CliRunner()
        page = _sheet(runner, _partly_spent(runner, tmp_path),
                      '--fx-rates', BETWEEN_CENTS)

        groups = _every_group_adds_up(page)
        assert groups['unrealized_gains_assets_fx'] == [Fraction(-733, 100)], groups
        assert key_of(page, 'unrealized_gains_assets_fx') == '-7.33 CAD'

    def test_every_key_with_a_figure_has_a_group(self, tmp_path):
        """A gain key without a working would be the one figure taken on trust."""
        runner = CliRunner()
        page = _sheet(runner, _spent_in_four(runner, tmp_path))

        groups = workings_of(page)
        for name in ('realized_gains_fx', 'unrealized_gains_assets_fx',
                     'unrealized_gains_liabilities_fx', 'unrealized_gains_other',
                     'gnucash_balancing_amount'):
            assert name in groups, (name, page)


class TestTurningItOff:

    def test_no_itemize_leaves_the_keys_and_takes_the_working(self, tmp_path):
        runner = CliRunner()
        book = _book(runner, tmp_path, Q042)

        page = _sheet(runner, book, '--no-itemize')

        assert workings_of(page) == {}, page
        # The figures themselves are untouched.
        assert key_of(page, 'unrealized_gains_fx') == '940.00 CAD'
        assert key_of(page, 'total_unrealized_gains') == '2303.20 CAD'

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

        assert workings_of(drawn.output) == {}, drawn.output
        assert key_of(drawn.output, 'unrealized_gains_fx') == '940.00 CAD'

    def test_report_itemizes_by_default(self, tmp_path):
        runner = CliRunner()
        book = _book(runner, tmp_path, Q042)

        drawn = _run(runner, 'report', str(book), 'balance-sheet',
                     '--start', '2026-01-01', '--end', YEAR_END)
        assert drawn.exit_code == 0, drawn.output

        assert workings_of(drawn.output) != {}, drawn.output

    def test_the_working_is_there_without_the_flag(self, tmp_path):
        runner = CliRunner()
        book = _book(runner, tmp_path, Q042)

        assert workings_of(_sheet(runner, book)) != {}, 'itemized by default'


class TestItStaysAComment:

    def test_every_working_line_is_a_comment_inside_the_block(self, tmp_path):
        """One tab then `#`, like the block's own notes: at column 0 it would
        read as a dated directive, and uncommented it would read as a key."""
        runner = CliRunner()
        page = _sheet(runner, _book(runner, tmp_path, Q042))

        working = [line for line in page.splitlines()
                   if line.startswith('\t#') and ':' in line]
        assert working, page
        for line in working:
            assert line.startswith('\t#'), repr(line)

    def test_the_income_statement_carries_no_gain_working(self, tmp_path):
        """It has no gain keys, so it has nothing to show the working of."""
        runner = CliRunner()
        book = _book(runner, tmp_path, Q042)

        statement = _run(runner, 'income-statement', str(book),
                         '--fiscal-year-end', YEAR_END)

        assert statement.exit_code == 0, statement.output
        assert workings_of(statement.output) == {}, statement.output
