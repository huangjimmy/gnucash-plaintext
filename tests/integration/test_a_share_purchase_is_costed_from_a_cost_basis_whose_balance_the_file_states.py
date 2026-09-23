"""A purchase costs its shares from the dollars it spent, whether or not the file states their cost basis's balance.

`tests/fixtures/shares_bought_from_dollars_whose_cost_basis_states_its_balance.txt`
is the book of `shares_bought_in_a_transaction_stating_no_canadian_figure.txt`
with `cost_basis_balance:` written on the dollars bought, as every export writes
it. A stated balance is already net of the purchase, so the purchase does not
lower it. It still spends 2,200.00 dollars that cost 1.30, and that cost goes
onto the shares.

Before, the cost went with the dollars only when the purchase lowered their
balance, so a book exported and imported again, or written with its balances,
held its shares at no cost: the sheet converted their US dollar figure at its
own rate, and a sale that gave the shares' guid was refused as drawing on a
split that is no cost basis.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run
from tests.integration.text_report_pages import book_from, key_of

LEDGER = 'shares_bought_from_dollars_whose_cost_basis_states_its_balance.txt'


def test_each_holding_is_costed_at_its_own_share_of_the_dollars(tmp_path):
    """52.00 a share and 26.00 a share, as when the balance is not stated."""
    listing = CliRunner().invoke(
        cli, ['fx-balances', str(book_from(tmp_path, LEDGER))]).output

    assert '52 CAD/USD_TECH' in listing, listing
    assert '26 CAD/USD_CORP' in listing, listing


def test_the_stated_balance_is_not_lowered_a_second_time(tmp_path):
    """7,800.00 stated on the dollars bought, and 1,100.00 back from the sale."""
    listing = CliRunner().invoke(
        cli, ['fx-balances', str(book_from(tmp_path, LEDGER))]).output

    assert 'Total USD cost basis balance: 8,900.00 USD' in listing, listing
    assert 'Total USD held in accounts: 8,900.00 USD' in listing, listing


def test_the_sale_realizes_its_gain_against_the_carried_cost(tmp_path):
    """20 shares costing 52.00 fetched 1,320.00 CAD, so 280.00 is realized, and the page balances."""
    drawn = _run(CliRunner(), 'balance-sheet', str(book_from(tmp_path, LEDGER)),
                 '--as-of', '2029-12-31', '--no-itemize')
    assert drawn.exit_code == 0, drawn.output

    assert key_of(drawn.output, 'realized_gains_other') == '280.00 CAD'
    assert key_of(drawn.output, 'total_assets') == '14900.00 CAD'
    assert key_of(drawn.output, 'total_liabilities_and_equity') == '14900.00 CAD'
