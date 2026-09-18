"""A payment block's realized difference reaches `realized_gains_fx`.

The commonest realized exchange difference this tool writes is not a
hand-written disposal at all: it is a settlement. A US dollar invoice is posted
at one rate and paid at another, the payment block's `$residual$` line takes
the difference, and the import marks that split.

That mark is written in `_book_payment_fx_difference`, the only place outside
the transaction create path that writes one, and it counts only because the
settling split carries `cost_basis_split_guid` and the entry is restated in the
book's own currency. Both are conditions of the reader, and neither is obvious
from the payment block a person writes.

Every other test of these keys draws its gain from a hand-written transaction,
or from a settlement in the record's own currency, which realizes nothing. So
if either condition changed, the figure would drop to 0.00 with nothing to
notice — on the shape a reader is most likely to have.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import key_of

SETTLED = 'tests/fixtures/fx_invoice_usd_paid_from_cad_bank.txt'
RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'
AS_OF = '2026-12-31'


def _page(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), SETTLED,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0, made.output

    drawn = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def test_the_settlement_difference_is_realized(tmp_path):
    """100.00 USD booked at 1.40 and settled for 137.00 CAD: a 3.00 loss."""
    page = _page(tmp_path)

    assert key_of(page, 'realized_gains_fx') == '-3.00 CAD'
    assert key_of(page, 'total_realized_gains') == '-3.00 CAD'


def test_the_working_lists_the_settlement(tmp_path):
    """A gain counted without its working would be a gain taken on trust."""
    page = _page(tmp_path)

    listed = [line.strip() for line in page.splitlines()
              if line.lstrip().startswith('#   ') and 'FX Gain' in line]
    assert len(listed) == 1, page
    assert listed[0].endswith('-3.00 CAD'), listed
