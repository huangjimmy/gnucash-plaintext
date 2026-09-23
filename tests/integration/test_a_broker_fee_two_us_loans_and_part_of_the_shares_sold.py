"""A broker fee, two US loans, and part of a holding sold to repay them.

Every mechanism Q-045 and Q-046 put in, on one book, with the share rising 60%
while the US dollar falls from 1.40 to 1.10 and comes back to 1.20:

* the cost of spent dollars travels onto what they bought, and **divides the
  way the dollars divided** — 990.00 USD to the shares and 1.00 USD to the
  broker, both at the 1.30 those dollars cost;
* a share sale draws the shares' cost basis down and realizes the difference,
  which is `realized_gains_other`;
* repaying a foreign loan draws the debt's cost basis down and realizes the
  difference, which is `realized_gains_fx`;
* what the cost bases hold is what the accounts hold, currency and shares
  alike.

**The broker fee expense account is kept in Canadian dollars**, and that is the point of
having the fee here at all. The broker charged 1.00 USD; the dollars that paid
it cost 1.30 CAD; so the expense is 1.30 CAD, recorded on the day and never
changed again. Kept in US dollars the account holds 1.00 USD, and the income
statement converts that balance at whatever the sheet's rate is — 1.20 at this
year end — which revalues an expense months after it was incurred and leaves
the page 0.10 short of balancing.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run
from tests.integration.text_report_pages import key_of

LEDGER = 'tests/fixtures/a_broker_fee_two_us_loans_and_part_of_the_shares_sold.txt'


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    assert made.exit_code == 0, made.output
    assert 'Errors:       0' in made.output, made.output
    return book


def _sheet(book):
    drawn = _run(CliRunner(), 'balance-sheet', str(book),
                 '--as-of', '2028-12-31', '--no-itemize')
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


def test_the_fee_takes_its_own_share_of_what_the_dollars_cost(tmp_path):
    """990.00 USD to the shares at 1.30 is 128.70 a share, not 128.83."""
    listing = CliRunner().invoke(cli, ['fx-balances', str(_book(tmp_path))]).output

    assert '128.7 CAD/USD_CORP' in listing, listing


def test_the_cost_bases_hold_what_the_accounts_hold(tmp_path):
    """Currency and shares alike, which is the invariant the whole of this rests on."""
    listing = CliRunner().invoke(cli, ['fx-balances', str(_book(tmp_path))]).output

    assert 'Total USD cost basis balance: 87.80 USD' in listing, listing
    assert 'Total USD held in accounts: 87.80 USD' in listing, listing
    assert 'Total USD_CORP cost basis balance: 3.0000 USD_CORP' in listing, listing
    assert 'Total USD_CORP held in accounts: 3.0000 USD_CORP' in listing, listing


def test_the_gain_on_the_shares_is_stated_apart_from_the_gain_on_the_currency(tmp_path):
    """Two figures a return asks for separately, so the page keeps them apart.

    The shares cost 900.90 CAD — 7 at 128.70 — and fetched 1,108.80 USD at the
    1.20 of the day, which is 1,330.56, so 429.66 is realized on them. The
    first loan cost 1,300.00 and was settled with dollars costing 1,100.00, a
    gain of 200.00; the second cost 1,111.00 and was settled with dollars
    costing 1,212.00, a loss of 101.00. The currency figure is the 99.00
    between them.
    """
    page = _sheet(_book(tmp_path))

    assert key_of(page, 'realized_gains_other') == '429.66 CAD'
    assert key_of(page, 'realized_gains_fx') == '99.00 CAD'
    assert key_of(page, 'total_realized_gains') == '528.66 CAD'


def test_naming_the_exchange_gain_account_leaves_the_gain_on_the_shares_alone(tmp_path):
    """`--fx-gain-account` says where exchange differences are booked, and nothing else.

    The share sale's 429.66 sits on `Income:Realized Gains`, which is not the
    account named, and it is still a gain on shares.
    """
    drawn = _run(CliRunner(), 'balance-sheet', str(_book(tmp_path)),
                 '--as-of', '2028-12-31', '--no-itemize',
                 '--fx-gain-account', 'Income:FX Gain')
    assert drawn.exit_code == 0, drawn.output

    assert key_of(drawn.output, 'realized_gains_other') == '429.66 CAD'
    assert key_of(drawn.output, 'realized_gains_fx') == '99.00 CAD'


def test_the_page_balances(tmp_path):
    """Which is the whole of it: every figure above is measured, and they add up.

    `tests/research/which_transaction_stops_a_balance_sheet_balancing_probe.py`
    draws this book after each of its seven transactions, and the two totals
    are equal at every one of them.
    """
    page = _sheet(_book(tmp_path))

    assert key_of(page, 'total_assets') == '20675.60 CAD'
    assert key_of(page, 'total_liabilities_and_equity') == '20675.60 CAD'
