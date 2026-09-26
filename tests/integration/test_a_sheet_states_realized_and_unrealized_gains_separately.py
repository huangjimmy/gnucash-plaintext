"""Realized and unrealized gains are separate figures, and foreign currency is valued from the cost bases.

Six books. Three of them are one CAD book that posts a 2,720.00 USD invoice and
collects it into a US dollar bank, so every transaction that brings the dollars
in is stated in US dollars and carries no CAD figure at all.

- **Every dollar still held.** Nothing was disposed of, so nothing is realized
  and the whole 19.86 CAD is unrealized. GnuCash states no gain at all on this
  book, at any price: the dollars arrived in US dollar transactions, so the
  split values it subtracts come to what the account holds.
- **Every dollar spent.** Nothing is held, so nothing is unrealized; the
  19.86 CAD lost on the way out is realized and is on the income statement.
- **1,000.00 USD kept back.** 12.56 of the loss is realized on the 1,720.00
  that left, and 7.30 is unrealized on the 1,000.00 still held.

Those three share one cost basis between them, so a figure that summed wrongly
across bases would pass every one of them. Three further books are here for
that reason:

- **US dollars earned three times and spent out in four payments**, so four
  disposals draw on three cost bases and the first is emptied by the second
  payment made against it — 250.00 realized, summing across both.
- **1,000.00 USD bought and held**, the plain case, and the one where GnuCash's
  own Advanced Portfolio report computes the same 150.00 from arithmetic this
  shares no code with.
- **1,000.00 USD bought at each of four rates, with only Canadian dollars
  spent**, drawn at six prices. The gain is measured against all four cost
  bases together, it is 0.00 at their average of 1.35, and the Canadian rent
  moves every total and no gain.

The second book is the one the reported example cannot make — it spends every
dollar — and it is the one that fails if the two gains are ever added into a
single figure.

Each book is drawn twice, at two year-end prices, because the price decides
whether the figures can be told apart at all. GnuCash's Balance Sheet computes
what the disposals were recorded at, less those same disposed
dollars revalued at the nearest price.

- **At 1.3865**, the rate the dollars left at, it collapses to the realized figure,
  the realized figure. All three figures coincide or go to zero, and a book
  drawn only here cannot tell a computed realized gain from a copy of
  GnuCash's number.
- **At 1.45** they separate: the realized gain does not move with the report
  price, the unrealized one does — turning into a gain of 56.20 on the
  1,000.00 held — and GnuCash's balancing amount is neither.
- **At 1.2** they separate the other way: the unrealized figure is a loss of
  193.80 and GnuCash's balancing amount changes sign, while the realized loss is still
  12.56. A figure that is always negative passes a test that only ever prices
  upwards, so both directions are drawn.
"""

import re
from fractions import Fraction

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import block_of, block_total_of, key_of

PEGGED = 'tests/fixtures/a_cad_book_earning_cad_usd_and_hkd.txt'
PEGGED_SPENT = 'tests/fixtures/some_of_the_cad_usd_and_hkd_spent.txt'
FOUR_RATES = ('tests/fixtures/'
              'a_cad_book_that_bought_usd_at_four_rates_and_spends_only_cad.txt')
EARNED_NOTHING_SPENT = 'tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt'
EARNED = 'tests/fixtures/a_cad_book_earning_usd_three_times.txt'
SPENT_IN_FOUR = 'tests/fixtures/the_usd_earned_three_times_spent_out_in_four.txt'
COLLECTED = 'tests/fixtures/a_usd_invoice_collected_into_a_usd_bank.txt'
SPENT = 'tests/fixtures/the_usd_bank_spent_out_against_its_basis.txt'
PARTLY_SPENT = 'tests/fixtures/the_usd_bank_partly_spent_leaving_a_thousand.txt'
RATES = 'tests/fixtures/usd_at_the_invoice_rate_then_lower_at_the_year_end.yaml'
HIGHER_RATES = 'tests/fixtures/usd_at_the_invoice_rate_then_higher_at_the_year_end.yaml'
BELOW_RATES = 'tests/fixtures/usd_at_the_invoice_rate_then_far_below_it_at_the_year_end.yaml'

YEAR_END = '2026-12-31'


def _commodities_of(page):
    """Each commodity under `unrealized_gains_assets_fx`, as
    `{mnemonic: {field: text}}`.

    The key states one commodity per currency the cost bases speak for, and
    each states what its bases hold, what that cost, what the accounts hold,
    what it is worth at the sheet's price and the difference. Only the
    commodity's own lines, which sit four tabs in — the bases and the accounts
    it is built from are deeper, and there may be any number of either.
    """
    found = {}
    current = None
    for line in block_of(page, 'unrealized_gains_assets_fx').splitlines():
        if line.startswith('\t\t\t\t\t') or not line.startswith('\t\t\t\t'):
            continue
        field, _, rest = line.strip().partition(': ')
        if not rest:
            continue
        if field == 'commodity.mnemonic':
            current = rest.strip('"')
            found[current] = {}
        elif current is not None:
            found[current][field] = rest.split(' #')[0].strip()
    return found


def _basis_on(listing, account_fragment):
    """The guid of the cost basis sitting on the account whose name contains
    `account_fragment`."""
    for line in listing.splitlines():
        if account_fragment in line:
            match = re.search(r'\b([0-9a-f]{32})\b', line)
            if match:
                return match.group(1)
    raise AssertionError(f'no cost basis on {account_fragment!r} in:\n{listing}')


def _basis_opened_on(listing, when):
    """The guid of the cost basis opened on `when`.

    All three of that book's cost bases sit on one account, so `_basis_on`
    cannot tell them apart and the date each was opened on is what does.
    """
    for line in listing.splitlines():
        if line.strip().startswith(when):
            match = re.search(r'\b([0-9a-f]{32})\b', line)
            if match:
                return match.group(1)
    raise AssertionError(f'no cost basis opened on {when} in:\n{listing}')


def _collected(runner, tmp_path):
    """A book holding 2,720.00 USD, collected from an invoice posted at 1.393801."""
    book = tmp_path / 'book.gnucash'
    result = _run(runner, 'import', '--new', str(book), COLLECTED,
                  '--fx-rates', RATES, '--include-business-objects')
    assert result.exit_code == 0, result.output
    return book


def _spend(runner, tmp_path, book, fixture):
    """Import `fixture` onto `book`, with the cost basis guid filled in.

    A guid is made fresh on each import, so the fixture carries a placeholder
    and the guid is read from `fx-balances` here, as the other cost-basis tests
    do.
    """
    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    with open(fixture, encoding='utf-8') as source:
        filled = source.read().replace(
            '{usd_basis}', _basis_on(listing.output, 'Accounts Receivable USD'))
    ledger = tmp_path / 'spend.txt'
    ledger.write_text(filled, encoding='utf-8')
    result = _run(runner, 'import', str(book), str(ledger), '--fx-rates', RATES)
    assert result.exit_code == 0, result.output
    return book


def _sheet(runner, book, rates=RATES):
    result = _run(runner, 'balance-sheet', str(book), '--as-of', YEAR_END,
                  '--fx-rates', rates)
    assert result.exit_code == 0, result.output
    return result.output


class TestEveryDollarStillHeld:
    """Nothing disposed of, so nothing realized and the whole 19.86 is unrealized.

    This is the book GnuCash cannot report on at all. Its balancing amount is
    0.00 at every price, because the invoice and its collection are both stated
    in US dollars and their split values sum to exactly what the account holds.
    What makes this sheet balance is the figure the book's own cost basis holds.
    """

    def _pages(self, tmp_path):
        """The one book, drawn at 1.3865, then 1.45, then 1.2.

        Built once: `_collected` imports with `--new` to a fixed path, so
        calling it a second time in one test would be refused.
        """
        runner = CliRunner()
        book = _collected(runner, tmp_path)
        return tuple(_sheet(runner, book, rates)
                     for rates in (RATES, HIGHER_RATES, BELOW_RATES))

    def test_nothing_is_realized_while_every_dollar_is_still_held(self, tmp_path):
        page, _higher, _below = self._pages(tmp_path)

        assert block_total_of(page, 'realized_gains_fx') == 0
        assert key_of(page, 'total_realized_gains') == '0.00 CAD'

    def test_the_whole_loss_is_unrealized(self, tmp_path):
        """2,720.00 USD that cost 3,791.14 CAD is worth 3,771.28 at 1.3865."""
        page, _higher, _below = self._pages(tmp_path)

        assert block_total_of(page, 'unrealized_gains_assets_fx') == Fraction('-19.86')
        assert key_of(page, 'unrealized_gains_liabilities_fx') == '0.00 CAD'
        assert key_of(page, 'unrealized_gains_fx') == '-19.86 CAD'
        assert block_total_of(page, 'unrealized_gains_other') == 0
        assert key_of(page, 'total_unrealized_gains') == '-19.86 CAD'

    def test_gnucash_states_no_gain_on_this_book_at_any_price(self, tmp_path):
        """Neither direction moves it, because it is not measuring a movement."""
        page, higher, below = self._pages(tmp_path)

        assert block_total_of(page, 'gnucash_balancing_amount') == 0
        assert block_total_of(higher, 'gnucash_balancing_amount') == 0
        assert block_total_of(below, 'gnucash_balancing_amount') == 0

    def test_the_sheet_balances_on_what_the_cost_basis_holds(self, tmp_path):
        page, _higher, _below = self._pages(tmp_path)

        assert key_of(page, 'retained_earnings') == '3791.14 CAD'
        assert key_of(page, 'total_assets') == '3771.28 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '3771.28 CAD'

    def test_the_unrealized_figure_moves_with_the_price_both_ways(self, tmp_path):
        """A gain of 152.86 at 1.45 and a loss of 527.14 at 1.2, each balancing."""
        _page, higher, below = self._pages(tmp_path)

        assert key_of(higher, 'unrealized_gains_fx') == '152.86 CAD'
        assert key_of(higher, 'total_assets') == '3944.00 CAD'
        assert key_of(higher, 'total_liabilities_and_equity') == '3944.00 CAD'

        assert key_of(below, 'unrealized_gains_fx') == '-527.14 CAD'
        assert key_of(below, 'total_assets') == '3264.00 CAD'
        assert key_of(below, 'total_liabilities_and_equity') == '3264.00 CAD'


class TestEveryDollarSpent:
    """Nothing held, so nothing unrealized; the whole 19.86 is realized."""

    def _page(self, tmp_path):
        runner = CliRunner()
        book = _collected(runner, tmp_path)
        return _sheet(runner, _spend(runner, tmp_path, book, SPENT))

    def test_the_loss_is_stated_as_realized(self, tmp_path):
        page = self._page(tmp_path)

        assert block_total_of(page, 'realized_gains_fx') == Fraction('-19.86')
        assert key_of(page, 'total_realized_gains') == '-19.86 CAD'

    def test_nothing_is_unrealized_on_a_book_holding_no_foreign_money(self, tmp_path):
        page = self._page(tmp_path)

        assert key_of(page, 'unrealized_gains_fx') == '0.00 CAD'
        assert key_of(page, 'total_unrealized_gains') == '0.00 CAD'

    def test_gnucash_balancing_amount_is_stated_as_gnucash_computes_it(self, tmp_path):
        """The dollars left at the rate the sheet is drawn at, so it comes to the realized figure.

        Carried across at GnuCash's own sign, so it can be found on GnuCash's
        own page, and under a label that does not call it a gain.
        """
        page = self._page(tmp_path)

        assert block_total_of(page, 'gnucash_balancing_amount') == Fraction('19.86')

    def test_the_sheet_balances(self, tmp_path):
        """The realized loss is in retained_earnings already and is not added again."""
        page = self._page(tmp_path)

        assert key_of(page, 'total_assets') == '3771.28 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '3771.28 CAD'


class TestAThousandDollarsKeptBack:
    """1,720.00 USD gone and 1,000.00 held: 12.56 realized against 7.30 unrealized."""

    def _page(self, tmp_path):
        runner = CliRunner()
        book = _collected(runner, tmp_path)
        return _sheet(runner, _spend(runner, tmp_path, book, PARTLY_SPENT))

    def test_the_two_gains_are_separate_figures(self, tmp_path):
        page = self._page(tmp_path)

        assert block_total_of(page, 'realized_gains_fx') == Fraction('-12.56')
        # The book owes nothing, so the whole of the unrealized figure is on
        # the asset side and the two sides come to the third.
        assert block_total_of(page, 'unrealized_gains_assets_fx') == Fraction('-7.30')
        assert key_of(page, 'unrealized_gains_liabilities_fx') == '0.00 CAD'
        assert key_of(page, 'unrealized_gains_fx') == '-7.30 CAD'

    def test_each_kind_has_its_total(self, tmp_path):
        page = self._page(tmp_path)

        assert key_of(page, 'total_realized_gains') == '-12.56 CAD'
        assert key_of(page, 'total_unrealized_gains') == '-7.30 CAD'

    def test_the_unrealized_loss_is_money_not_a_rate(self, tmp_path):
        """7.30 at the cent, never the 993/136 the revaluation yields before it is an amount."""
        page = self._page(tmp_path)

        assert '/' not in key_of(page, 'unrealized_gains_fx')
        assert '/' not in key_of(page, 'total_liabilities_and_equity')

    def test_gnucash_balancing_amount_is_stated_as_gnucash_computes_it(self, tmp_path):
        page = self._page(tmp_path)

        assert block_total_of(page, 'gnucash_balancing_amount') == Fraction('12.56')

    def test_the_sheet_balances_with_only_the_unrealized_total_in_equity(self, tmp_path):
        """3,778.58 of retained earnings less the 7.30 not yet taken."""
        page = self._page(tmp_path)

        assert key_of(page, 'retained_earnings') == '3778.58 CAD'
        assert key_of(page, 'total_assets') == '3771.28 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '3771.28 CAD'


# The non-FX keys — `realized_gains_other` and `unrealized_gains_other` — are
# specified in Q-043 and left for later work, so nothing here asserts them.
# Securities revalue correctly on the two books measured for that issue, and a
# security denominated in another currency carries an FX movement inside its
# gain that no cost basis speaks for; neither is computed yet.


class TestEveryDollarSpentPricedAwayFromTheRateTheyLeftAt:
    """The same book at 1.45, where GnuCash's balancing amount stops coinciding with the realized loss."""

    def _page(self, tmp_path):
        runner = CliRunner()
        book = _collected(runner, tmp_path)
        return _sheet(runner, _spend(runner, tmp_path, book, SPENT), HIGHER_RATES)

    def test_the_realized_loss_does_not_move_with_the_report_price(self, tmp_path):
        """What the dollars cost and what they fetched are both in the book already."""
        page = self._page(tmp_path)

        assert block_total_of(page, 'realized_gains_fx') == Fraction('-19.86')

    def test_nothing_is_unrealized_whatever_the_price(self, tmp_path):
        page = self._page(tmp_path)

        assert key_of(page, 'unrealized_gains_fx') == '0.00 CAD'

    def test_the_balancing_amount_moves_and_is_neither_gain(self, tmp_path):
        """3,791.14 of recorded cost against 2,720.00 USD at 1.45."""
        page = self._page(tmp_path)

        assert block_total_of(page, 'gnucash_balancing_amount') == Fraction('-152.86')

    def test_the_sheet_still_balances(self, tmp_path):
        page = self._page(tmp_path)

        assert key_of(page, 'total_assets') == '3771.28 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '3771.28 CAD'


class TestAThousandKeptBackPricedAwayFromTheRateTheyLeftAt:
    """At 1.45 the dollars still held are worth more than they cost, so that figure is a gain."""

    def _page(self, tmp_path):
        runner = CliRunner()
        book = _collected(runner, tmp_path)
        return _sheet(runner, _spend(runner, tmp_path, book, PARTLY_SPENT), HIGHER_RATES)

    def test_the_realized_loss_is_unchanged(self, tmp_path):
        page = self._page(tmp_path)

        assert block_total_of(page, 'realized_gains_fx') == Fraction('-12.56')

    def test_the_unrealized_figure_is_a_gain_at_this_price(self, tmp_path):
        """1,000.00 USD costing 1,393.80 is worth 1,450.00 at 1.45."""
        page = self._page(tmp_path)

        assert key_of(page, 'unrealized_gains_fx') == '56.20 CAD'

    def test_the_balancing_amount_is_neither_of_the_two_gains(self, tmp_path):
        """2,397.34 of recorded cost against 1,720.00 USD at 1.45, beside a realized 12.56 and an unrealized 56.20."""
        page = self._page(tmp_path)

        assert block_total_of(page, 'gnucash_balancing_amount') == Fraction('-96.66')

    def test_the_sheet_balances_at_the_higher_price(self, tmp_path):
        """3,778.58 of retained earnings and 56.20 not yet taken, against 3,834.78 of assets."""
        page = self._page(tmp_path)

        assert key_of(page, 'retained_earnings') == '3778.58 CAD'
        assert key_of(page, 'total_assets') == '3834.78 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '3834.78 CAD'


class TestEveryDollarSpentPricedFarBelowWhatTheyCost:
    """The same book at 1.2: still nothing unrealized, and GnuCash's balancing amount changes sign."""

    def _page(self, tmp_path):
        runner = CliRunner()
        book = _collected(runner, tmp_path)
        return _sheet(runner, _spend(runner, tmp_path, book, SPENT), BELOW_RATES)

    def test_the_realized_loss_does_not_move_with_the_report_price(self, tmp_path):
        page = self._page(tmp_path)

        assert block_total_of(page, 'realized_gains_fx') == Fraction('-19.86')

    def test_nothing_is_unrealized_whatever_the_price(self, tmp_path):
        page = self._page(tmp_path)

        assert key_of(page, 'unrealized_gains_fx') == '0.00 CAD'

    def test_the_balancing_amount_changes_sign_with_the_price(self, tmp_path):
        """3,791.14 of recorded cost against 2,720.00 USD at 1.2, where 1.45 made it −152.86."""
        page = self._page(tmp_path)

        assert block_total_of(page, 'gnucash_balancing_amount') == Fraction('527.14')

    def test_the_sheet_still_balances(self, tmp_path):
        page = self._page(tmp_path)

        assert key_of(page, 'total_assets') == '3771.28 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '3771.28 CAD'


class TestAThousandKeptBackPricedFarBelowWhatTheyCost:
    """At 1.2 the dollars still held are worth less than they cost, so that figure is a loss."""

    def _page(self, tmp_path):
        runner = CliRunner()
        book = _collected(runner, tmp_path)
        return _sheet(runner, _spend(runner, tmp_path, book, PARTLY_SPENT), BELOW_RATES)

    def test_the_realized_loss_is_unchanged(self, tmp_path):
        page = self._page(tmp_path)

        assert block_total_of(page, 'realized_gains_fx') == Fraction('-12.56')

    def test_the_unrealized_figure_is_a_loss_at_this_price(self, tmp_path):
        """1,000.00 USD costing 1,393.80 is worth 1,200.00 at 1.2, where 1.45 made it a gain."""
        page = self._page(tmp_path)

        assert key_of(page, 'unrealized_gains_fx') == '-193.80 CAD'

    def test_the_balancing_amount_changes_sign_with_the_price(self, tmp_path):
        """2,397.34 of recorded cost against 1,720.00 USD at 1.2, where 1.45 made it −96.66."""
        page = self._page(tmp_path)

        assert block_total_of(page, 'gnucash_balancing_amount') == Fraction('333.34')

    def test_the_sheet_balances_at_the_lower_price(self, tmp_path):
        """3,778.58 of retained earnings less the 193.80 not yet taken, against 3,584.78 of assets."""
        page = self._page(tmp_path)

        assert key_of(page, 'retained_earnings') == '3778.58 CAD'
        assert key_of(page, 'total_assets') == '3584.78 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '3584.78 CAD'


class TestTwoForeignCurrenciesAtOnce:
    """US and Hong Kong dollars in one book, priced through the peg, with Canadian dollars earned and spent too.

    Every other book here holds one foreign currency, so a figure that lumped
    currencies together, or measured one against another's cost basis, would
    pass all of them. This one cannot be passed that way.

    The Hong Kong dollar is pegged to the US dollar between 7.75 and 7.85, and
    with the US dollar at 1.30 the peg yields exact rationals:

        peg 7.80   1.30/7.80 = 1/6      what the 146,010.00 HKD was earned at
        peg 7.75   1.30/7.75 = 26/155
        peg 7.85   1.30/7.85 = 26/157

    The sheet is drawn at three dates, asking three different questions:

        2026-09-30  US dollar 1.40, peg 7.75 — **both currencies have moved**,
                    by different amounts: 60.00 on the US dollars and 1,391.00
                    on the Hong Kong ones. The ordinary case, and the one a
                    figure that mixed the two up could still pass plausibly.
        2026-11-30  US dollar 1.30, peg 7.85 — the Hong Kong dollar alone.
        2026-12-31  US dollar 1.30, peg 7.75 — the Hong Kong dollar alone, the
                    other way.

    **At the last two the US dollar is a control**: priced at what it was
    earned at, so its gain is 0.00 while the peg moves either side of 7.80 and
    the Hong Kong figure changes sign. A currency measured against another's
    cost basis could not leave that zero standing.
    """

    AS_OF = {'2026-09-30': ('1451.00 CAD', '23916.00 CAD'),
             '2026-11-30': ('-105.64 CAD', '22359.36 CAD'),
             '2026-12-31': ('107.00 CAD', '22572.00 CAD')}
    # The dates where the US dollar is priced at what it was earned at.
    CONTROL = ('2026-11-30', '2026-12-31')

    def _pages(self, tmp_path):
        """The one book drawn at both peg dates, built once."""
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        earned = _run(runner, 'import', '--new', str(book), PEGGED)
        assert earned.exit_code == 0, earned.output
        listing = _run(runner, 'fx-balances', str(book))
        assert listing.exit_code == 0, listing.output
        with open(PEGGED_SPENT, encoding='utf-8') as source:
            filled = (source.read()
                      .replace('{usd_basis}', _basis_on(listing.output, 'USD Bank'))
                      .replace('{hkd_basis}', _basis_on(listing.output, 'HKD Bank')))
        ledger = tmp_path / 'spend.txt'
        ledger.write_text(filled, encoding='utf-8')
        spent = _run(runner, 'import', str(book), str(ledger))
        assert spent.exit_code == 0, spent.output
        pages = {}
        for as_of in self.AS_OF:
            sheet = _run(runner, 'balance-sheet', str(book), '--as-of', as_of)
            assert sheet.exit_code == 0, sheet.output
            pages[as_of] = sheet.output
        return pages

    def test_the_peg_moving_either_way_moves_the_figure_both_ways(self, tmp_path):
        """7.85 leaves the holding worth less than it cost, 7.75 worth more."""
        pages = self._pages(tmp_path)

        for as_of, (gain, _assets) in self.AS_OF.items():
            page = pages[as_of]
            assert block_total_of(page, 'unrealized_gains_assets_fx') == Fraction(
                gain.split()[0]), (as_of, page)
            assert key_of(page, 'unrealized_gains_fx') == gain, (as_of, page)
            assert key_of(page, 'total_unrealized_gains') == gain, (as_of, page)

    def test_the_us_dollar_stays_at_nothing_where_its_price_has_not_moved(self, tmp_path):
        """Priced 1.30 at both control dates, so 600.00 USD costing 780.00 has gained nothing.

        Read off the commodity rather than the key, because the key is the two
        currencies added together and this is the one of them that must not
        move.
        """
        pages = self._pages(tmp_path)
        for as_of in self.CONTROL:
            usd = _commodities_of(pages[as_of])['USD']
            assert usd['cost_basis_balance'] == '600.00', (as_of, usd)
            assert usd['cost_value'] == '780.00', (as_of, usd)
            assert usd['value'] == '780.00', (as_of, usd)
            assert usd['unrealized_gains_assets_fx'] == '0.00', (as_of, usd)

    def test_both_currencies_move_at_once_and_each_is_measured_on_its_own(self, tmp_path):
        """At 1.40 and a peg of 7.75 neither is zero, and the two add to the key.

        99,510 divides by 155, so the Hong Kong figure is exact to the cent at
        that peg rather than rounded: 1,391.00, not 1,391.00-ish.
        """
        page = self._pages(tmp_path)['2026-09-30']

        found = _commodities_of(page)
        assert set(found) == {'USD', 'HKD'}, found
        assert found['HKD']['share_price'] == '28/155', found
        assert found['HKD']['cost_basis_balance'] == '99510.00', found
        assert found['HKD']['unrealized_gains_assets_fx'] == '1391.00', found
        assert found['USD']['share_price'] == '1.4', found
        assert found['USD']['unrealized_gains_assets_fx'] == '60.00', found
        assert block_total_of(page, 'unrealized_gains_assets_fx') == 1451

    def test_the_working_states_each_currency_separately(self, tmp_path):
        """Two commodities under the one key, each its own currency, adding to it."""
        page = self._pages(tmp_path)['2026-12-31']

        found = _commodities_of(page)
        assert set(found) == {'USD', 'HKD'}, found
        assert found['HKD']['cost_basis_balance'] == '99510.00', found
        assert found['HKD']['unrealized_gains_assets_fx'] == '107.00', found
        assert found['USD']['cost_basis_balance'] == '600.00', found
        assert found['USD']['unrealized_gains_assets_fx'] == '0.00', found

    def test_realized_sums_across_both_currencies(self, tmp_path):
        """60.00 on the US dollars and 50.00 on the Hong Kong dollars.

        Both exact: 46,500 divides by 6 and by 155, so what those Hong Kong
        dollars cost and what they fetched are each a whole number of cents.
        """
        for as_of, page in self._pages(tmp_path).items():
            assert block_total_of(page, 'realized_gains_fx') == 110, (as_of, page)
            assert key_of(page, 'total_realized_gains') == '110.00 CAD', (as_of, page)

    def test_the_canadian_earning_and_spending_move_no_gain(self, tmp_path):
        """5,000.00 earned and 900.00 of rent, both in the book's own currency.

        Built once, outside the loop: `_pages` imports with `--new`, and a
        second call on the same path is refused rather than rebuilding.
        """
        pages = self._pages(tmp_path)

        for as_of, (_gain, assets) in self.AS_OF.items():
            page = pages[as_of]
            assert key_of(page, 'retained_earnings') == '21465.00 CAD', (as_of, page)
            assert key_of(page, 'total_assets') == assets, (as_of, page)
            assert key_of(page, 'total_liabilities_and_equity') == assets, (as_of, page)


class TestUsdBoughtAtFourRatesAndPricedAtSix:
    """1,000.00 USD bought at each of 1.20, 1.30, 1.40 and 1.50, and only Canadian dollars spent.

    Four cost bases, none disposed of, so the figure is measured against all
    four added together: 5,400.00 for 4,000.00 dollars, an average of exactly
    1.35. Drawn at six prices, the gain is 4,000 × price − 5,400.00 every time.

        priced at    1.00      1.20     1.35    1.40     1.45     1.50
        unrealized  -1400.00  -600.00   0.00   200.00   400.00   600.00

    The 1,200.00 of rent is paid in Canadian dollars from the Canadian bank. It
    moves `total_assets` and must move no gain: a figure that counted Canadian
    movements is what charged 19.86 to a Canadian account on the book this
    issue was reported from.
    """

    PRICED = {
        '1': ('-1400.00 CAD', '7400.00 CAD'),
        '1.2': ('-600.00 CAD', '8200.00 CAD'),
        '1.35': ('0.00 CAD', '8800.00 CAD'),
        '1.4': ('200.00 CAD', '9000.00 CAD'),
        '1.45': ('400.00 CAD', '9200.00 CAD'),
        '1.5': ('600.00 CAD', '9400.00 CAD'),
    }

    def _pages(self, tmp_path):
        """The one book drawn at each of the six prices.

        Built once, and priced for each run by a rates file rather than by the
        book's own prices — `--fx-rates` adds a price for the run only, so the
        book is left as it is between them.
        """
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        bought = _run(runner, 'import', '--new', str(book), FOUR_RATES)
        assert bought.exit_code == 0, bought.output
        pages = {}
        for price in self.PRICED:
            rates = tmp_path / f'rates-{price}.yaml'
            rates.write_text(f'USD: {price}\n', encoding='utf-8')
            sheet = _run(runner, 'balance-sheet', str(book), '--as-of', YEAR_END,
                         '--fx-rates', str(rates))
            assert sheet.exit_code == 0, sheet.output
            pages[price] = sheet.output
        return pages

    def test_the_gain_is_measured_against_all_four_cost_bases(self, tmp_path):
        pages = self._pages(tmp_path)

        for price, (gain, _assets) in self.PRICED.items():
            page = pages[price]
            assert block_total_of(page, 'unrealized_gains_assets_fx') == Fraction(
                gain.split()[0]), (price, page)
            assert key_of(page, 'unrealized_gains_fx') == gain, (price, page)
            assert key_of(page, 'total_unrealized_gains') == gain, (price, page)

    def test_the_average_of_the_four_rates_states_a_gain_of_nothing(self, tmp_path):
        """5,400.00 for 4,000.00 dollars is 1.35, so at 1.35 the figure is 0.00.

        A zero the book has, not an absent one: the key is written because the
        book holds the money, whatever the money has done.
        """
        page = self._pages(tmp_path)['1.35']

        assert key_of(page, 'unrealized_gains_fx') == '0.00 CAD'
        assert key_of(page, 'total_unrealized_gains') == '0.00 CAD'

    def test_nothing_is_realized_at_any_price(self, tmp_path):
        """No dollar has left, so no price makes any of it realized."""
        pages = self._pages(tmp_path)

        for price in self.PRICED:
            assert block_total_of(pages[price], 'realized_gains_fx') == 0, price
            assert key_of(pages[price], 'total_realized_gains') == '0.00 CAD', price
            assert key_of(pages[price], 'unrealized_gains_liabilities_fx') == '0.00 CAD', price

    def test_the_canadian_spending_moves_the_total_and_no_gain(self, tmp_path):
        """3,400.00 left in the Canadian bank, and 4,000.00 USD at the price.

        10,000.00 opening less 5,400.00 spent on dollars and 1,200.00 of rent.
        The rent is in every one of these totals and in none of the gains.
        """
        pages = self._pages(tmp_path)

        for price, (_gain, assets) in self.PRICED.items():
            page = pages[price]
            assert key_of(page, 'total_assets') == assets, (price, page)
            assert key_of(page, 'total_liabilities_and_equity') == assets, (price, page)


class TestUsdBoughtAndHeld:
    """1,000.00 USD bought at 1.30 and not spent, priced at 1.45 at the year end.

    The whole 150.00 is unrealized and nothing is realized, which is the plain
    case — and it is the one where GnuCash's own Advanced Portfolio report
    computes the same figure from arithmetic this shares no code with: Basis
    C$1,300.00, Value C$1,450.00, Unrealized Gain C$150.00
    (`tests/research/what_gnucash_computes_as_a_securitys_realized_gain_probe.py`).
    A disposal valued at what the units cost is the whole of what separates the
    two computations, and this book has disposed of nothing.
    """

    def _page(self, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        bought = _run(runner, 'import', '--new', str(book), EARNED_NOTHING_SPENT)
        assert bought.exit_code == 0, bought.output
        sheet = _run(runner, 'balance-sheet', str(book), '--as-of', YEAR_END)
        assert sheet.exit_code == 0, sheet.output
        return sheet.output

    def test_the_whole_movement_is_unrealized_and_none_of_it_realized(self, tmp_path):
        page = self._page(tmp_path)

        assert block_total_of(page, 'realized_gains_fx') == 0
        assert key_of(page, 'total_realized_gains') == '0.00 CAD'
        assert block_total_of(page, 'unrealized_gains_assets_fx') == 150
        assert key_of(page, 'unrealized_gains_liabilities_fx') == '0.00 CAD'
        assert key_of(page, 'unrealized_gains_fx') == '150.00 CAD'
        assert key_of(page, 'total_unrealized_gains') == '150.00 CAD'

    def test_the_sheet_balances(self, tmp_path):
        page = self._page(tmp_path)

        assert key_of(page, 'total_assets') == '5150.00 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '5150.00 CAD'


class TestUsdEarnedThreeTimesAndSpentOutInFour:
    """Four disposals against three cost bases, ending with no dollars at all.

    The other books here have one cost basis between them, so a realized figure
    that summed wrongly across bases would still pass. This one earns US
    dollars three times at 1.30, 1.35 and 1.40, and spends every dollar in four
    payments at 1.45, 1.50, 1.38 and 1.42:

        600.00 from the 1.30 basis     780.00 cost     870.00 fetched     90.00
        400.00 from the 1.30 basis     520.00 cost     600.00 fetched     80.00
      2,000.00 from the 1.35 basis   2,700.00 cost   2,760.00 fetched     60.00
      1,000.00 from the 1.40 basis   1,400.00 cost   1,420.00 fetched     20.00
                                                                        250.00

    The first basis is drawn on twice and emptied by the second of them, so the
    figure has to sum across disposals as well as across cost bases.
    """

    def _page(self, tmp_path):
        runner = CliRunner()
        book = tmp_path / 'book.gnucash'
        earned = _run(runner, 'import', '--new', str(book), EARNED)
        assert earned.exit_code == 0, earned.output
        listing = _run(runner, 'fx-balances', str(book))
        assert listing.exit_code == 0, listing.output
        with open(SPENT_IN_FOUR, encoding='utf-8') as source:
            filled = source.read()
        for placeholder, opened in (('{basis_at_130}', '2026-02-01'),
                                    ('{basis_at_135}', '2026-04-01'),
                                    ('{basis_at_140}', '2026-06-01')):
            filled = filled.replace(placeholder,
                                    _basis_opened_on(listing.output, opened))
        ledger = tmp_path / 'spend.txt'
        ledger.write_text(filled, encoding='utf-8')
        spent = _run(runner, 'import', str(book), str(ledger))
        assert spent.exit_code == 0, spent.output
        sheet = _run(runner, 'balance-sheet', str(book), '--as-of', YEAR_END)
        assert sheet.exit_code == 0, sheet.output
        return sheet.output

    def test_the_realized_figure_sums_across_every_disposal_and_cost_basis(self, tmp_path):
        page = self._page(tmp_path)

        assert block_total_of(page, 'realized_gains_fx') == 250
        assert key_of(page, 'total_realized_gains') == '250.00 CAD'

    def test_nothing_is_unrealized_though_the_year_end_price_is_higher(self, tmp_path):
        """The book prices US dollars at 1.50 that day.

        That would be a large gain on anything still held, so a figure taken
        from the price rather than from what the book holds would show here.
        """
        page = self._page(tmp_path)

        assert block_total_of(page, 'unrealized_gains_assets_fx') == 0
        assert key_of(page, 'unrealized_gains_liabilities_fx') == '0.00 CAD'
        assert key_of(page, 'unrealized_gains_fx') == '0.00 CAD'
        assert key_of(page, 'total_unrealized_gains') == '0.00 CAD'

    def test_the_sheet_balances_with_every_dollar_gone(self, tmp_path):
        """5,400.00 of revenue and 250.00 of gain against 5,650.00 of expense,
        so the opening capital is all that is left."""
        page = self._page(tmp_path)

        assert key_of(page, 'total_assets') == '5000.00 CAD'
        assert key_of(page, 'total_liabilities_and_equity') == '5000.00 CAD'


class TestAGainRealizedAfterTheSheetIsDrawn:
    """A sheet states what the book had realized by the day it is drawn.

    The book collects 2,720.00 USD on 2026-08-13 and sends the whole balance
    out on 2026-08-17, realizing 19.86 CAD of loss that day. Drawn between the
    two, the sheet must state none of it: every dollar is still held, so the
    difference is unrealized and the disposal has not happened yet.

    Every other book here is drawn at a year end, where each disposal is
    already behind the date — so a figure that read every marked split in the
    book and never looked at its date would pass all of them and be wrong on
    any sheet drawn mid-year.
    """

    BEFORE_THE_DISPOSAL = '2026-08-15'

    def _page(self, tmp_path):
        runner = CliRunner()
        book = _collected(runner, tmp_path)
        _spend(runner, tmp_path, book, SPENT)
        result = _run(runner, 'balance-sheet', str(book),
                      '--as-of', self.BEFORE_THE_DISPOSAL, '--fx-rates', RATES)
        assert result.exit_code == 0, result.output
        return result.output

    def test_a_disposal_after_the_date_realizes_nothing_on_this_sheet(self, tmp_path):
        page = self._page(tmp_path)

        assert block_total_of(page, 'realized_gains_fx') == 0
        assert key_of(page, 'total_realized_gains') == '0.00 CAD'

    def test_the_working_lists_that_disposal_no_more_than_the_key_counts_it(self, tmp_path):
        """The key and its items have to agree.

        A total of nothing itemized as a list of gains is worse than either,
        because the reader cannot reconcile the two and has no way to tell
        which of them the sheet means. So the key says it found no split,
        rather than carrying an August disposal this sheet's date is before.
        """
        page = self._page(tmp_path)

        block = block_of(page, 'realized_gains_fx')
        assert '\t\tsplits: # there is no split' in block.splitlines(), block
        assert 'Income:FX Gain' not in block, block
