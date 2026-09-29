"""A Hong Kong company keeps its book in HKD and measures its USD, CNY and EUR in HKD (Q-056).

The author's case. A book states its base currency in its `company` block.
Every other currency is foreign, and each amount of a foreign currency the
book holds has a cost basis: what it cost in the base currency. Realized and
unrealized gains are measured in the base currency too.

This book belongs to a Hong Kong company, and states `base_currency: "HKD"`.
The company has a US dollar bank account. Its customers pay their USD invoices
into that account. When the company needs HKD, it sells part of the USD it
holds. The company also buys CNY. It pays a supplier's EUR bill with EUR that
it buys for the purpose.

Each step is imported into the book as the previous step saved it. After each
step, the test checks three things:

- `fx-balances` lists the cost bases the book holds, each costed in HKD;
- `fx-balances --verify-costs` and `--verify-integrity` find nothing wrong;
- `export` writes the transactions that the step's `_exported.txt` fixture
  states.

Step 1, `tests/fixtures/a_hong_kong_company_1_invoices_10000_usd_at_7_80_hkd_per_usd_and_collects_it_in_usd.txt`,
opens the accounts, states `base_currency: "HKD"`, and records 1,000,000.00 HKD
of share capital. On 2026-02-02 the company posted INV-001 to its customer for
10,000.00 USD. The exchange rate on that day was 7.80 HKD/USD, so the sale was
recorded as 78,000.00 HKD of revenue. On 2026-03-02 the customer paid the
10,000.00 USD into the company's USD account:

2026-02-02 * "INV-001" "Invoice INV-001"
	guid: "0d560000000000000000000000000011"
	currency.mnemonic: "USD"
	Assets:Accounts Receivable USD 10000.00 USD
		guid: "0d560000000000000000000000000111"
	Income:Sales -78000.00 HKD
		guid: "0d560000000000000000000000000112"
		share_price: "10000/78000"
		value: "-10000.00"

2026-03-02 * "Pacific Buyer Inc"
	guid: "0d560000000000000000000000000012"
	txn_type: P
	owner: customer:C-US
	Assets:Bank USD 10000.00 USD
		guid: "0d560000000000000000000000000121"
	Assets:Accounts Receivable USD -10000.00 USD
		guid: "0d560000000000000000000000000122"

The invoice's receivable split is a cost basis of 10,000.00 USD that cost
78,000.00 HKD. The payment arrived in USD and stayed in USD, so no currency was
exchanged and no gain was realized. The 10,000.00 USD in the bank carries
INV-001's cost.

Step 2, `a_hong_kong_company_2_invoices_5000_usd_at_7_75_hkd_per_usd_and_collects_it_in_usd.txt`: on
2026-04-01 the company posted INV-002 for 5,000.00 USD. The exchange rate on
that day was 7.75 HKD/USD, so the sale was recorded as 38,750.00 HKD. On
2026-05-04 the customer paid it into the same USD account. The book then held
two USD cost bases, one at 7.80 HKD/USD and one at 7.75 HKD/USD.

Step 3, `a_hong_kong_company_3_sells_8000_usd_at_7_85_hkd_per_usd.txt`: on
2026-06-01 the company sold 8,000.00 USD for HKD at 7.85 HKD/USD. The
transaction states that the USD came from INV-001's cost basis:

2026-06-01 * "Sell 8,000.00 USD at 7.85 HKD/USD"
	guid: "0d560000000000000000000000000031"
	currency.mnemonic: "HKD"
	Assets:Bank HKD 62800.00 HKD
		guid: "0d560000000000000000000000000311"
	Assets:Bank USD -8000.00 USD
		guid: "0d560000000000000000000000000312"
		share_price: "7.80"
		value: "-62400.00"
		cost_basis_split_guid: "0d560000000000000000000000000111"
	Income:FX Gain $residual$ HKD
		guid: "0d560000000000000000000000000313"

The 8,000.00 USD cost 62,400.00 HKD (7.80 HKD/USD) and was sold for 62,800.00
HKD (7.85 HKD/USD). The sale realized a gain of 400.00 HKD. INV-001's cost
basis has 2,000.00 USD left.

Step 4, `a_hong_kong_company_4_buys_50000_cny_at_1_08_hkd_per_cny.txt`: on 2026-07-02 the company bought
50,000.00 CNY at 1.08 HKD/CNY and paid 54,000.00 HKD for it. The purchase
opened a cost basis of 50,000.00 CNY that cost 54,000.00 HKD.

Step 5, `a_hong_kong_company_5_pays_a_2000_eur_bill_with_eur_bought_at_8_45_hkd_per_eur.txt`: a
French supplier billed the company 2,000.00 EUR for design services. The
company posted the bill, BILL-EU-001, on 2026-08-03. The exchange rate on that
day was 8.50 HKD/EUR, so the expense was recorded as 17,000.00 HKD. On
2026-08-14 the company bought 2,000.00 EUR at 8.45 HKD/EUR and paid 16,900.00
HKD for it. On 2026-08-20 the company paid the bill with that EUR:

2026-08-20 * "Atelier Lumière SARL"
	guid: "0d560000000000000000000000000053"
	currency.mnemonic: "HKD"
	txn_type: P
	owner: vendor:V-EU
	Liabilities:Accounts Payable EUR 2000.00 EUR
		guid: "0d560000000000000000000000000531"
		share_price: "8.50"
		value: "17000.00"
		cost_basis_split_guid: "0d560000000000000000000000000511"
	Assets:Bank EUR -2000.00 EUR
		guid: "0d560000000000000000000000000532"
		share_price: "8.45"
		value: "-16900.00"
		cost_basis_split_guid: "0d560000000000000000000000000521"
	Income:FX Gain $residual$ HKD
		guid: "0d560000000000000000000000000533"

The company owed 2,000.00 EUR, recorded at 17,000.00 HKD (8.50 HKD/EUR). It
paid the debt with 2,000.00 EUR that cost 16,900.00 HKD (8.45 HKD/EUR). The
payment realized a gain of 100.00 HKD. Neither EUR cost basis has anything
left.

Step 6, `a_hong_kong_company_6_adds_prices_of_7_83_hkd_per_usd_and_1_09_hkd_per_cny_on_2026_12_31.txt`,
holds two `price` blocks. Importing it adds two prices on 2026-12-31 to the
book's price database: 7.83 HKD/USD and 1.09 HKD/CNY. The balance sheet on
that date values the USD and the CNY at those prices, and states:

- Assets of 1,101,210.00 HKD: 991,900.00 HKD, 7,000.00 USD worth 54,810.00 HKD,
  and 50,000.00 CNY worth 54,500.00 HKD.
- The company still holds 7,000.00 USD, which cost 54,350.00 HKD. 2,000.00
  USD came from INV-001, at 7.80 HKD/USD (15,600.00 HKD). 5,000.00 USD came
  from INV-002, at 7.75 HKD/USD (38,750.00 HKD). The USD is worth 460.00 HKD
  more than it cost.
- The 50,000.00 CNY cost 54,000.00 HKD, and is worth 500.00 HKD more than it
  cost.
- Realized gains of 500.00 HKD: 400.00 HKD on the USD sold, and 100.00 HKD on
  the bill.
- Unrealized gains of 960.00 HKD: 460.00 HKD on the USD and 500.00 HKD on the
  CNY.
- Equity of 1,101,210.00 HKD: 1,000,000.00 HKD of share capital, 100,250.00
  HKD of retained earnings, and the 960.00 HKD unrealized. The retained
  earnings are 116,750.00 HKD of sales plus the 500.00 HKD realized, less
  17,000.00 HKD of design services.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')

STEPS = [
    'a_hong_kong_company_1_invoices_10000_usd_at_7_80_hkd_per_usd_and_collects_it_in_usd',
    'a_hong_kong_company_2_invoices_5000_usd_at_7_75_hkd_per_usd_and_collects_it_in_usd',
    'a_hong_kong_company_3_sells_8000_usd_at_7_85_hkd_per_usd',
    'a_hong_kong_company_4_buys_50000_cny_at_1_08_hkd_per_cny',
    'a_hong_kong_company_5_pays_a_2000_eur_bill_with_eur_bought_at_8_45_hkd_per_eur',
    'a_hong_kong_company_6_adds_prices_of_7_83_hkd_per_usd_and_1_09_hkd_per_cny_on_2026_12_31',
]

INV_001 = '0d560000000000000000000000000111'
INV_002 = '0d560000000000000000000000000211'
CNY_BOUGHT = '0d560000000000000000000000000411'
BILL_EU_001 = '0d560000000000000000000000000511'
EUR_BOUGHT = '0d560000000000000000000000000521'

A_ROW = re.compile(r'^(\d{4}-\d\d-\d\d)\s+([0-9a-f]{32})\s+(.+?)\s+(\S+ HKD/[A-Z]{3})\s+'
                   r'([\d,.]+ [A-Z]{3})\s+([\d,.]+ [A-Z]{3})\s+(\w+)\s*$')


def _book(tmp_path, last):
    """The book after step `last`, and that step's import output."""
    book = tmp_path / 'book.gnucash'
    for number, step in enumerate(STEPS[:last], start=1):
        args = ['import', str(book), str(FIXTURES / f'{step}.txt'), '--include-business-objects']
        if number == 1:
            args.insert(1, '--new')
        done = _run(CliRunner(), *args)
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
        assert '⚠' not in done.output, done.output
    return book


def _cost_bases(book):
    """Each cost basis `fx-balances` lists: guid, account, cost, brought in, balance, side."""
    listing = _run(CliRunner(), 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    return [row.groups()[1:] for row in map(A_ROW.match, listing.output.splitlines()) if row]


def _checked(book):
    """`fx-balances --verify-costs` and `--verify-integrity` find nothing wrong."""
    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert costs.exit_code == 0, costs.output
    assert 'every cost agrees with the figures it is derived from' in costs.output, costs.output
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0, whole.output


def _transactions(book, tmp_path):
    """The transactions `export` writes, each block as written, in order."""
    out = tmp_path / 'exported.txt'
    done = _run(CliRunner(), 'export', str(book), str(out))
    assert done.exit_code == 0, done.output
    return re.findall(r'^\d{4}-\d\d-\d\d \* .*\n(?:\t.*\n)*', out.read_text(), re.M)


def _expected(step):
    text = (FIXTURES / f'{STEPS[step - 1]}_exported.txt').read_text()
    return re.findall(r'^\d{4}-\d\d-\d\d \* .*\n(?:\t.*\n)*', text, re.M)


def _sheet(book):
    """The year-end balance sheet's figures, by key, for the keys a line states once."""
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')
    assert page.exit_code == 0, page.output
    return dict(re.findall(r'^\t([a-z_]+): (-?[\d.]+ HKD)', page.output, re.M))


def test_1_inv_001_collected_in_usd_is_a_usd_cost_basis_at_7_80_hkd_per_usd(tmp_path):
    """INV-001's 10,000.00 USD is a cost basis that cost 78,000.00 HKD.

    The test imports step 1 into a new book with `import --new
    --include-business-objects`. The step posts INV-001 at 7.80 HKD/USD, and
    the customer pays it into the USD account. The receivable's posting split
    is the cost basis, and all 10,000.00 USD of it is left.
    """
    book = _book(tmp_path, 1)
    assert _cost_bases(book) == [
        (INV_001, 'Assets:Accounts Receivable USD', '7.8 HKD/USD', '10,000.00 USD',
         '10,000.00 USD', 'asset')]
    _checked(book)
    assert _transactions(book, tmp_path) == _expected(1)


def test_2_inv_002_is_a_second_usd_cost_basis_at_7_75_hkd_per_usd(tmp_path):
    """INV-002's 5,000.00 USD is a second cost basis, which cost 38,750.00 HKD.

    The test imports step 2 with `import --include-business-objects`. The step
    posts INV-002 at 7.75 HKD/USD, and the customer pays it into the same USD
    account. The book holds two USD cost bases, each at the exchange rate on
    the day its invoice was posted.
    """
    book = _book(tmp_path, 2)
    assert _cost_bases(book) == [
        (INV_001, 'Assets:Accounts Receivable USD', '7.8 HKD/USD', '10,000.00 USD',
         '10,000.00 USD', 'asset'),
        (INV_002, 'Assets:Accounts Receivable USD', '7.75 HKD/USD', '5,000.00 USD',
         '5,000.00 USD', 'asset')]
    _checked(book)
    assert _transactions(book, tmp_path) == _expected(2)


def test_3_selling_8000_usd_at_7_85_hkd_per_usd_realizes_400_hkd(tmp_path):
    """Selling 8,000.00 USD at 7.85 HKD/USD realizes 400.00 HKD, and INV-001 has 2,000.00 USD left.

    The test imports step 3, the sale. The sale draws on INV-001's cost basis,
    which cost 7.80 HKD/USD. The USD cost 62,400.00 HKD and was sold for
    62,800.00 HKD. `$residual$` records the 400.00 HKD gain on Income:FX Gain.
    """
    book = _book(tmp_path, 3)
    assert _cost_bases(book) == [
        (INV_001, 'Assets:Accounts Receivable USD', '7.8 HKD/USD', '10,000.00 USD',
         '2,000.00 USD', 'asset'),
        (INV_002, 'Assets:Accounts Receivable USD', '7.75 HKD/USD', '5,000.00 USD',
         '5,000.00 USD', 'asset')]
    _checked(book)
    assert _transactions(book, tmp_path) == _expected(3)


def test_4_50000_cny_bought_at_1_08_hkd_per_cny_is_a_cny_cost_basis(tmp_path):
    """50,000.00 CNY bought at 1.08 HKD/CNY is a cost basis that cost 54,000.00 HKD.

    The test imports step 4. The company pays 54,000.00 HKD from its HKD
    account, and the 50,000.00 CNY arrives in its CNY account.
    """
    book = _book(tmp_path, 4)
    assert _cost_bases(book)[-1] == (
        CNY_BOUGHT, 'Assets:Bank CNY', '1.08 HKD/CNY', '50,000.00 CNY', '50,000.00 CNY',
        'asset')
    _checked(book)
    assert _transactions(book, tmp_path) == _expected(4)


def test_5_paying_the_eur_bill_posted_at_8_50_with_eur_bought_at_8_45_hkd_per_eur_realizes_100_hkd(tmp_path):
    """Paying a bill posted at 8.50 HKD/EUR with EUR bought at 8.45 HKD/EUR realizes 100.00 HKD.

    The test imports step 5 with `import --include-business-objects`. The bill
    for 2,000.00 EUR was posted at 8.50 HKD/EUR, so the debt was recorded as
    17,000.00 HKD. The company paid it with 2,000.00 EUR that it bought at 8.45
    HKD/EUR for 16,900.00 HKD. The payment draws on both cost bases, and
    `$residual$` records the 100.00 HKD gain on Income:FX Gain. Neither EUR
    cost basis has anything left.
    """
    book = _book(tmp_path, 5)
    eur = [row for row in _cost_bases(book) if row[0] in (BILL_EU_001, EUR_BOUGHT)]
    assert eur == [
        (EUR_BOUGHT, 'Assets:Bank EUR', '8.45 HKD/EUR', '2,000.00 EUR', '0.00 EUR',
         'asset'),
        (BILL_EU_001, 'Liabilities:Accounts Payable EUR', '8.5 HKD/EUR', '2,000.00 EUR',
         '0.00 EUR', 'liability')]
    _checked(book)
    assert _transactions(book, tmp_path) == _expected(5)


def test_6_the_balance_sheet_on_2026_12_31_states_500_hkd_realized_and_960_hkd_unrealized(tmp_path):
    """The year-end balance sheet states 500.00 HKD realized and 960.00 HKD unrealized, and it balances.

    The test imports step 6, which adds prices of 7.83 HKD/USD and 1.09
    HKD/CNY on 2026-12-31 to the book, and then runs
    `balance-sheet --as-of 2026-12-31`. The company still holds 7,000.00 USD,
    which cost 54,350.00 HKD; at 7.83 HKD/USD it is worth 54,810.00 HKD. The 50,000.00 CNY cost
    54,000.00 HKD, and at 1.09 HKD/CNY it is worth 54,500.00 HKD.
    """
    book = _book(tmp_path, 6)
    sheet = _sheet(book)
    assert sheet['total_assets'] == '1101210.00 HKD'
    assert sheet['retained_earnings'] == '100250.00 HKD'
    assert sheet['unrealized_gains_fx'] == '960.00 HKD'
    assert sheet['total_realized_gains'] == '500.00 HKD'
    assert sheet['total_equity'] == '1101210.00 HKD'
    assert sheet['total_liabilities_and_equity'] == '1101210.00 HKD'
    _checked(book)
