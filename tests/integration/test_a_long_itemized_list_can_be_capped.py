"""`--max-items` shortens a long itemized list, and the list still adds up.

Every itemized key lists one entry per thing it is measured from, and nothing
caps that by default, because the items exist so a reader can add the total up
for themselves. Measured on a generated book by
`tests/research/how_a_page_grows_with_the_splits_behind_it_probe.py`: 2,500
foreign purchases draw 40,154 lines and 1.4 MB, of which 40,069 lines are the
four itemized keys.

Grouping the entries instead was measured and does not work — on a book whose
purchases differ from one another, 2,500 cost bases fall into 2,500 distinct
account-and-price groups. So the only thing that shortens such a page is
leaving entries out, and that is asked for rather than applied.

**What must hold when it is asked for is the arithmetic.** Each of these keys
ends in totals whose own comments say they are the sum of the entries above
them, so a list that simply stopped after five made its own comment untrue and
left a reader adding figures that come to less than the total beneath them. A
shortened list therefore ends with `not_listed:`, carrying the count and what
the rest come to.

`-1` is no cap and is the default; `0` lists none; every other number means
itself. Zero meant "all" at first and read backwards — a page saying
`--max-items 0 for all` asks a reader to learn that nought means everything.
"""

from fractions import Fraction

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import block_of, block_total_of, key_of

# 1,000.00 USD bought at each of 1.20, 1.30, 1.40 and 1.50: four cost bases on
# one account, so one key carries four entries and a cap of two bites.
FOUR_RATES = 'tests/fixtures/a_cad_book_that_bought_usd_at_four_rates_and_spends_only_cad.txt'

YEAR_END = '2026-12-31'


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), FOUR_RATES)
    assert made.exit_code == 0, made.output
    return book


def _sheet(book, *extra):
    drawn = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', YEAR_END, *extra)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def _cost_bases_in(page):
    return block_of(page, 'unrealized_gains_assets_fx').count('cost_basis:')


def _figures_named(page, key, field):
    """Every `field:` under `key`, as Fractions, whatever depth they sit at."""
    found = []
    for line in block_of(page, key).splitlines():
        name, _, rest = line.strip().partition(': ')
        if name == field:
            found.append(Fraction(rest.split(' #')[0].strip()))
    return found


def test_every_entry_is_listed_by_default(tmp_path):
    """Four purchases, four cost bases, and nothing saying anything was left out."""
    page = _sheet(_book(tmp_path))

    assert _cost_bases_in(page) == 4, page
    assert 'not_listed' not in page, page
    assert '--max-items' not in page, page


def test_a_cap_lists_that_many_and_says_where_the_rest_went(tmp_path):
    """Two of the four, and the list's own line says the other two are below it."""
    page = _sheet(_book(tmp_path), '--max-items', '2')

    assert _cost_bases_in(page) == 2, page
    assert ('\t\t\t\tcost_bases: # 4 cost bases, 2 listed and the rest under'
            ' not_listed; --max-items -1 for all') in page.splitlines(), page


def test_the_entries_and_the_rest_come_to_the_total_printed_beneath_them(tmp_path):
    """The point of `not_listed:`, and what the totals' own comments claim.

    `cost_basis_balance:` at the end of the commodity says it is the sum of
    each cost basis's, so the figures above it have to come to it — two listed
    at 1,000.00 each and 2,000.00 carried in `not_listed:` against a total of
    4,000.00.
    """
    page = _sheet(_book(tmp_path), '--max-items', '2')

    # Every `cost_basis_balance:` in the block: two entries, the not-listed
    # one, and the commodity's total. The block states none of its own, a
    # quantity added across commodities being units of nothing.
    balances = _figures_named(page, 'unrealized_gains_assets_fx', 'cost_basis_balance')
    assert balances == [Fraction(1000), Fraction(1000), Fraction(2000),
                        Fraction(4000)], balances

    costs = _figures_named(page, 'unrealized_gains_assets_fx', 'cost_value')
    assert costs == [Fraction(1200), Fraction(1300), Fraction(2900),
                     Fraction(5400), Fraction(5400)], costs

    gains = _figures_named(page, 'unrealized_gains_assets_fx',
                           'unrealized_gains_assets_fx')
    assert gains == [Fraction(300), Fraction(200), Fraction(100),
                     Fraction(600), Fraction(600)], gains


def test_the_split_list_carries_its_rest_too(tmp_path):
    """The balancing block's splits are capped the same way and still total.

    Whatever the cap leaves out is carried in `not_listed:`, so in every
    commodity group the splits printed plus that entry come to the group's own
    `sum_value`.

    Asserted across the block rather than against one group's figures: which
    commodities it lists is GnuCash's business — its figure spans every
    commodity an account is held in as well as every currency a split is
    valued in — so a test written against a particular set of groups would
    break whenever a fixture gained an account, with nothing wrong.
    """
    page = _sheet(_book(tmp_path), '--max-items', '2')
    block = block_of(page, 'gnucash_balancing_amount')

    assert '\t\t\t\t\tnot_listed:' in block.splitlines(), block

    listed_and_the_rest = _figures_named(page, 'gnucash_balancing_amount', 'value')
    per_group = _figures_named(page, 'gnucash_balancing_amount', 'sum_value')
    assert sum(listed_and_the_rest) == sum(per_group), block


def test_the_totals_do_not_move_when_the_list_is_shortened(tmp_path):
    """What the cap changes is the page's length and nothing else."""
    book = _book(tmp_path)
    whole = _sheet(book)
    capped = _sheet(book, '--max-items', '2')

    for name in ('unrealized_gains_assets_fx', 'realized_gains_fx',
                 'unrealized_gains_other', 'gnucash_balancing_amount'):
        assert block_total_of(capped, name) == block_total_of(whole, name), name

    for key in ('unrealized_gains_fx', 'total_unrealized_gains',
                'total_assets', 'total_liabilities_and_equity'):
        assert key_of(capped, key) == key_of(whole, key), key


def test_minus_one_is_every_entry(tmp_path):
    """The default said out loud, so a command can carry it and mean no cap."""
    book = _book(tmp_path)

    assert _sheet(book, '--max-items', '-1') == _sheet(book)


def test_zero_lists_none_of_them_and_still_says_what_they_come_to(tmp_path):
    """Zero means zero, which is the useful thing it looks like.

    **Every list, including the commodities.** A commodity group is an entry of
    the `commodities:` list like any other, so at zero none is drawn and the
    cost bases inside them go with them — there is no entry left on the page to
    carry a `cost_basis_balance`. What stands in their place is one
    `not_listed:` entry for the whole list, and the block's own totals beneath
    it, which state the same figures they state uncapped.
    """
    page = _sheet(_book(tmp_path), '--max-items', '0')

    assert _cost_bases_in(page) == 0, page
    assert block_of(page, 'unrealized_gains_assets_fx').count('commodity:') == 0, page
    assert ('\t\tcommodities: # 1 commodity, 0 listed and the rest under'
            ' not_listed; --max-items -1 for all') in page.splitlines(), page

    # The carried entry and the totals say the same thing, because the one
    # commodity left out is the whole block.
    assert _figures_named(page, 'unrealized_gains_assets_fx', 'cost_value') \
        == [Fraction(5400), Fraction(5400)], page
    assert _figures_named(page, 'unrealized_gains_assets_fx',
                          'unrealized_gains_assets_fx') \
        == [Fraction(600), Fraction(600)], page


def test_a_cap_larger_than_every_list_leaves_them_whole(tmp_path):
    """Nothing is left out, so nothing says anything was.

    Larger than every list on the page, not merely than the cost bases: this
    book's balancing block lists twelve splits against its four cost bases, so
    a cap of ten would shorten one while leaving the other alone.
    """
    page = _sheet(_book(tmp_path), '--max-items', '50')

    assert _cost_bases_in(page) == 4, page
    assert 'not_listed' not in page, page


def test_below_minus_one_is_refused(tmp_path):
    """There is no number of entries below none, and -1 already means all."""
    result = _run(CliRunner(), 'balance-sheet', str(_book(tmp_path)),
                  '--as-of', YEAR_END, '--max-items', '-2')

    assert result.exit_code != 0, result.output
    assert '-2' in result.output, result.output


def test_the_securities_list_is_capped_and_still_totals(tmp_path):
    """`unrealized_gains_other` is a list like the rest, and obeys the cap.

    It was the one that did not, while README, `--max-items --help` and
    `docs/multi-currency.md` all said every itemized list is shortened. A
    brokerage holding a few thousand securities printed every one of them
    under `--max-items 5`, and a reader who asked for a short page got a long
    one with no indication that the option had been ignored.

    `all_account_types_book.txt` holds ACME and VGRO, each bought for 500.00
    CAD and each worth 600.00 at the prices file's figures, so a cap of one
    lists one security and carries the other in `not_listed:`.
    """
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book),
                'tests/fixtures/all_account_types_book.txt')
    assert made.exit_code == 0, made.output
    priced = ('--prices', 'tests/fixtures/security_prices.yaml')

    whole = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2024-12-31',
                 *priced)
    capped = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2024-12-31',
                  *priced, '--max-items', '1')
    assert whole.exit_code == 0, whole.output
    assert capped.exit_code == 0, capped.output

    assert block_of(whole.output, 'unrealized_gains_other').count('security:') == 2
    assert block_of(capped.output, 'unrealized_gains_other').count('security:') == 1
    assert ('\t\tsecurities: # 2 securities, 1 listed and the rest under'
            ' not_listed; --max-items -1 for all') in capped.output.splitlines()

    # The one left out is carried, so the three totals beneath still have the
    # entries above them adding up to what their comments say they do.
    assert '\t\t\tnot_listed:' in capped.output.splitlines(), capped.output
    assert '\t\t\t\tcount: 1' in capped.output.splitlines(), capped.output
    assert block_total_of(capped.output, 'unrealized_gains_other') == \
        block_total_of(whole.output, 'unrealized_gains_other')
    assert key_of(capped.output, 'total_unrealized_gains') == \
        key_of(whole.output, 'total_unrealized_gains')


def test_the_splits_under_a_security_are_capped(tmp_path):
    """And the deepest list of all, the splits that brought a holding about.

    AMZN was bought 20 and sold 8, so its account carries two split lines. A
    cap of one lists one, says on the `splits:` line what it is not showing,
    and ends with the `not_listed:` entry that line promises.

    **That entry carries a count and no figures.** Each line is a reading of
    one split — units beside what they cost in that transaction's own currency
    — and several transactions' currencies add to nothing, so there is no
    total beneath them for a carried figure to complete. What there is to say
    is how many were left out, and saying "the rest under not_listed" while
    writing no such entry sent a reader looking for something that was not
    there.
    """
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book),
                'tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt')
    assert made.exit_code == 0, made.output

    whole = _sheet(book)
    capped = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', YEAR_END,
                  '--max-items', '1')
    assert capped.exit_code == 0, capped.output

    assert block_of(whole, 'unrealized_gains_other').count('split_amount ') == 2
    assert block_of(capped.output, 'unrealized_gains_other').count('split_amount ') == 1
    assert ('\t\t\t\t\t\tsplits: # 2 splits, 1 listed and the rest under'
            ' not_listed; --max-items -1 for all') in capped.output.splitlines()
    # The entry that line promises, with the count and nothing else.
    assert '\t\t\t\t\t\t\tnot_listed:' in capped.output.splitlines(), capped.output
    assert '\t\t\t\t\t\t\t\tcount: 1' in capped.output.splitlines(), capped.output
    assert block_total_of(capped.output, 'unrealized_gains_other') == \
        block_total_of(whole, 'unrealized_gains_other')


def test_a_capped_security_account_list_carries_the_balance_it_left_out(tmp_path):
    """`quantity:` is the sum of those balances, so the cap has to carry one.

    A security's `value:` and `cost_value:` are converted rather than summed
    from its accounts, but `quantity:` four lines above is exactly what they
    hold between them. Capped with a count alone, the block stated a quantity a
    reader could not reach: two accounts holding 1.0000 each, one listed, and
    nothing saying where the other 1.0000 was.
    """
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book),
                'tests/fixtures/a_cad_book_holding_one_security_in_two_accounts.txt')
    assert made.exit_code == 0, made.output

    whole = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', YEAR_END)
    capped = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', YEAR_END,
                  '--max-items', '1')
    assert whole.exit_code == 0, whole.output
    assert capped.exit_code == 0, capped.output

    listed = block_of(capped.output, 'unrealized_gains_other')
    assert listed.count('account:') == 1, listed
    assert ('\t\t\t\taccounts: # 2 accounts, 1 listed and the rest under'
            ' not_listed; --max-items -1 for all') in capped.output.splitlines()
    assert '\t\t\t\t\tnot_listed:' in capped.output.splitlines(), capped.output

    # The listed account's balance plus the carried one come to `quantity:`.
    held = _figures_named(capped.output, 'unrealized_gains_other', 'balance')
    quantity = _figures_named(capped.output, 'unrealized_gains_other', 'quantity')
    assert sum(held) == quantity[0], (held, quantity)
    assert block_total_of(capped.output, 'unrealized_gains_other') == \
        block_total_of(whole.output, 'unrealized_gains_other')


def test_report_passes_the_cap_through(tmp_path):
    """`report` draws the same balance sheet, so it takes the same option."""
    result = _run(CliRunner(), 'report', str(_book(tmp_path)), 'balance-sheet',
                  '--start', '2026-01-01', '--end', YEAR_END, '--max-items', '2')

    assert result.exit_code == 0, result.output
    assert _cost_bases_in(result.output) == 2, result.output
