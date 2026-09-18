"""A book holding a currency it has no price for balances on every build.

`price-of-commodity` answers `#f` on GnuCash 3.4 and 3.8 where the book holds
no price for a currency, and `0` from 4.4 on — and `0` is true in Scheme
(CLAUDE.md §"price-of-commodity"). So the same book can take two different
paths through the report depending on which GnuCash draws it, and the sheet
can come out balanced on one and short on the other.

Which way it goes depends on how the currency arrived, and the two cases pull
against each other:

- **bought with the book's own money.** GnuCash reconstructs its cost from the
  sum of the account's split values, which are in the book's currency, so its
  revaluation is right and falling back to it costs nothing.
- **arrived in its own currency**, as a US dollar invoice collected into a US
  dollar bank does. No split carries a figure in the book's currency, so
  GnuCash's revaluation is 0 — and falling back to it drops the whole cost.

Both are drawn here, on every supported build, and asserted on the one thing
that must hold either way: a balance sheet balances. Nothing else in the suite
draws foreign-transaction currency with no price, which is how a build-specific
hole stayed open — the figures differ by build and by book, but this does not.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import key_of

ARRIVED_IN_ITS_OWN_CURRENCY = 'tests/fixtures/a_usd_invoice_collected_into_a_usd_bank.txt'
RATES = 'tests/fixtures/usd_at_the_invoice_rate_then_lower_at_the_year_end.yaml'
BOUGHT_WITH_CANADIAN_MONEY = ('tests/fixtures/'
                              'a_cad_book_holding_hkd_the_book_has_no_price_for.txt')
AS_OF = '2026-12-31'


def _drawn(tmp_path, ledger, *extra):
    """Import `ledger`, then draw a sheet with no rates file of its own.

    `--fx-rates` prices a run and is never written to the book (CLAUDE.md §28),
    so a book imported with one still holds no price of its own afterwards —
    which is the state under test.
    """
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), ledger, *extra)
    assert made.exit_code == 0, made.output

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def _balances(page):
    return key_of(page, 'total_assets') == key_of(page, 'total_liabilities_and_equity')


def test_a_currency_that_arrived_in_its_own_currency(tmp_path):
    """The case GnuCash's own revaluation cannot measure: it answers 0."""
    page = _drawn(tmp_path, ARRIVED_IN_ITS_OWN_CURRENCY,
                  '--include-business-objects', '--fx-rates', RATES)

    assert _balances(page), page


def test_a_currency_bought_with_the_books_own_money(tmp_path):
    """The case GnuCash's revaluation measures correctly, kept working."""
    page = _drawn(tmp_path, BOUGHT_WITH_CANADIAN_MONEY)

    assert _balances(page), page
