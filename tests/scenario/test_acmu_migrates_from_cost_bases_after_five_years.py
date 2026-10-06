"""ACMU LLC keeps cost bases for five years, then keeps a balance in each selected currency as ACME does (Q-057).

The author's case, as the author gave it:

    now we need another case, user A has a company ACMU LLC, similar to ACME,
    but ACMU use cost basis and base currency in CAD, then A think the ACME
    is better, then after 5 years, user migrate ACMU from cost basis to the
    multiple currency support like ACME

    you should create a ACMU with many transactions including invoices, and
    then migrate away from cost basis, and the book should not break! and
    balance sheet/income statement after the migration should still hold!

    and ACMU should also have CAD invoice 1000 CAD

And on the rates: "if you know the tx date, you should know the rate on that
day". Every rate is the Bank of Canada's daily rate for the day of the
transaction, in Canadian dollars, or the last it published before a day it
published none: 31 December for 1 January, 2023-03-31 for Saturday
2023-04-01, 2024-06-28 for Sunday 2024-06-30 and 2025-01-31 for Saturday
2025-02-01. The fixtures hold them as the book's prices. The case gives the
1,000.00 CAD invoice and "many transactions including invoices"; which
transactions, and their dates and amounts, are the fixtures'. ACMU's fiscal
year ends on 06-30, as ACME's does.

Steps 1 to 3 are ACME's three, in a book kept in CAD with cost bases:

- 2020-01-01 opening, 1,000.00 USD at 1.2988 CAD/USD, 1,298.80 CAD.
- 2021-01-01 INV-ABC, 1,000.00 USD at 1.2732 CAD/USD, 1,273.20 CAD, and
  INV-ABC-EU, 1,000.00 EUR at 1.5608 CAD/EUR, 1,560.80 CAD. Both paid on
  2021-03-03.
- 2021-06-01 1,000.00 EUR that cost 1,560.80 CAD sold for 1,223.34 USD worth
  1,472.90 CAD at 1.2040 CAD/USD: 87.90 CAD lost.

Step 4, `acmu_4_trades_from_2021_07_to_2024_12_with_cost_bases.txt`, after
`acmu_4_bank_of_canada_rates_from_2021_06_30_to_2024_12_31.txt`:

- 2021-09-01 INV-ABC-2, 2,000.00 USD at 1.2607 CAD/USD, 2,521.40 CAD, paid on 2021-10-01.
- 2021-11-15 software, 300.00 USD that cost 389.64 CAD, worth 375.51 CAD at
  1.2517 CAD/USD: 14.13 CAD lost.
- 2022-02-01 1,500.00 USD sold for 1,904.10 CAD at 1.2694 CAD/USD. 700.00 USD
  cost 909.16 CAD and 800.00 USD cost 1,018.56 CAD: 23.62 CAD lost.
- 2022-03-01 INV-MAPLE, 1,000.00 CAD, paid on 2022-03-20.
- 2022-05-10 rent, 400.00 CAD.
- 2022-09-01 INV-ABC-EU-2, 2,000.00 EUR at 1.3110 CAD/EUR, 2,622.00 CAD, paid on 2022-10-05.
- 2023-01-10 1,000.00 EUR that cost 1,311.00 CAD sold for 1,440.70 CAD at
  1.4407 CAD/EUR: 129.70 CAD gained.
- 2023-04-01 travel, 200.00 EUR that cost 262.20 CAD, worth 294.16 CAD at
  1.4708 CAD/EUR: 31.96 CAD gained.
- 2023-09-01 INV-ABC-3, 1,500.00 USD at 1.3580 CAD/USD, 2,037.00 CAD, paid on 2023-09-20.
- 2024-02-01 bank fee, 25.00 USD that cost 31.83 CAD, worth 33.51 CAD at
  1.3404 CAD/USD: 1.68 CAD gained.
- 2024-10-01 INV-ABC-4, 1,000.00 USD at 1.3504 CAD/USD, 1,350.40 CAD, not yet paid.

Step 5, `acmu_5_selects_cad_usd_cny_hkd_eur_and_gbp.txt`, is the migration: a
`company` block stating `currency_balances: "CAD USD CNY HKD EUR GBP"`.

Step 6, `acmu_6_sells_500_usd_storing_638_39_cad_for_724_20_cad_on_2025_02_01.txt`,
is the first transaction after it. Chase Chequing holds 4,898.34 USD storing
6,254.11 CAD, so 500.00 USD store 638.39 CAD. Sold for 724.20 CAD at 1.4484
CAD/USD, they realize 85.81 CAD, and the transaction states no cost basis.

Then one transaction in the middle of a year is deleted, which the author
asked for after those steps were tested:

    gnucash allow deletion of any transactions, but the scenario test dont
    cover this!!!, must extend the ACME and ACMU scenaris with deleting 1
    transaction in the middle of the year, then what happen? there will be
    cascading effect to all balances!!!

`delete-transactions` removes the 2021-11-15 software subscription, 300.00
USD that cost 389.64 CAD. It is deleted once before the migration and once
after it, and the book comes out the same either way:

- Chase Chequing holds 300.00 USD more from that day on, 5,198.34 USD at the
  end, storing 389.64 CAD more, 6,643.75 CAD.
- The 375.51 CAD of expense and the 14.13 CAD of loss are gone, so each year
  end from 2022-06-30 on has 389.64 CAD more of retained earnings and 14.13
  CAD more of realized gain.
- Each later year end values 300.00 USD more at that day's rate. On
  2022-06-30, 3,723.34 USD at 1.2886 CAD/USD are 4,797.90 CAD against the
  4,638.58 CAD they store.
- In each other currency, every later sale of US dollars moves a different
  share of what the account stores, since the account holds more.

Every amount in CAD here was worked out from the bank's rates lot by lot,
apart from gnucash-plaintext, and the statements it prints were then read
against them.
"""

import re
from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')
OPENS = 'acmu_1_opens_with_1000_usd_that_cost_1298_80_cad_on_2020_01_01'
INVOICES = ('acmu_2_invoices_abc_1000_usd_at_1_2732_cad_per_usd_and_abc_europe_1000_eur_'
            'at_1_5608_cad_per_eur_and_is_paid_in_full')
SELLS_EUR = ('acmu_3_sells_1000_eur_that_cost_1560_80_cad_for_1223_34_usd_worth_1472_90_cad_'
             'on_2021_06_01')
RATES = 'acmu_4_bank_of_canada_rates_from_2021_06_30_to_2024_12_31'
FIVE_YEARS = 'acmu_4_trades_from_2021_07_to_2024_12_with_cost_bases'
MIGRATES = 'acmu_5_selects_cad_usd_cny_hkd_eur_and_gbp'
SELLS_USD = 'acmu_6_sells_500_usd_storing_638_39_cad_for_724_20_cad_on_2025_02_01'

WITH_COST_BASES = (OPENS, INVOICES, SELLS_EUR, RATES, FIVE_YEARS)
MIGRATED = WITH_COST_BASES + (MIGRATES,)
CURRENCIES = ('CAD', 'USD', 'CNY', 'HKD', 'EUR', 'GBP')
YEAR_ENDS = ('2021-06-30', '2022-06-30', '2023-06-30', '2024-06-30', '2024-12-31')


def _book(tmp_path, steps):
    """The book after `steps`, and the output of the last import."""
    book = tmp_path / 'book.gnucash'
    done = None
    for number, step in enumerate(steps):
        args = ['import', str(book), str(FIXTURES / f'{step}.txt'), '--include-business-objects']
        if number == 0:
            args.insert(1, '--new')
        done = _run(CliRunner(), *args)
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return book, done.output


def _sheet(book, currency, as_of):
    """The balance sheet's totals: assets, liabilities and equity, retained earnings, realized, unrealized."""
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', as_of, '--currency', currency)
    assert page.exit_code == 0, page.output
    keys = dict(re.findall(rf'^\t([a-z_]+): (-?[\d.]+) {currency}', page.output, re.M))
    return (keys['total_assets'], keys['total_liabilities_and_equity'], keys['retained_earnings'],
            keys['total_realized_gains'], keys['total_unrealized_gains'])


def _income(book, currency, fiscal_year_end):
    page = _run(CliRunner(), 'income-statement', str(book), '--currency', currency,
                '--fiscal-year-end', fiscal_year_end)
    assert page.exit_code == 0, page.output
    lines = dict(re.findall(rf'^\t((?:Income|Expenses):\S+(?: \S+)*?) (-?[\d.]+) {currency}$',
                            page.output, re.M))
    lines['net_income'] = re.search(rf'^\tnet_income: (-?[\d.]+) {currency}', page.output, re.M).group(1)
    return lines


def _balances(book):
    listing = _run(CliRunner(), 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    return dict(line.split(': ', 1) for line in listing.output.splitlines()[1:])


# The balance sheet in CAD at each fiscal year end and on 2024-12-31: assets,
# retained earnings, realized gains and unrealized gains.
#
# 2021-06-30: 3,223.34 USD at 1.2394 CAD/USD are 3,995.01 CAD, and cost
# 4,044.90 CAD.
# 2022-06-30: 3,423.34 USD at 1.2886 are 4,411.32 CAD, and cost 4,248.94 CAD.
# With 2,504.10 CAD in RBC Chequing, 6,915.42 CAD.
# 2023-06-30: 3,423.34 USD at 1.3240 are 4,532.50 CAD, 800.00 EUR at 1.4445
# are 1,155.60 CAD and cost 1,048.80 CAD, and 3,944.80 CAD: 9,632.90 CAD.
# 2024-06-30: 4,898.34 USD at 1.3687 are 6,704.36 CAD and cost 6,254.11 CAD,
# 800.00 EUR at 1.4659 are 1,172.72 CAD, and 3,944.80 CAD: 11,821.88 CAD.
# 2024-12-31: 5,898.34 USD with the 1,000.00 USD receivable, at 1.4389, are
# 8,487.12 CAD, 800.00 EUR at 1.4928 are 1,194.24 CAD, and 3,944.80 CAD:
# 13,626.16 CAD.
THE_SHEET_IN_CAD = [
    ('2021-06-30', '3995.01', '2746.10', '-87.90', '-49.89'),
    ('2022-06-30', '6915.42', '5454.24', '-125.65', '162.38'),
    ('2023-06-30', '9632.90', '7943.74', '36.01', '390.36'),
    ('2024-06-30', '11821.88', '9948.91', '37.69', '574.17'),
    ('2024-12-31', '13626.16', '11299.31', '37.69', '1028.05'),
]

THE_INCOME_STATEMENT_IN_CAD = [
    ('2021-06-30', {'Income:Sales': '2834.00', 'Income:FX Gain': '-87.90', 'net_income': '2746.10'}),
    ('2022-06-30', {'Income:Sales': '3521.40', 'Income:FX Gain': '-37.75', 'Expenses:Software': '375.51',
                    'Expenses:Rent': '400.00', 'net_income': '2708.14'}),
    ('2023-06-30', {'Income:Sales': '2622.00', 'Income:FX Gain': '161.66', 'Expenses:Travel': '294.16',
                    'net_income': '2489.50'}),
    ('2024-06-30', {'Income:Sales': '2037.00', 'Income:FX Gain': '1.68', 'Expenses:Bank Fees': '33.51',
                    'net_income': '2005.17'}),
    ('2025-06-30', {'Income:Sales': '1350.40', 'net_income': '1350.40'}),
]


@pytest.mark.parametrize('steps', [WITH_COST_BASES, MIGRATED], ids=['with-cost-bases', 'migrated'])
@pytest.mark.parametrize('as_of, assets, retained, realized, unrealized', THE_SHEET_IN_CAD)
def test_the_balance_sheet_in_cad_holds_through_the_migration(tmp_path, steps, as_of, assets, retained,
                                                             realized, unrealized):
    """Each year end states the same assets, retained earnings and gains before the migration and after it."""
    book, _ = _book(tmp_path, steps)
    assert _sheet(book, 'CAD', as_of) == (assets, assets, retained, realized, unrealized)


@pytest.mark.parametrize('steps', [WITH_COST_BASES, MIGRATED], ids=['with-cost-bases', 'migrated'])
@pytest.mark.parametrize('fiscal_year_end, lines', THE_INCOME_STATEMENT_IN_CAD)
def test_the_income_statement_in_cad_holds_through_the_migration(tmp_path, steps, fiscal_year_end, lines):
    book, _ = _book(tmp_path, steps)
    assert _income(book, 'CAD', fiscal_year_end) == lines


def test_the_book_with_cost_bases_holds_eight_and_checks_out(tmp_path):
    """Before the migration: 5,898.34 USD and 800.00 EUR on eight cost bases, and nothing wrong."""
    book, _ = _book(tmp_path, WITH_COST_BASES)
    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert costs.exit_code == 0, costs.output
    assert 'Total USD cost basis balance: 5,898.34 USD held' in costs.output, costs.output
    assert 'Total EUR cost basis balance: 800.00 EUR held' in costs.output, costs.output
    assert 'Checked 8 cost basis(es): every cost agrees' in costs.output, costs.output
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0 and 'The book is consistent and balanced.' in whole.output, whole.output


def test_the_migration_warns_that_it_cannot_be_undone(tmp_path):
    _, output = _book(tmp_path, MIGRATED)
    assert ('this book kept cost bases, and from now on it keeps a balance in each of '
            'CAD USD CNY HKD EUR GBP on every account instead. The cost bases it recorded '
            'stay in it. A book migrated away from cost bases cannot be migrated back to '
            'them.') in output, output


def test_the_migrated_book_is_consistent_and_balanced(tmp_path):
    book, _ = _book(tmp_path, MIGRATED)
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0 and 'The book is consistent and balanced.' in whole.output, whole.output


def test_each_account_stores_in_cad_what_its_cost_bases_came_to(tmp_path):
    """4,898.34 USD cost 6,254.11 CAD, 800.00 EUR cost 1,048.80 CAD, and the unpaid 1,000.00 USD is 1,350.40 CAD."""
    book, _ = _book(tmp_path, MIGRATED)
    balances = _balances(book)
    assert balances['Assets:Chase Chequing'].startswith('4898.34 USD, 6254.11 CAD, ')
    assert balances['Assets:Wise EUR'].startswith('800.00 EUR, 1048.80 CAD, ')
    assert balances['Assets:Accounts Receivable USD'].startswith('1000.00 USD, 1350.40 CAD, ')
    assert balances['Assets:RBC Chequing'].startswith('3944.80 CAD, ')
    assert balances['Income:Sales'].startswith('-12364.80 CAD, ')
    assert balances['Income:FX Gain'].startswith('-37.69 CAD, ')


def test_every_currency_adds_up_to_zero_across_the_migrated_accounts(tmp_path):
    book, _ = _book(tmp_path, MIGRATED)
    totals = {}
    for held in _balances(book).values():
        for each in held.split(', '):
            amount, code = each.split(' ')
            totals[code] = totals.get(code, Fraction(0)) + Fraction(amount)
    assert totals == dict.fromkeys(CURRENCIES, 0)


@pytest.mark.parametrize('currency', CURRENCIES)
def test_the_migrated_book_s_balance_sheet_balances_in_each_currency_at_each_year_end(tmp_path, currency):
    book, _ = _book(tmp_path, MIGRATED)
    for as_of in YEAR_ENDS:
        assets, liabilities_and_equity, *_ = _sheet(book, currency, as_of)
        assert assets == liabilities_and_equity, (currency, as_of)


def test_the_cost_bases_stay_in_the_migrated_book_and_its_export_reads_back(tmp_path):
    book, _ = _book(tmp_path, MIGRATED)
    out = tmp_path / 'exported.txt'
    assert _run(CliRunner(), 'export', str(book), str(out)).exit_code == 0
    exported = out.read_text()
    assert exported.count('cost_basis_split_guid: ') == 7
    assert 'cost_basis_balance: "175.00"' in exported
    again = _run(CliRunner(), 'import', str(book), str(out), '--strategy', 'update')
    assert again.exit_code == 0, again.output
    # The book's 21 transactions: 1 opening, 4 of the first invoices, 1 sale
    # of EUR and 15 of the five years.
    assert 'Up to date:   21 (no new changes, not edited)' in again.output, again.output


def test_acmu_s_first_three_steps_migrated_store_what_acme_s_accounts_store(tmp_path):
    """The same money at the same rates: Chase Chequing's 3,223.34 USD store what ACME's do."""
    book, _ = _book(tmp_path, (OPENS, INVOICES, SELLS_EUR, MIGRATES))
    assert _balances(book) == {
        'Assets:Chase Chequing': '3223.34 USD, 4044.90 CAD, 21302.17 CNY, 25030.87 HKD, '
                                 '2706.37 EUR, 2352.30 GBP',
        'Equity:Opening Balances': '-1298.80 CAD, -1000.00 USD, -6964.08 CNY, -7786.57 HKD, '
                                   '-890.63 EUR, -756.26 GBP',
        'Income:Sales': '-2834.00 CAD, -2225.89 USD, -14540.79 CNY, -17259.44 HKD, '
                        '-1815.74 EUR, -1630.51 GBP',
        'Income:FX Gain': '87.90 CAD, 2.55 USD, 202.70 CNY, 15.14 HKD, 0.00 EUR, 34.47 GBP',
    }


THE_SOFTWARE_SUBSCRIPTION = '0d590000000000000000000000000043'

# The balance sheet in CAD with the software subscription deleted: assets,
# retained earnings, realized gains and unrealized gains. 2021-06-30 is
# before it and states what it stated.
#
# 2022-06-30: 3,723.34 USD at 1.2886 are 4,797.90 CAD and store 4,638.58 CAD,
# with 2,504.10 CAD: 7,302.00 CAD.
# 2023-06-30: 3,723.34 USD at 1.3240 are 4,929.70 CAD, 800.00 EUR are
# 1,155.60 CAD, and 3,944.80 CAD: 10,030.10 CAD.
# 2024-06-30: 5,198.34 USD at 1.3687 are 7,114.97 CAD and store 6,643.75 CAD,
# 800.00 EUR are 1,172.72 CAD, and 3,944.80 CAD: 12,232.49 CAD.
# 2024-12-31: 6,198.34 USD with the receivable, at 1.4389, are 8,918.79 CAD,
# 800.00 EUR are 1,194.24 CAD, and 3,944.80 CAD: 14,057.83 CAD.
THE_SHEET_IN_CAD_WITHOUT_THE_SOFTWARE = [
    ('2021-06-30', '3995.01', '2746.10', '-87.90', '-49.89'),
    ('2022-06-30', '7302.00', '5843.88', '-111.52', '159.32'),
    ('2023-06-30', '10030.10', '8333.38', '50.14', '397.92'),
    ('2024-06-30', '12232.49', '10338.55', '51.82', '595.14'),
    ('2024-12-31', '14057.83', '11688.95', '51.82', '1070.08'),
]


def _without_the_software(tmp_path, deleted):
    """ACMU's book with the 2021-11-15 software subscription deleted, before the migration or after it."""
    book, _ = _book(tmp_path, WITH_COST_BASES if deleted == 'before-the-migration' else MIGRATED)
    done = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid', THE_SOFTWARE_SUBSCRIPTION)
    assert done.exit_code == 0, done.output
    assert (f'{THE_SOFTWARE_SUBSCRIPTION}: deleted (2021-11-15 "Software subscription, 300.00 USD '
            f'at 1.2517 CAD/USD")') in done.output, done.output
    if deleted == 'before-the-migration':
        migrated = _run(CliRunner(), 'import', str(book), str(FIXTURES / f'{MIGRATES}.txt'))
        assert migrated.exit_code == 0 and 'Errors:       0' in migrated.output, migrated.output
    return book


WHEN_IT_IS_DELETED = ['before-the-migration', 'after-the-migration']


@pytest.mark.parametrize('deleted', WHEN_IT_IS_DELETED)
@pytest.mark.parametrize('as_of, assets, retained, realized, unrealized',
                         THE_SHEET_IN_CAD_WITHOUT_THE_SOFTWARE)
def test_the_balance_sheet_in_cad_after_the_software_subscription_is_deleted(
        tmp_path, deleted, as_of, assets, retained, realized, unrealized):
    """Each year end after the deletion, the same whether it was deleted before the migration or after."""
    book = _without_the_software(tmp_path, deleted)
    assert _sheet(book, 'CAD', as_of) == (assets, assets, retained, realized, unrealized)


@pytest.mark.parametrize('deleted', WHEN_IT_IS_DELETED)
def test_the_year_of_the_deletion_states_no_software_and_14_13_cad_less_loss(tmp_path, deleted):
    """The fiscal year ending 2022-06-30: 23.62 CAD lost where it was 37.75 CAD, and no software expense."""
    book = _without_the_software(tmp_path, deleted)
    assert _income(book, 'CAD', '2022-06-30') == {
        'Income:Sales': '3521.40', 'Income:FX Gain': '-23.62', 'Expenses:Rent': '400.00',
        'net_income': '3097.78'}


@pytest.mark.parametrize('deleted', WHEN_IT_IS_DELETED)
def test_every_account_stores_the_same_whenever_the_subscription_was_deleted(tmp_path, deleted):
    """Chase Chequing holds 5,198.34 USD storing 6,643.75 CAD, and every other currency follows from the first transaction."""
    book = _without_the_software(tmp_path, deleted)
    balances = _balances(book)
    assert balances == {
        'Assets:Chase Chequing': '5198.34 USD, 6643.75 CAD, 35115.44 CNY, 40503.40 HKD, '
                                 '4499.37 EUR, 3881.14 GBP',
        'Assets:Wise EUR': '800.00 EUR, 1048.80 CAD, 796.59 USD, 5499.74 CNY, 6250.30 HKD, '
                           '690.00 GBP',
        'Assets:Accounts Receivable USD': '1000.00 USD, 1350.40 CAD, 7018.71 CNY, 7774.32 HKD, '
                                          '903.46 EUR, 752.65 GBP',
        'Assets:RBC Chequing': '3944.80 CAD, 3045.39 USD, 19785.37 CNY, 23762.82 HKD, '
                               '2758.85 EUR, 2349.27 GBP',
        'Equity:Opening Balances': '-1298.80 CAD, -1000.00 USD, -6964.08 CNY, -7786.57 HKD, '
                                   '-890.63 EUR, -756.26 GBP',
        'Income:Sales': '-12364.80 CAD, -9504.29 USD, -64087.41 CNY, -74131.92 HKD, '
                        '-8503.02 EUR, -7337.56 GBP',
        'Income:FX Gain': '-51.82 CAD, -93.38 USD, -38.64 CNY, -731.17 HKD, -72.03 EUR, -8.96 GBP',
        'Expenses:Rent': '400.00 CAD, 314.99 USD, 1998.18 CNY, 2457.05 HKD, 280.96 EUR, 234.18 GBP',
        'Expenses:Travel': '294.16 CAD, 217.36 USD, 1493.20 CNY, 1706.26 HKD, 200.00 EUR, '
                           '175.87 GBP',
        'Expenses:Bank Fees': '33.51 CAD, 25.00 USD, 179.49 CNY, 195.51 HKD, 23.04 EUR, 19.67 GBP',
    }


@pytest.mark.parametrize('deleted', WHEN_IT_IS_DELETED)
def test_the_book_is_consistent_and_balanced_in_each_currency_after_the_deletion(tmp_path, deleted):
    book = _without_the_software(tmp_path, deleted)
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0 and 'The book is consistent and balanced.' in whole.output, whole.output
    for currency in CURRENCIES:
        for as_of in YEAR_ENDS:
            assets, liabilities_and_equity, *_ = _sheet(book, currency, as_of)
            assert assets == liabilities_and_equity, (currency, as_of)


def test_500_usd_sold_after_the_migration_state_no_cost_basis(tmp_path):
    """500.00 of 4,898.34 USD storing 6,254.11 CAD leave at 638.39 CAD and sell for 724.20 CAD: 85.81 CAD realized.

    The sheet on 2025-02-01, at 1.4484 CAD/USD and 1.5042 CAD/EUR: 5,398.34
    USD with the receivable are worth 7,818.96 CAD, 800.00 EUR are worth
    1,203.36 CAD, and 4,669.00 CAD: 13,691.32 CAD of assets.
    """
    book, _ = _book(tmp_path, MIGRATED + (SELLS_USD,))
    balances = _balances(book)
    assert balances['Assets:Chase Chequing'].startswith('4398.34 USD, 5615.72 CAD, ')
    assert balances['Assets:RBC Chequing'].startswith('4669.00 CAD, ')
    assert balances['Income:FX Gain'].startswith('-123.50 CAD, ')
    assert _sheet(book, 'CAD', '2025-02-01') == (
        '13691.32', '13691.32', '11385.12', '123.50', '1007.40')
