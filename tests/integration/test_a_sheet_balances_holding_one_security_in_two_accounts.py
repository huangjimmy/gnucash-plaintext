"""A balance sheet balances when one security sits in two accounts.

GnuCash converts a commodity's whole holding once: two accounts holding one
unit each of something worth 10.005 CAD come to 20.01 in `total_assets`. The
gain this page states for them is added up account by account, each rounded to
money on its own, which comes to 10.01 twice — 20.02.

A cent then separates the two sides of a sheet that must balance, and the book
that shows it holds no foreign currency and opens no cost basis at all: a share
is counted in units and priced rather than converted, so it keeps GnuCash's own
revaluation whatever this change does. Two brokerage accounts holding one stock
is an ordinary thing for a company to have.

Adding the revaluation up per account is deliberate — it is what lets the
working beneath a key add up to the key — so what this asserts is the invariant
that has to survive that choice, rather than any particular figure.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import key_of

TWO_BROKERS = 'tests/fixtures/a_cad_book_holding_one_security_in_two_accounts.txt'
AS_OF = '2026-12-31'


def _page(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), TWO_BROKERS)
    assert made.exit_code == 0, made.output

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def test_the_sheet_balances(tmp_path):
    """Whichever way the holdings are added up, the two sides must agree."""
    page = _page(tmp_path)

    assert key_of(page, 'total_assets') == key_of(
        page, 'total_liabilities_and_equity'), page


def test_the_working_states_the_holding_not_the_accounts(tmp_path):
    """One line for the commodity, because that is what the figure is of.

    GnuCash revalues a holding, not an account: it takes the whole quantity
    through the price once. A line printing an account path therefore said
    something untrue about its own figure — it stated a slice nobody computed,
    rounded on its own, and two such lines here came to 0.00 apiece where
    GnuCash made the pair 0.01.

    The working-sums test cannot see this: it reads each line and adds the
    figures up, and a line printing an account path parses exactly as one
    printing a commodity's mnemonic. What was missing was an assertion about
    what a line is *of*, rather than what it adds to.
    """
    page = _page(tmp_path)
    working = [line.strip() for line in page.splitlines()
               if line.lstrip().startswith('#   ')]

    assert '#   XYZ 0.01 CAD' in working, working
    assert not [line for line in working if 'Broker' in line], working


def test_the_gain_is_what_gnucash_makes_of_the_holding(tmp_path):
    """One commodity, one conversion — not one conversion per account.

    `gnucash_balancing_amount` is GnuCash's own figure for the same book, so
    where every gain on the page is GnuCash's revaluation the two agree.
    """
    page = _page(tmp_path)

    assert key_of(page, 'unrealized_gains_other') == key_of(
        page, 'gnucash_balancing_amount'), page
