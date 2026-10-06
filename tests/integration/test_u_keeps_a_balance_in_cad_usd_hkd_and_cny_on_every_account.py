"""U keeps a balance in CAD, USD, HKD and CNY on every account (Q-057).

The author's case, written in the "Scenarios" section of
`docs/issues/Q-057-keep-each-accounts-balance-in-every-currency-the-book-supports.md`.
U's base currency is CAD, and U selects USD, HKD, CAD and CNY, with
`currency_balances: "CAD USD HKD CNY"` in the `company` block.

Step 1, `tests/fixtures/u_1_holds_100_usd_that_is_130_cad_780_hkd_and_600_cny.txt`,
opens USD_A, USD_A1, CAD_B, HKD_C and CNY_D, and puts 100.00 USD in USD_A on
2030-01-02, when the book's prices are 1.30 CAD/USD, 7.80 HKD/USD and 6.00
CNY/USD. USD_A holds 100.00 USD, and also stores 130.00 CAD, 780.00 HKD and
600.00 CNY.

`u_2_transfers_10_usd_from_usd_a_to_usd_a1.txt` moves 10.00 USD from USD_A to
USD_A1. The transfer moves 10.00 USD, 13.00 CAD, 78.00 HKD and 60.00 CNY.
USD_A then holds 90.00 USD, 117.00 CAD, 702.00 HKD and 540.00 CNY, and
USD_A1 holds 10.00 USD, 13.00 CAD, 78.00 HKD and 60.00 CNY.

`u_2_transfers_10_usd_from_usd_a_to_cad_b_at_1_40_cad_per_usd.txt` moves the
10.00 USD to CAD_B instead, on a day when the prices are 1.40 CAD/USD, 7.85
HKD/USD and 6.50 CNY/USD. USD_A gives up 10.00 USD, 13.00 CAD, 78.00 HKD and
60.00 CNY. CAD_B receives 14.00 CAD, and with it 10.00 USD, 78.50 HKD and
65.00 CNY. The 1.00 CAD, 0.50 HKD and 5.00 CNY between them are realized
gains. They are recorded in the CAD income account as 1.00 CAD, and that
account also stores 0.50 HKD and 5.00 CNY.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')
HOLDS_100_USD = 'u_1_holds_100_usd_that_is_130_cad_780_hkd_and_600_cny'
TO_USD_A1 = 'u_2_transfers_10_usd_from_usd_a_to_usd_a1'
TO_CAD_B = 'u_2_transfers_10_usd_from_usd_a_to_cad_b_at_1_40_cad_per_usd'


def _book(tmp_path, *steps):
    book = tmp_path / 'book.gnucash'
    for number, step in enumerate(steps):
        args = ['import', str(book), str(FIXTURES / f'{step}.txt')]
        if number == 0:
            args.insert(1, '--new')
        done = _run(CliRunner(), *args)
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return book


def _balances(book):
    """What `fx-balances` lists for each account: its balance in each selected currency."""
    listing = _run(CliRunner(), 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    return dict(line.split(': ', 1) for line in listing.output.splitlines()[1:])


def _splits(book, tmp_path, description):
    """Each split of one exported transaction: its account and amount, and the amounts stored on it."""
    out = tmp_path / 'exported.txt'
    done = _run(CliRunner(), 'export', str(book), str(out))
    assert done.exit_code == 0, done.output
    block = re.search(rf'^\d{{4}}-\d\d-\d\d \* "{re.escape(description)}".*\n((?:\t.*\n)*)',
                      out.read_text(), re.M).group(1)
    found = {}
    account = None
    for line in block.splitlines():
        if line.startswith('\t\t') and 'currency_amount.' in line:
            key, value = line.strip().split(': ')
            found[account][key.split('.')[1]] = value.strip('"')
        elif line.startswith('\t') and not line.startswith('\t\t') and not line.split()[0].endswith(':'):
            account = line.strip().rsplit(' ', 2)[0]
            found[account] = {}
    return found


def _sheet(book, currency):
    """The balance sheet as of 2030-02-01 in `currency`: its account lines and the keys a line states once."""
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2030-02-01',
                '--currency', currency)
    assert page.exit_code == 0, page.output
    lines = dict(re.findall(r'^\t((?:Assets|Equity)\S*(?: \S+)*?) (-?[\d.]+ [A-Z]{3})$', page.output, re.M))
    lines.update(re.findall(rf'^\t([a-z_]+): (-?[\d.]+ {currency})', page.output, re.M))
    return lines


def test_the_balance_sheet_in_cad_after_the_transfer_to_cad_b(tmp_path):
    """In CAD: 14.00 CAD and 90.00 USD worth 126.00 CAD, against 130.00 CAD of equity, 1.00 CAD realized and 9.00 CAD unrealized.

    USD_A stores 117.00 CAD for its 90.00 USD, which are worth 126.00 CAD at
    1.40 CAD/USD.
    """
    sheet = _sheet(_book(tmp_path, HOLDS_100_USD, TO_CAD_B), 'CAD')
    assert sheet['Assets:CAD_B'] == '14.00 CAD'
    assert sheet['Assets:USD_A'] == '90.00 USD'
    assert sheet['total_assets'] == '140.00 CAD'
    assert sheet['Equity:Opening Balances'] == '130.00 CAD'
    assert sheet['retained_earnings'] == '1.00 CAD'
    assert sheet['total_realized_gains'] == '1.00 CAD'
    assert sheet['total_unrealized_gains'] == '9.00 CAD'
    assert sheet['total_liabilities_and_equity'] == '140.00 CAD'


def test_the_balance_sheet_shows_the_9_cad_worked_out_from_what_usd_a_stores(tmp_path):
    """The working is an account, its balance and the balance it stores, and states no cost basis."""
    book = _book(tmp_path, HOLDS_100_USD, TO_CAD_B)
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2030-02-01',
                '--currency', 'CAD').output
    working = re.sub(r'account_guid: [0-9a-f]{32}', 'account_guid: GUID', page)
    assert ('\t\t\t\tstored_balances:\n'
            '\t\t\t\t\tstored_balance:\n'
            '\t\t\t\t\t\taccount_guid: GUID\n'
            '\t\t\t\t\t\taccount: "Assets:USD_A"\n'
            '\t\t\t\t\t\tbalance: 90.00\n'
            '\t\t\t\t\t\tstored_value: 117.00 # what the account stores for its balance\n'
            '\t\t\t\t\t\tvalue: 126.00 # balance * share_price\n'
            '\t\t\t\t\t\tunrealized_gains_assets_fx: 9.00 # value - stored_value\n'
            "\t\t\t\tbalance: 90.00 # sum of each stored_balance's balance\n"
            "\t\t\t\tstored_value: 117.00 # sum of each stored_balance's stored_value\n"
            ) in working, page
    assert 'cost' not in page, page


def test_the_balance_sheet_in_hkd_after_the_transfer_to_cad_b(tmp_path):
    """In HKD: 785.00 HKD of assets, against 780.00 HKD of equity, 0.50 HKD realized and 4.50 HKD unrealized.

    14.00 CAD is worth 78.50 HKD and 90.00 USD is worth 706.50 HKD at 7.85
    HKD/USD. The opening equity is the 780.00 HKD it was on its day. USD_A
    stores 702.00 HKD for its 90.00 USD, and CAD_B stores 78.50 HKD for its
    14.00 CAD.
    """
    sheet = _sheet(_book(tmp_path, HOLDS_100_USD, TO_CAD_B), 'HKD')
    assert sheet['total_assets'] == '785.00 HKD'
    assert sheet['Equity:Opening Balances'] == '780.00 HKD'
    assert sheet['retained_earnings'] == '0.50 HKD'
    assert sheet['total_realized_gains'] == '0.50 HKD'
    assert sheet['total_unrealized_gains'] == '4.50 HKD'
    assert sheet['total_liabilities_and_equity'] == '785.00 HKD'


def test_the_income_statement_in_cny_states_the_5_cny_realized(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD, TO_CAD_B)
    page = _run(CliRunner(), 'income-statement', str(book), '--currency', 'CNY',
                '--start', '2030-01-01', '--end', '2030-12-31')
    assert page.exit_code == 0, page.output
    assert '\tIncome:FX Gain 5.00 CNY\n' in page.output, page.output


def test_a_statement_in_a_currency_u_did_not_select_is_refused(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD, TO_CAD_B)
    for command in (['balance-sheet', str(book), '--as-of', '2030-02-01'],
                    ['income-statement', str(book), '--start', '2030-01-01', '--end', '2030-12-31']):
        page = _run(CliRunner(), *command, '--currency', 'EUR')
        assert page.exit_code != 0
        assert ('this book keeps a balance in each of CAD, USD, HKD, CNY on every account, '
                'and a statement is printed in one of those. It holds no balance in EUR'
                ) in page.output, page.output


def test_usd_a_holding_100_usd_also_stores_130_cad_780_hkd_and_600_cny(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD)
    assert _balances(book)['Assets:USD_A'] == '100.00 USD, 130.00 CAD, 780.00 HKD, 600.00 CNY'


def test_10_usd_from_usd_a_to_usd_a1_moves_13_cad_78_hkd_and_60_cny(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD, TO_USD_A1)
    assert _splits(book, tmp_path, 'Transfer 10.00 USD from USD_A to USD_A1') == {
        'Assets:USD_A1': {'CAD': '13.00', 'HKD': '78.00', 'CNY': '60.00'},
        'Assets:USD_A': {'CAD': '-13.00', 'HKD': '-78.00', 'CNY': '-60.00'},
    }
    balances = _balances(book)
    assert balances['Assets:USD_A'] == '90.00 USD, 117.00 CAD, 702.00 HKD, 540.00 CNY'
    assert balances['Assets:USD_A1'] == '10.00 USD, 13.00 CAD, 78.00 HKD, 60.00 CNY'


def test_10_usd_from_usd_a_to_cad_b_realizes_1_cad_0_50_hkd_and_5_cny(tmp_path):
    book = _book(tmp_path, HOLDS_100_USD, TO_CAD_B)
    assert _splits(book, tmp_path, 'Transfer 10.00 USD from USD_A to CAD_B at 1.40 CAD/USD') == {
        'Assets:CAD_B': {'USD': '10.00', 'HKD': '78.50', 'CNY': '65.00'},
        'Assets:USD_A': {'CAD': '-13.00', 'HKD': '-78.00', 'CNY': '-60.00'},
        'Income:FX Gain': {'USD': '0.00', 'HKD': '-0.50', 'CNY': '-5.00'},
    }
    balances = _balances(book)
    assert balances['Assets:USD_A'] == '90.00 USD, 117.00 CAD, 702.00 HKD, 540.00 CNY'
    assert balances['Assets:CAD_B'] == '14.00 CAD, 10.00 USD, 78.50 HKD, 65.00 CNY'
    assert balances['Income:FX Gain'] == '-1.00 CAD, 0.00 USD, -0.50 HKD, -5.00 CNY'
