"""A purchase whose fee is taken off on the same account, the fee drawing on the purchase, leaves a cost basis holding what the account holds.

100.00 USD bought and 1.00 kept back by the bank, both on one account: the
purchase opens a cost basis for the 100.00 and the fee, stating the purchase's
position in the file, draws 1.00 of it, so 99.00 is left and the cost basis
holds what the account holds. A fee stating no cost basis is refused, with the
ways to write it (Q-050): netted with the purchase in silence, it spent
dollars without saying from where.

`tests/fixtures/usd_bought_with_the_bank_keeping_part_as_its_fee_drawn_on_the_purchase.txt`.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.integration.text_report_pages import book_from

LEDGER = 'usd_bought_with_the_bank_keeping_part_as_its_fee_drawn_on_the_purchase.txt'


def test_the_cost_basis_holds_what_the_account_holds(tmp_path):
    """99.00, 99.00 and 30.00.

    The second purchase's fee draws on one of its two splits; the third's 70.00
    is more than its first split brought, so it is written as two splits, each
    drawing on one.
    """
    listing = CliRunner().invoke(
        cli, ['fx-balances', str(book_from(tmp_path, LEDGER))]).output

    assert '1.35 CAD/USD' in listing, listing
    assert 'Total USD cost basis balance: 228.00 USD' in listing, listing
    assert 'Total USD held in accounts: 228.00 USD' in listing, listing
