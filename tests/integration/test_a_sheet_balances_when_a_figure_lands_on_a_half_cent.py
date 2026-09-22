"""A balance sheet balances when a figure lands exactly on a half cent.

Two sides of the page are worked out by different hands. An account line and
`total_assets` are GnuCash's own conversion, which uses `GNC-RND-ROUND` —
banker's rounding, a tie going to the nearest even. The gain measured from the
book's own cost bases is this report's arithmetic, and it reaches `total_equity`.

Where a figure lands exactly on a half cent the two rules part: 1,000.00 USD at
1.386465 is 1386.465, which GnuCash makes 1386.46 and half-up makes 1386.47. A
cent then separates the two sides of a sheet that must balance — on the
simplest book the feature covers, currency bought with the book's own money and
nothing spent since.

Nothing else in the suite reaches it: every other fixture's figures either
divide exactly or round the same way under both rules, so the assertion that
the page balances has never been able to fail on this account.
"""

from fractions import Fraction

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import key_of, totals_of, under

BOUGHT = 'tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt'
HALF_CENT = 'tests/fixtures/usd_at_a_rate_that_lands_on_a_half_cent.yaml'
AS_OF = '2026-12-31'


def _page(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), BOUGHT)
    assert made.exit_code == 0, made.output

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF,
                 '--fx-rates', HALF_CENT)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def test_the_sheet_balances(tmp_path):
    """The one thing that must hold whichever way a tie is rounded."""
    page = _page(tmp_path)

    assert key_of(page, 'total_assets') == key_of(
        page, 'total_liabilities_and_equity'), page


def test_the_working_agrees_with_the_account_line(tmp_path):
    """What the gain is measured against is what the page says the money is worth.

    A holding's `value:` is GnuCash's conversion of it. The working states the
    same holding's worth, and a reader holding the two side by side is entitled
    to find one figure.
    """
    page = _page(tmp_path)

    # What GnuCash converted the holding to, on the account's own line.
    valued = Fraction(under(page, 'Assets:USD Bank')['value'])
    # What the gain was measured against: the cost bases' balance at the
    # sheet's price, which is the same holding at the same price.
    assert totals_of(page, 'unrealized_gains_assets_fx')['value'] == valued, page
