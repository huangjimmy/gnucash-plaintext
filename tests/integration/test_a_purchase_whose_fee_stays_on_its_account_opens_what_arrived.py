"""A purchase whose fee is taken off on the same account opens a cost basis for what the account kept.

100.00 USD bought and 1.00 kept back by the bank, both on one account, is 99.00
USD arriving: nothing moved and nothing was spent from what the book held
before. The cost basis opens for 99.00, so it holds what the account holds.
Opened for the arriving split's 100.00, it offered a dollar the book never had,
which `--verify-integrity` then reported and `import` had accepted at exit 0.

`tests/fixtures/usd_bought_with_the_bank_keeping_part_as_its_fee_on_the_same_account.txt`.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.integration.text_report_pages import book_from

LEDGER = 'usd_bought_with_the_bank_keeping_part_as_its_fee_on_the_same_account.txt'


def test_the_cost_basis_holds_what_the_account_holds(tmp_path):
    """99.00, 30.00 and 99.00.

    The second purchase's fee is taken off once, not once per split; the
    third's 70.00 is more than its first split brought, and the rest comes off
    the second.
    """
    listing = CliRunner().invoke(
        cli, ['fx-balances', str(book_from(tmp_path, LEDGER))]).output

    assert '1.35 CAD/USD' in listing, listing
    assert 'Total USD cost basis balance: 228.00 USD' in listing, listing
    assert 'Total USD held in accounts: 228.00 USD' in listing, listing
