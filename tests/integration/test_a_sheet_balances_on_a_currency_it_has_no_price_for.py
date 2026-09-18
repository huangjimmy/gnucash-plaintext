"""A currency the book holds no price for keeps GnuCash's own revaluation.

A cost basis says what currency cost; it does not say what that currency is
worth now, and for that the book needs a price. Where it has none, measuring
the gain from the cost bases is not possible, so the currency has to fall to
GnuCash's revaluation like any other the cost bases cannot speak for.

Claiming it regardless took the account out of the fallback set while the
revaluation skipped the basis for want of a price, so the currency contributed
nothing anywhere. Measured on 1,000.00 HKD bought for 180.00 CAD with no HKD
price: GnuCash values the account at zero, so assets came to 820.00 while
equity stayed at 1,000.00 — a balance sheet 180.00 out on its face, on GnuCash
3.4 and 3.8. On 4.4 and later the same lookup answers 0 rather than #f, which
happened to balance, so the defect showed on the two oldest builds alone.

Drawn on any supported build the figure is now the same and the sheet balances.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import key_of

LEDGER = 'tests/fixtures/a_cad_book_holding_hkd_the_book_has_no_price_for.txt'
AS_OF = '2026-12-31'


def _page(tmp_path):
    """1,000.00 HKD bought for 180.00 CAD, and no HKD price in the book."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), LEDGER)
    assert made.exit_code == 0, made.output
    sheet = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF)
    assert sheet.exit_code == 0, sheet.output
    return sheet.output


def test_the_sheet_balances(tmp_path):
    page = _page(tmp_path)

    assert key_of(page, 'total_assets') == key_of(
        page, 'total_liabilities_and_equity')


def test_the_unpriced_currency_is_stated_at_gnucashs_own_figure(tmp_path):
    """GnuCash values the account at nothing, so the whole cost is the loss."""
    page = _page(tmp_path)

    assert key_of(page, 'total_assets') == '820.00 CAD'
    assert key_of(page, 'unrealized_gains_fx') == '-180.00 CAD'
    assert key_of(page, 'total_unrealized_gains') == '-180.00 CAD'
