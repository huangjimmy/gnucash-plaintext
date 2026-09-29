"""A US company keeps its book in USD and measures the CAD it holds in USD (Q-056).

The author's case, the mirror of a Canadian book that holds US dollars. This
book belongs to a US company, and states `base_currency: "USD"`. In it, CAD is
a foreign currency: each amount of CAD the book holds has a cost basis in USD.
USD has none. The company invoices a Canadian customer in CAD. The customer
pays into the company's CAD bank account, and the company later sells part of
the CAD for USD.

Each step is imported into the book as the previous step saved it. After each
step, the test checks three things:

- `fx-balances` lists the cost bases the book holds, each costed in USD;
- `fx-balances --verify-costs` and `--verify-integrity` find nothing wrong;
- `export` writes the transactions that the step's `_exported.txt` fixture
  states.

Step 1, `tests/fixtures/a_us_company_1_invoices_20000_cad_at_0_74_usd_per_cad_and_collects_it_in_cad.txt`,
opens the accounts, states `base_currency: "USD"`, and records 500,000.00 USD
of share capital. On 2026-02-02 the company posted INV-C01 to its customer for
20,000.00 CAD. The exchange rate on that day was 0.74 USD/CAD, so the sale was
recorded as 14,800.00 USD of revenue. On 2026-03-02 the customer paid the
20,000.00 CAD into the company's CAD account:

2026-02-02 * "INV-C01" "Invoice INV-C01"
	guid: "0d570000000000000000000000000011"
	currency.mnemonic: "CAD"
	Assets:Accounts Receivable CAD 20000.00 CAD
		guid: "0d570000000000000000000000000111"
	Income:Sales -14800.00 USD
		guid: "0d570000000000000000000000000112"
		share_price: "20000/14800"
		value: "-20000.00"

2026-03-02 * "Maple Retail Ltd"
	guid: "0d570000000000000000000000000012"
	txn_type: P
	owner: customer:C-CA
	Assets:Bank CAD 20000.00 CAD
		guid: "0d570000000000000000000000000121"
	Assets:Accounts Receivable CAD -20000.00 CAD
		guid: "0d570000000000000000000000000122"

The invoice's receivable split is a cost basis of 20,000.00 CAD that cost
14,800.00 USD. The payment arrived in CAD and stayed in CAD, so no currency was
exchanged and no gain was realized.

Step 2, `a_us_company_2_invoices_10000_cad_at_0_72_usd_per_cad_and_collects_it_in_cad.txt`: on
2026-04-01 the company posted INV-C02 for 10,000.00 CAD. The exchange rate on
that day was 0.72 USD/CAD, so the sale was recorded as 7,200.00 USD. On
2026-05-04 the customer paid it into the same CAD account.

Step 3, `a_us_company_3_sells_15000_cad_at_0_75_usd_per_cad.txt`: on 2026-06-01 the
company sold 15,000.00 CAD for USD at 0.75 USD/CAD. The transaction states
that the CAD came from INV-C01's cost basis:

2026-06-01 * "Sell 15,000.00 CAD at 0.75 USD/CAD"
	guid: "0d570000000000000000000000000031"
	currency.mnemonic: "USD"
	Assets:Bank USD 11250.00 USD
		guid: "0d570000000000000000000000000311"
	Assets:Bank CAD -15000.00 CAD
		guid: "0d570000000000000000000000000312"
		share_price: "0.74"
		value: "-11100.00"
		cost_basis_split_guid: "0d570000000000000000000000000111"
	Income:FX Gain $residual$ USD
		guid: "0d570000000000000000000000000313"

The 15,000.00 CAD cost 11,100.00 USD (0.74 USD/CAD) and was sold for
11,250.00 USD (0.75 USD/CAD). The sale realized a gain of 150.00 USD.
INV-C01's cost basis has 5,000.00 CAD left.

Step 4, `a_us_company_4_adds_a_price_of_0_73_usd_per_cad_on_2026_12_31.txt`,
holds one `price` block. Importing it adds a price of 0.73 USD/CAD on
2026-12-31 to the book's price database. The balance sheet on that date
values the CAD at that price, and states:

- The company still holds 15,000.00 CAD, which cost 10,900.00 USD. 5,000.00
  CAD came from INV-C01, at 0.74 USD/CAD (3,700.00 USD). 10,000.00 CAD came
  from INV-C02, at 0.72 USD/CAD (7,200.00 USD). The CAD is worth 10,950.00
  USD, which is 50.00 USD more than it cost.
- Assets of 522,200.00 USD: 511,250.00 USD, and 15,000.00 CAD worth 10,950.00
  USD.
- Equity of 522,200.00 USD: 500,000.00 USD of share capital, 22,150.00 USD of
  retained earnings, and the 50.00 USD unrealized. The retained earnings are
  22,000.00 USD of sales plus the 150.00 USD realized.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')

STEPS = [
    'a_us_company_1_invoices_20000_cad_at_0_74_usd_per_cad_and_collects_it_in_cad',
    'a_us_company_2_invoices_10000_cad_at_0_72_usd_per_cad_and_collects_it_in_cad',
    'a_us_company_3_sells_15000_cad_at_0_75_usd_per_cad',
    'a_us_company_4_adds_a_price_of_0_73_usd_per_cad_on_2026_12_31',
]

INV_C01 = '0d570000000000000000000000000111'
INV_C02 = '0d570000000000000000000000000211'

A_ROW = re.compile(r'^(\d{4}-\d\d-\d\d)\s+([0-9a-f]{32})\s+(.+?)\s+(\S+ USD/[A-Z]{3})\s+'
                   r'([\d,.]+ [A-Z]{3})\s+([\d,.]+ [A-Z]{3})\s+(\w+)\s*$')
A_TRANSACTION = re.compile(r'^\d{4}-\d\d-\d\d \* .*\n(?:\t.*\n)*', re.M)


def _book(tmp_path, last):
    """The book after step `last`."""
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
    return A_TRANSACTION.findall(out.read_text())


def _expected(step):
    return A_TRANSACTION.findall((FIXTURES / f'{STEPS[step - 1]}_exported.txt').read_text())


def test_1_inv_c01_collected_in_cad_is_a_cad_cost_basis_at_0_74_usd_per_cad(tmp_path):
    """INV-C01's 20,000.00 CAD is a cost basis that cost 14,800.00 USD.

    The test imports step 1 into a new book with `import --new
    --include-business-objects`. The step posts INV-C01 at 0.74 USD/CAD, and
    the customer pays it into the CAD account. CAD is a foreign currency in
    this book, and the receivable's posting split is its cost basis.
    """
    book = _book(tmp_path, 1)
    assert _cost_bases(book) == [
        (INV_C01, 'Assets:Accounts Receivable CAD', '0.74 USD/CAD', '20,000.00 CAD',
         '20,000.00 CAD', 'asset')]
    _checked(book)
    assert _transactions(book, tmp_path) == _expected(1)


def test_2_inv_c02_is_a_second_cad_cost_basis_at_0_72_usd_per_cad(tmp_path):
    """INV-C02's 10,000.00 CAD is a second cost basis, which cost 7,200.00 USD.

    The test imports step 2 with `import --include-business-objects`. The step
    posts INV-C02 at 0.72 USD/CAD, and the customer pays it into the same CAD
    account.
    """
    book = _book(tmp_path, 2)
    assert _cost_bases(book) == [
        (INV_C01, 'Assets:Accounts Receivable CAD', '0.74 USD/CAD', '20,000.00 CAD',
         '20,000.00 CAD', 'asset'),
        (INV_C02, 'Assets:Accounts Receivable CAD', '0.72 USD/CAD', '10,000.00 CAD',
         '10,000.00 CAD', 'asset')]
    _checked(book)
    assert _transactions(book, tmp_path) == _expected(2)


def test_3_selling_15000_cad_at_0_75_usd_per_cad_realizes_150_usd(tmp_path):
    """Selling 15,000.00 CAD at 0.75 USD/CAD realizes 150.00 USD, and INV-C01 has 5,000.00 CAD left.

    The test imports step 3, the sale. The sale draws on INV-C01's cost basis,
    which cost 0.74 USD/CAD. The CAD cost 11,100.00 USD and was sold for
    11,250.00 USD. `$residual$` records the 150.00 USD gain on Income:FX Gain.
    """
    book = _book(tmp_path, 3)
    assert _cost_bases(book) == [
        (INV_C01, 'Assets:Accounts Receivable CAD', '0.74 USD/CAD', '20,000.00 CAD',
         '5,000.00 CAD', 'asset'),
        (INV_C02, 'Assets:Accounts Receivable CAD', '0.72 USD/CAD', '10,000.00 CAD',
         '10,000.00 CAD', 'asset')]
    _checked(book)
    assert _transactions(book, tmp_path) == _expected(3)


def test_4_the_balance_sheet_on_2026_12_31_states_150_usd_realized_and_50_usd_unrealized(tmp_path):
    """The year-end balance sheet states 150.00 USD realized and 50.00 USD unrealized, and it balances.

    The test imports step 4, which adds a price of 0.73 USD/CAD on 2026-12-31
    to the book, and then runs `balance-sheet --as-of 2026-12-31`. The company still holds 15,000.00 CAD,
    which cost 10,900.00 USD; at 0.73 USD/CAD it is worth 10,950.00 USD.
    """
    book = _book(tmp_path, 4)
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')
    assert page.exit_code == 0, page.output
    sheet = dict(re.findall(r'^\t([a-z_]+): (-?[\d.]+ USD)', page.output, re.M))
    assert sheet['total_assets'] == '522200.00 USD'
    assert sheet['retained_earnings'] == '22150.00 USD'
    assert sheet['unrealized_gains_fx'] == '50.00 USD'
    assert sheet['total_realized_gains'] == '150.00 USD'
    assert sheet['total_equity'] == '522200.00 USD'
    assert sheet['total_liabilities_and_equity'] == '522200.00 USD'
    _checked(book)
