"""Itemizing shows how a figure was reached. It never changes the figure.

`--itemize` is on by default and puts, under each key that states a gain, the
items that key is made of. `--no-itemize` leaves the key stating the same
figure on its own. **The two have to agree**, on every key and every book: the
items exist so a reader can add a total up and check it, and a block whose
total differs from the key it sits under proves nothing about that key — it is
a second opinion wearing the key's name.

This is the test that catches a block computed its own way rather than from
what the figure is actually made of. Two such were found by it:

- `gnucash_balancing_amount` grouped by the currency each split's value is
  stated in. GnuCash's own figure merges account balances, keyed by each
  account's own commodity, and subtracts split values, keyed by the
  transaction's currency — so it spans the union, and every commodity no split
  was valued in went missing. A book that borrowed 1,000.00 USD stated 1300.00
  under a key whose figure is -100.00.
- `unrealized_gains_assets_fx` valued every cost basis at the sheet's price and
  ignored the fallback to GnuCash's revaluation that the key itself uses, so a
  book whose cost bases do not account for what it holds stated 1300.00 in the
  block above a line reading `unrealized_gains_fx: 940.00 CAD #
  unrealized_gains_assets_fx + unrealized_gains_liabilities_fx`.

Nothing here asserts a particular amount. Each book's figures are whatever its
prices and cost bases come to; what is asserted is that one page states one
figure per key.
"""

from fractions import Fraction

import pytest
from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import block_total_of, key_of

# Every itemized key, and books that exercise each of them: cost bases at
# several rates, a currency that falls back to GnuCash's revaluation, disposals
# that realize a difference, securities, and a book that owes a currency.
ITEMIZED = ('unrealized_gains_assets_fx', 'realized_gains_fx',
            'unrealized_gains_other', 'gnucash_balancing_amount')

BOOKS = (
    ('a_cad_book_that_bought_usd_at_four_rates_and_spends_only_cad.txt', '2026-12-31'),
    ('a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt', '2026-12-31'),
    ('a_cad_book_that_borrowed_usd_into_its_cad_bank.txt', '2026-01-25'),
    ('a_cad_book_holding_us_listed_shares.txt', '2026-12-31'),
    ('a_cad_book_holding_one_security_in_two_accounts.txt', '2026-12-31'),
    ('a_cad_book_earning_usd_three_times.txt', '2026-12-31'),
    # Two cost bases of one commodity that round apart: 1.00 USD twice at
    # 1.3833 is 1.38 each, where the 2.00 USD converts once to 2.77. Summed a
    # basis at a time the key came to 0.16 against a block and a `total_assets`
    # of 0.17, and the sheet stated 100.17 of assets against 100.16 of
    # liabilities and equity.
    ('a_cad_book_with_two_cost_bases_that_round_apart.txt', '2026-12-31'),
)


def _pages(tmp_path, ledger, as_of):
    """The same book drawn both ways, so the only difference is the flag.

    Every price source these statements accept reads the book's price database
    — `pricedb-nearest`, `pricedb-latest`, `pricedb-before` — and GnuCash
    rounds each conversion on that path, which is what lets a group's
    `balance_sheet_value` and the rounded key agree. GnuCash's averaging
    sources build a rate from the book's own transactions through another path
    that need not round the same way, and they are refused by name rather than
    drawn: `test_a_rates_file_prices_gnucash_reports_for_the_run_only.py` holds
    that refusal. So there is no source reachable here for which these totals
    could come apart.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), f'tests/fixtures/{ledger}')
    assert made.exit_code == 0, made.output

    itemized = _run(runner, 'balance-sheet', str(book), '--as-of', as_of)
    assert itemized.exit_code == 0, itemized.output

    plain = _run(runner, 'balance-sheet', str(book), '--as-of', as_of, '--no-itemize')
    assert plain.exit_code == 0, plain.output
    return itemized.output, plain.output


def _stated(page, key):
    """What a key states on the page that does not itemize, as a Fraction."""
    said = key_of(page, key)
    assert said is not None, (key, page)
    return Fraction(said.split(' ')[0])


@pytest.mark.parametrize('ledger,as_of', BOOKS, ids=[book for book, _ in BOOKS])
def test_every_itemized_total_is_what_the_key_states_without_items(tmp_path, ledger, as_of):
    """One page, one figure per key, whichever way it is drawn."""
    itemized, plain = _pages(tmp_path, ledger, as_of)

    for key in ITEMIZED:
        assert block_total_of(itemized, key) == _stated(plain, key), (
            f'{key} on {ledger}: itemized block totals '
            f'{block_total_of(itemized, key)}, the key states {_stated(plain, key)}')


@pytest.mark.parametrize('ledger,as_of', BOOKS, ids=[book for book, _ in BOOKS])
def test_the_page_states_the_addition_it_prints(tmp_path, ledger, as_of):
    """`unrealized_gains_fx` says it is the two sides added, so it has to be.

    The comment on that line states an addition. With the assets side itemized
    and the owed side not, a reader adds the block's total to the figure beside
    it and must arrive at the third — which is the arithmetic the page asserts
    about itself.
    """
    itemized, _plain = _pages(tmp_path, ledger, as_of)

    assets = block_total_of(itemized, 'unrealized_gains_assets_fx')
    owed = Fraction(key_of(itemized, 'unrealized_gains_liabilities_fx').split(' ')[0])
    total = Fraction(key_of(itemized, 'unrealized_gains_fx').split(' ')[0])

    assert assets + owed == total, (
        f'{ledger}: the page prints {assets} + {owed} and calls it {total}')
