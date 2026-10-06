"""ACME LLC keeps a balance in USD, CAD, CNY, HKD, EUR and GBP on every account (Q-057).

The author's case, as the author wrote it:

    User A has a company called ACME LLC, fiscal year ending 06-30 each year
    ACME has a book in base currency USD, A choose USD CAD CNY HKD EUR GBP as supported currencies
    On 2020-01-01, ACME has an opening transaction to initialize book
    Chase Chequing 1000 USD (all other currencies balance derived on 2020-01-01 FX rate)
    until 2020-02-02, there were no new transactions, now you should test and verify
    that income statement/balance sheet should show no realized/unrealized gain at all!

    Even if balance sheet / income statement will be in CAD CNY HKD EUR GBP, there should
    be no realized/unrealized gain!!

    on 2021-01-01 ACME invoiced its customers ABC 1000 USD, ABC Europe 1000 EUR
    on 2021-03-03 ACME received payments from both ABC and ABC Europe in full
    on 2021-06-01 ACME disposed 1000 EUR for USD

    You shall test income statement/balance sheet before and after all 3 dates above in USD.
    You shall also test income statement / balance sheet in CAD CNY HKD EUR GBP

And on the rates: "if you know the tx date, you should know the rate on that
day". The book's prices are the Bank of Canada's daily rates, each in
Canadian dollars, as it published them for the day of each transaction. It
publishes none on 1 January, so those two transactions take the rate of 31
December:

    day          CAD/USD   CAD/EUR   CAD/CNY   CAD/HKD   CAD/GBP
    2019-12-31   1.2988    1.4583    0.1865    0.1668    1.7174
    2020-12-31   1.2732    1.5608    0.1949    0.1642    1.7381
    2021-03-03   1.2631    1.5240    0.1953    0.1628    1.7636
    2021-06-01   1.2040    1.4729    0.1887    0.1552    1.7057

A rate between two of those currencies is one divided by the other: 1,000.00
USD on 2019-12-31 are 1,298.80 CAD, and 1,298.80 / 0.1865 = 6,964.08 CNY.

Step 1, `tests/fixtures/acme_1_opens_with_1000_usd_in_chase_chequing_on_2020_01_01.txt`.
Chase Chequing holds 1,000.00 USD, and stores 1,298.80 CAD, 6,964.08 CNY,
7,786.57 HKD, 890.63 EUR and 756.26 GBP.

Step 2, `acme_2_invoices_abc_1000_usd_and_abc_europe_1000_eur_and_is_paid_in_full.txt`.
On 2021-01-01 INV-ABC is posted for 1,000.00 USD and INV-ABC-EU for 1,000.00
EUR, which is 1,225.89 USD of sales at 1.5608 CAD/EUR and 1.2732 CAD/USD. On
2021-03-03 ABC pays 1,000.00 USD into Chase Chequing and ABC Europe pays
1,000.00 EUR into Wise EUR. Each payment moves what the receivable stored.

Step 3, `acme_3_sells_1000_eur_for_1223_34_usd_on_2021_06_01.txt`. The
1,000.00 EUR are sold for 1,223.34 USD, at 1.4729 CAD/EUR and 1.2040 CAD/USD.
They were stored at 1,225.89 USD, so the sale realizes a loss of 2.55 USD. In
CAD the EUR were stored at 1,560.80 and sold for 1,472.90, a loss of 87.90
CAD. The loss is 202.70 CNY, 15.14 HKD and 34.47 GBP, and nothing in EUR.

Then one transaction in the middle of the year is deleted, which the author
asked for after the first three steps were tested:

    gnucash allow deletion of any transactions, but the scenario test dont
    cover this!!!, must extend the ACME and ACMU scenaris with deleting 1
    transaction in the middle of the year, then what happen? there will be
    cascading effect to all balances!!!

`delete-transactions` removes the 2021-03-03 payment of ABC Europe. Every
balance after it changes:

- The receivable holds its 1,000.00 EUR again, with the 1,225.89 USD,
  1,560.80 CAD and the rest it stored.
- Wise EUR never received them, so the sale of 2021-06-01 takes it to
  1,000.00 EUR owed, at that day's amounts: 1,472.90 CAD.
- The sale now exchanges euros the account did not hold for their worth of
  the day, so in CAD it realizes nothing where it realized a loss of 87.90
  CAD. The 87.90 CAD is still lost, on the receivable, and not yet realized:
  the sheet in CAD states 251.90 CAD unrealized where it stated 164.00 CAD.
- In USD the sale states what it stated, 1,225.89 USD of euros for 1,223.34
  USD, and still realizes the 2.55 USD.

Every amount here was worked out from the table above apart from
gnucash-plaintext, and the statements it prints were then read against them.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')
OPENS = 'acme_1_opens_with_1000_usd_in_chase_chequing_on_2020_01_01'
INVOICES = 'acme_2_invoices_abc_1000_usd_and_abc_europe_1000_eur_and_is_paid_in_full'
SELLS_EUR = 'acme_3_sells_1000_eur_for_1223_34_usd_on_2021_06_01'


def _book(tmp_path, *steps):
    book = tmp_path / 'book.gnucash'
    for number, step in enumerate(steps):
        args = ['import', str(book), str(FIXTURES / f'{step}.txt'), '--include-business-objects']
        if number == 0:
            args.insert(1, '--new')
        done = _run(CliRunner(), *args)
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return book


def _sheet(book, currency, as_of):
    """The balance sheet's totals in `currency` at the end of `as_of`: assets, liabilities and equity, realized, unrealized."""
    page = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', as_of, '--currency', currency)
    assert page.exit_code == 0, page.output
    keys = dict(re.findall(rf'^\t([a-z_]+): (-?[\d.]+) {currency}', page.output, re.M))
    return (keys['total_assets'], keys['total_liabilities_and_equity'],
            keys['total_realized_gains'], keys['total_unrealized_gains'])


def _income(book, currency, *period):
    """The income statement's account lines and net income in `currency` over a period."""
    page = _run(CliRunner(), 'income-statement', str(book), '--currency', currency, *period)
    assert page.exit_code == 0, page.output
    lines = dict(re.findall(rf'^\t(Income:\S+(?: \S+)*?) (-?[\d.]+) {currency}$', page.output, re.M))
    lines['net_income'] = re.search(rf'^\tnet_income: (-?[\d.]+) {currency}', page.output, re.M).group(1)
    return lines


@pytest.mark.parametrize('currency, assets', [
    ('USD', '1000.00'), ('CAD', '1298.80'), ('CNY', '6964.08'),
    ('HKD', '7786.57'), ('EUR', '890.63'), ('GBP', '756.26')])
def test_until_2020_02_02_no_statement_shows_a_realized_or_an_unrealized_gain(tmp_path, currency, assets):
    """With only the opening 1,000.00 USD in the book, the sheet in each currency states no gain, and the income statement nothing."""
    book = _book(tmp_path, OPENS)
    assert _sheet(book, currency, '2020-02-02') == (assets, assets, '0.00', '0.00')
    assert _income(book, currency, '--fiscal-year-end', '2020-06-30') == {'net_income': '0.00'}
    assert _income(book, currency, '--start', '2020-01-01', '--end', '2020-02-02') == {
        'net_income': '0.00'}


def test_chase_chequing_stores_what_1000_usd_were_on_2020_01_01(tmp_path):
    listing = _run(CliRunner(), 'fx-balances', str(_book(tmp_path, OPENS)))
    assert ('Assets:Chase Chequing: 1000.00 USD, 1298.80 CAD, 6964.08 CNY, 7786.57 HKD, '
            '890.63 EUR, 756.26 GBP') in listing.output, listing.output


@pytest.mark.parametrize('as_of, assets, realized, unrealized', [
    # Before the invoices: the opening 1,000.00 USD.
    ('2020-12-31', '1000.00', '0.00', '0.00'),
    # The invoices posted: 1,000.00 USD in the bank, 1,000.00 USD receivable,
    # and 1,000.00 EUR receivable worth the 1,225.89 USD it stores.
    ('2021-01-01', '3225.89', '0.00', '0.00'),
    # At the rates of 2021-03-03, 1,000.00 EUR are worth 1,206.56 USD, 19.33
    # USD less than they store. The book's price nearest the end of
    # 2021-03-02 is the one of 2021-03-03.
    ('2021-03-02', '3206.56', '0.00', '-19.33'),
    # Paid in full: 2,000.00 USD in the bank and 1,000.00 EUR.
    ('2021-03-03', '3206.56', '0.00', '-19.33'),
    # The day before the sale, at the rates of 2021-06-01: the 1,000.00 EUR
    # are worth 1,223.34 USD and store 1,225.89 USD, 2.55 USD not yet realized.
    ('2021-05-31', '3223.34', '0.00', '-2.55'),
    # Sold: 3,223.34 USD in the bank, and the 2.55 USD realized.
    ('2021-06-01', '3223.34', '-2.55', '0.00'),
])
def test_the_balance_sheet_in_usd_before_and_after_each_date(tmp_path, as_of, assets, realized, unrealized):
    book = _book(tmp_path, OPENS, INVOICES, SELLS_EUR)
    assert _sheet(book, 'USD', as_of) == (assets, assets, realized, unrealized)


@pytest.mark.parametrize('period, lines', [
    (('--start', '2020-07-01', '--end', '2020-12-31'), {'net_income': '0.00'}),
    (('--start', '2020-07-01', '--end', '2021-01-01'),
     {'Income:Sales': '2225.89', 'net_income': '2225.89'}),
    (('--start', '2020-07-01', '--end', '2021-03-03'),
     {'Income:Sales': '2225.89', 'net_income': '2225.89'}),
    (('--start', '2020-07-01', '--end', '2021-05-31'),
     {'Income:Sales': '2225.89', 'net_income': '2225.89'}),
    (('--start', '2020-07-01', '--end', '2021-06-01'),
     {'Income:Sales': '2225.89', 'Income:FX Gain': '-2.55', 'net_income': '2223.34'}),
    (('--fiscal-year-end', '2021-06-30'),
     {'Income:Sales': '2225.89', 'Income:FX Gain': '-2.55', 'net_income': '2223.34'}),
], ids=['before-the-invoices', 'invoiced', 'paid', 'before-the-sale', 'sold', 'the-fiscal-year'])
def test_the_income_statement_in_usd_before_and_after_each_date(tmp_path, period, lines):
    """1,000.00 USD and 1,225.89 USD of sales, and the 2.55 USD lost on the EUR."""
    book = _book(tmp_path, OPENS, INVOICES, SELLS_EUR)
    assert _income(book, 'USD', *period) == lines


@pytest.mark.parametrize('currency, as_of, assets, realized, unrealized', [
    # 2021-01-01, the invoices posted, at the rates of 2020-12-31. Chase
    # Chequing's 1,000.00 USD are worth 1,273.20 CAD and store 1,298.80 CAD
    # from 2019-12-31, 25.60 CAD less. Both receivables are worth what they
    # store.
    ('CAD', '2021-01-01', '4107.20', '0.00', '-25.60'),
    ('CNY', '2021-01-01', '21073.37', '0.00', '-431.50'),
    ('HKD', '2021-01-01', '25013.40', '0.00', '-32.61'),
    ('EUR', '2021-01-01', '2631.47', '0.00', '-74.90'),
    ('GBP', '2021-01-01', '2363.04', '0.00', '-23.73'),
    # 2021-03-03, paid in full, at that day's rates.
    ('CAD', '2021-03-03', '4050.20', '0.00', '-82.60'),
    ('CNY', '2021-03-03', '20738.35', '0.00', '-766.52'),
    ('HKD', '2021-03-03', '24878.38', '0.00', '-167.63'),
    ('EUR', '2021-03-03', '2657.61', '0.00', '-48.76'),
    ('GBP', '2021-03-03', '2296.55', '0.00', '-90.22'),
    # 2021-06-01, the EUR sold. Chase Chequing's 3,223.34 USD at that day's
    # rates, against the 4,044.90 CAD, 21,302.17 CNY, 25,030.87 HKD, 2,706.37
    # EUR and 2,352.30 GBP they store.
    ('CAD', '2021-06-01', '3880.90', '-87.90', '-164.00'),
    ('CNY', '2021-06-01', '20566.51', '-202.70', '-735.66'),
    ('HKD', '2021-06-01', '25005.81', '-15.14', '-25.06'),
    ('EUR', '2021-06-01', '2634.87', '0.00', '-71.50'),
    ('GBP', '2021-06-01', '2275.25', '-34.47', '-77.05'),
])
def test_the_balance_sheet_in_each_other_currency(tmp_path, currency, as_of, assets, realized, unrealized):
    book = _book(tmp_path, OPENS, INVOICES, SELLS_EUR)
    assert _sheet(book, currency, as_of) == (assets, assets, realized, unrealized)


@pytest.mark.parametrize('currency, lines', [
    ('CAD', {'Income:Sales': '2834.00', 'Income:FX Gain': '-87.90', 'net_income': '2746.10'}),
    ('CNY', {'Income:Sales': '14540.79', 'Income:FX Gain': '-202.70', 'net_income': '14338.09'}),
    ('HKD', {'Income:Sales': '17259.44', 'Income:FX Gain': '-15.14', 'net_income': '17244.30'}),
    ('EUR', {'Income:Sales': '1815.74', 'net_income': '1815.74'}),
    ('GBP', {'Income:Sales': '1630.51', 'Income:FX Gain': '-34.47', 'net_income': '1596.04'}),
])
def test_the_income_statement_of_the_fiscal_year_in_each_other_currency(tmp_path, currency, lines):
    """The sales at what they were in each currency on their day, and the loss on the EUR in each.

    1,000.00 USD of sales are 1,273.20 CAD and 1,000.00 EUR of sales are
    1,560.80 CAD, 2,834.00 CAD together. The EUR were sold for what they were
    stored at in EUR, so the statement in EUR has no line for a gain.
    """
    book = _book(tmp_path, OPENS, INVOICES, SELLS_EUR)
    assert _income(book, currency, '--fiscal-year-end', '2021-06-30') == lines


THE_PAYMENT_OF_ABC_EUROPE = '0d580000000000000000000000000024'


def _without_the_payment_of_abc_europe(tmp_path):
    """ACME's book after its three steps, with the 2021-03-03 payment of ABC Europe deleted."""
    book = _book(tmp_path, OPENS, INVOICES, SELLS_EUR)
    done = _run(CliRunner(), 'delete-transactions', str(book), '--by-guid', THE_PAYMENT_OF_ABC_EUROPE)
    assert done.exit_code == 0, done.output
    assert f'{THE_PAYMENT_OF_ABC_EUROPE}: deleted (2021-03-03 "ABC Europe")' in done.output, done.output
    return book


def test_deleting_the_payment_of_abc_europe_changes_every_balance_after_it(tmp_path):
    """The receivable holds its 1,000.00 EUR again, and the sale leaves Wise EUR owing 1,000.00 EUR."""
    listing = _run(CliRunner(), 'fx-balances', str(_without_the_payment_of_abc_europe(tmp_path)))
    assert listing.output.splitlines()[1:] == [
        'Assets:Chase Chequing: 3223.34 USD, 4044.90 CAD, 21302.18 CNY, 25030.87 HKD, '
        '2706.37 EUR, 2352.30 GBP',
        'Assets:Wise EUR: -1000.00 EUR, -1225.89 USD, -1472.90 CAD, -7805.51 CNY, -9490.34 HKD, '
        '-863.52 GBP',
        'Assets:Accounts Receivable EUR: 1000.00 EUR, 1225.89 USD, 1560.80 CAD, 8008.21 CNY, '
        '9505.48 HKD, 897.99 GBP',
        'Equity:Opening Balances: -1000.00 USD, -1298.80 CAD, -6964.08 CNY, -7786.57 HKD, '
        '-890.63 EUR, -756.26 GBP',
        'Income:Sales: -2225.89 USD, -2834.00 CAD, -14540.79 CNY, -17259.44 HKD, '
        '-1815.74 EUR, -1630.51 GBP',
        'Income:FX Gain: 2.55 USD, 0.00 CAD, -0.01 CNY, 0.00 HKD, 0.00 EUR, 0.00 GBP',
    ]


@pytest.mark.parametrize('currency, as_of, assets, realized, unrealized', [
    # 2021-03-03: the payment is gone, and the receivable is worth what Wise
    # EUR was, so each sheet states what it stated with the payment.
    ('USD', '2021-03-03', '3206.56', '0.00', '-19.33'),
    ('CAD', '2021-03-03', '4050.20', '0.00', '-82.60'),
    ('CNY', '2021-03-03', '20738.35', '0.00', '-766.52'),
    ('HKD', '2021-03-03', '24878.38', '0.00', '-167.63'),
    ('EUR', '2021-03-03', '2657.61', '0.00', '-48.76'),
    ('GBP', '2021-03-03', '2296.55', '0.00', '-90.22'),
    # 2021-06-01: the same assets as with the payment, 1,000.00 EUR
    # receivable against 1,000.00 EUR owed. What the sale realized with the
    # payment is now unrealized: in CAD 0.00 and -251.90 where it was -87.90
    # and -164.00.
    ('USD', '2021-06-01', '3223.34', '-2.55', '0.00'),
    ('CAD', '2021-06-01', '3880.90', '0.00', '-251.90'),
    ('CNY', '2021-06-01', '20566.51', '0.01', '-938.37'),
    ('HKD', '2021-06-01', '25005.81', '0.00', '-40.20'),
    ('EUR', '2021-06-01', '2634.87', '0.00', '-71.50'),
    ('GBP', '2021-06-01', '2275.25', '0.00', '-111.52'),
])
def test_the_balance_sheet_after_the_payment_is_deleted(tmp_path, currency, as_of, assets, realized,
                                                       unrealized):
    book = _without_the_payment_of_abc_europe(tmp_path)
    assert _sheet(book, currency, as_of) == (assets, assets, realized, unrealized)


def test_the_income_statement_after_the_payment_is_deleted(tmp_path):
    """The sales are what they were. The loss on the EUR is 2.55 USD still, and nothing in CAD."""
    book = _without_the_payment_of_abc_europe(tmp_path)
    assert _income(book, 'USD', '--fiscal-year-end', '2021-06-30') == {
        'Income:Sales': '2225.89', 'Income:FX Gain': '-2.55', 'net_income': '2223.34'}
    assert _income(book, 'CAD', '--fiscal-year-end', '2021-06-30') == {
        'Income:Sales': '2834.00', 'net_income': '2834.00'}


def test_the_book_is_consistent_and_balanced_after_the_payment_is_deleted(tmp_path):
    whole = _run(CliRunner(), '--verify-integrity', str(_without_the_payment_of_abc_europe(tmp_path)))
    assert whole.exit_code == 0 and 'The book is consistent and balanced.' in whole.output, whole.output


def test_what_each_account_holds_after_the_eur_are_sold(tmp_path):
    listing = _run(CliRunner(), 'fx-balances', str(_book(tmp_path, OPENS, INVOICES, SELLS_EUR)))
    assert listing.output.splitlines()[1:] == [
        'Assets:Chase Chequing: 3223.34 USD, 4044.90 CAD, 21302.17 CNY, 25030.87 HKD, '
        '2706.37 EUR, 2352.30 GBP',
        'Equity:Opening Balances: -1000.00 USD, -1298.80 CAD, -6964.08 CNY, -7786.57 HKD, '
        '-890.63 EUR, -756.26 GBP',
        'Income:Sales: -2225.89 USD, -2834.00 CAD, -14540.79 CNY, -17259.44 HKD, '
        '-1815.74 EUR, -1630.51 GBP',
        'Income:FX Gain: 2.55 USD, 87.90 CAD, 202.70 CNY, 15.14 HKD, 0.00 EUR, 34.47 GBP',
    ]
