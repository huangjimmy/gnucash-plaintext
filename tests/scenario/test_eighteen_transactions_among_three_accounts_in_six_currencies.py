"""Eighteen transactions among three accounts, with every balance in six currencies after each (Q-057).

The author's case, as the author asked for it:

    you need to have a very detail and long test cases, with a series of
    transactions, and the currencies have CAD USD HKD CNY GBP EUR, it must be
    a long list of transactions among 3 accounts, and assert the balances.
    Also, need to be able to get balance as of date

The case gives the six currencies, three accounts and a long list. Which
accounts and which transactions are the fixtures'. The book is kept in CAD
and selects CAD, USD, HKD, CNY, GBP and EUR. Its three accounts are Chase USD
and Wise USD, both kept in US dollars, and HSBC HKD, kept in Hong Kong
dollars. Its gains go to `Income:FX Gain`, kept in CAD.

Every rate is the Bank of Canada's daily rate for the day, in Canadian
dollars (`three_accounts_1_bank_of_canada_rates_of_2022.txt`):

    day          CAD/USD   CAD/HKD   CAD/CNY   CAD/GBP   CAD/EUR
    2022-01-04   1.2708    0.1630    0.1994    1.7193    1.4347
    2022-01-17   1.2520    0.1607    0.1972    1.7089    1.4281
    2022-02-15   1.2741    0.1633    0.2010    1.7242    1.4468
    2022-03-15   1.2803    0.1636    0.2009    1.6715    1.4039
    2022-04-18   1.2618    0.1609    0.1982    1.6428    1.3614
    2022-05-02   1.2895    0.1643    0.1951    1.6138    1.3556
    2022-06-01   1.2639    0.1611    0.1891    1.5810    1.3485
    2022-07-04   1.2867    0.1640    0.1921    1.5595    1.3424
    2022-08-02   1.2856    0.1638    0.1903    1.5690    1.3109
    2022-09-01   1.3166    0.1678    0.1907    1.5200    1.3110
    2022-09-15   1.3200    0.1682    0.1888    1.5162    1.3196

The eighteen transactions (`three_accounts_2_eighteen_transactions_of_2022.txt`),
each on a day of its own so that the balances can be read after each:

 1. 2022-01-04  Chase USD opens with 10,000.00 USD, 12,708.00 CAD.
 2. 2022-01-17  HSBC HKD opens with 50,000.00 HKD, 8,035.00 CAD.
 3. 2022-02-01  4,000.00 USD move from Chase USD to Wise USD.
 4. 2022-02-15  2,000.00 USD of Chase USD are sold for 15,604.41 HKD.
 5. 2022-03-01  1,000.00 USD move from Wise USD to Chase USD.
 6. 2022-03-15  20,000.00 HKD are sold for 2,555.65 USD, into Wise USD.
 7. 2022-04-01  2,500.00 USD move from Chase USD to Wise USD.
 8. 2022-04-18  3,000.00 USD more arrive in Wise USD, 3,785.40 CAD.
 9. 2022-05-02  5,000.00 USD of Wise USD are sold for 39,242.24 HKD.
10. 2022-05-16  1,234.56 USD move from Wise USD to Chase USD.
11. 2022-06-01  33,333.33 HKD are sold for 4,248.75 USD, into Chase USD.
12. 2022-06-15  3,333.33 USD move from Chase USD to Wise USD.
13. 2022-07-04  1,000.00 USD of Chase USD are sold for 7,845.73 HKD.
14. 2022-07-18  All 8,154.42 USD of Wise USD move to Chase USD.
15. 2022-08-02  All 59,359.05 HKD of HSBC HKD are sold for 7,563.02 USD, into Chase USD.
16. 2022-08-15  5,000.00 USD move from Chase USD to Wise USD.
17. 2022-09-01  2,500.00 USD of Chase USD are sold for 19,615.61 HKD.
18. 2022-09-15  10,000.00 HKD are sold for 1,274.24 USD, into Wise USD.

What each kind does to the balances:

- Money arriving (1, 2, 8) is stored at that day's rates. 10,000.00 USD on
  2022-01-04 are 12,708.00 CAD, and 12,708.00 / 0.1630 = 77,963.19 HKD.
- A move between the two US dollar accounts (3, 5, 7, 10, 12, 14, 16) moves
  the same share of every balance the account stores, and realizes nothing.
  4,000.00 of 10,000.00 USD move 5,083.20 of 12,708.00 CAD. All of an
  account (14) moves all of each balance.
- A sale (4, 6, 9, 11, 13, 15, 17, 18) gives up the share the account
  stores, and what it buys arrives at that day's rates. `Income:FX Gain`
  takes the difference in each currency. In 4, 2,000.00 USD store 2,541.60
  CAD and are worth 2,548.20 CAD at 1.2741 CAD/USD, a gain of 6.60 CAD.

`fx-balances --as-of DATE` lists what each account held at the end of a day,
in every selected currency. Every amount in `AFTER_EACH` was worked out from
the rates above apart from gnucash-plaintext, and what it prints was then
read against them.
"""

from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = Path('tests/fixtures')
RATES = 'three_accounts_1_bank_of_canada_rates_of_2022'
TRANSACTIONS = 'three_accounts_2_eighteen_transactions_of_2022'

# What each account holds at the end of the day of each transaction: its own
# currency first, then CAD, USD, HKD, CNY, GBP and EUR as the book selects
# them. An account holding nothing in any currency is not listed.
OPENING = 'Equity:Opening Balances'
GAIN = 'Income:FX Gain'
CHASE = 'Assets:Chase USD'
WISE = 'Assets:Wise USD'
HSBC = 'Assets:HSBC HKD'
EQUITY_AFTER_2 = '-20743.00 CAD, -16417.73 USD, -127963.19 HKD, -104476.63 CNY, -12093.23 GBP, -14483.96 EUR'
EQUITY_AFTER_8 = '-24528.40 CAD, -19417.73 USD, -151489.60 HKD, -123575.52 CNY, -14397.47 GBP, -17264.48 EUR'
AFTER_EACH = [
    ('2022-01-04', {  # 1. Chase USD opens with 10,000.00 USD
        CHASE: '10000.00 USD, 12708.00 CAD, 77963.19 HKD, 63731.19 CNY, 7391.38 GBP, 8857.60 EUR',
        OPENING: '-12708.00 CAD, -10000.00 USD, -77963.19 HKD, -63731.19 CNY, -7391.38 GBP, -8857.60 EUR',
    }),
    ('2022-01-17', {  # 2. HSBC HKD opens with 50,000.00 HKD
        CHASE: '10000.00 USD, 12708.00 CAD, 77963.19 HKD, 63731.19 CNY, 7391.38 GBP, 8857.60 EUR',
        HSBC: '50000.00 HKD, 8035.00 CAD, 6417.73 USD, 40745.44 CNY, 4701.85 GBP, 5626.36 EUR',
        OPENING: EQUITY_AFTER_2,
    }),
    ('2022-02-01', {  # 3. 4,000.00 USD move from Chase USD to Wise USD
        CHASE: '6000.00 USD, 7624.80 CAD, 46777.91 HKD, 38238.71 CNY, 4434.83 GBP, 5314.56 EUR',
        WISE: '4000.00 USD, 5083.20 CAD, 31185.28 HKD, 25492.48 CNY, 2956.55 GBP, 3543.04 EUR',
        HSBC: '50000.00 HKD, 8035.00 CAD, 6417.73 USD, 40745.44 CNY, 4701.85 GBP, 5626.36 EUR',
        OPENING: EQUITY_AFTER_2,
    }),
    ('2022-02-15', {  # 4. 2,000.00 USD of Chase USD are sold for 15,604.41 HKD
        CHASE: '4000.00 USD, 5083.20 CAD, 31185.27 HKD, 25492.47 CNY, 2956.55 GBP, 3543.04 EUR',
        WISE: '4000.00 USD, 5083.20 CAD, 31185.28 HKD, 25492.48 CNY, 2956.55 GBP, 3543.04 EUR',
        HSBC: '65604.41 HKD, 10583.20 CAD, 8417.73 USD, 53423.05 CNY, 6179.75 GBP, 7387.63 EUR',
        OPENING: EQUITY_AFTER_2,
        GAIN: '-6.60 CAD, 0.00 USD, -11.77 HKD, 68.63 CNY, 0.38 GBP, 10.25 EUR',
    }),
    ('2022-03-01', {  # 5. 1,000.00 USD move from Wise USD to Chase USD
        CHASE: '5000.00 USD, 6354.00 CAD, 38981.59 HKD, 31865.59 CNY, 3695.69 GBP, 4428.80 EUR',
        WISE: '3000.00 USD, 3812.40 CAD, 23388.96 HKD, 19119.36 CNY, 2217.41 GBP, 2657.28 EUR',
        HSBC: '65604.41 HKD, 10583.20 CAD, 8417.73 USD, 53423.05 CNY, 6179.75 GBP, 7387.63 EUR',
        OPENING: EQUITY_AFTER_2,
        GAIN: '-6.60 CAD, 0.00 USD, -11.77 HKD, 68.63 CNY, 0.38 GBP, 10.25 EUR',
    }),
    ('2022-03-15', {  # 6. 20,000.00 HKD are sold for 2,555.65 USD, into Wise USD
        CHASE: '5000.00 USD, 6354.00 CAD, 38981.59 HKD, 31865.59 CNY, 3695.69 GBP, 4428.80 EUR',
        WISE: '5555.65 USD, 7084.40 CAD, 43388.96 HKD, 35406.07 CNY, 4174.93 GBP, 4987.93 EUR',
        HSBC: '45604.41 HKD, 7356.83 CAD, 5851.52 USD, 37136.63 CNY, 4295.81 GBP, 5135.46 EUR',
        OPENING: EQUITY_AFTER_2,
        GAIN: '-52.23 CAD, 10.56 USD, -11.77 HKD, 68.34 CNY, -73.20 GBP, -68.23 EUR',
    }),
    ('2022-04-01', {  # 7. 2,500.00 USD move from Chase USD to Wise USD
        CHASE: '2500.00 USD, 3177.00 CAD, 19490.79 HKD, 15932.79 CNY, 1847.84 GBP, 2214.40 EUR',
        WISE: '8055.65 USD, 10261.40 CAD, 62879.76 HKD, 51338.87 CNY, 6022.78 GBP, 7202.33 EUR',
        HSBC: '45604.41 HKD, 7356.83 CAD, 5851.52 USD, 37136.63 CNY, 4295.81 GBP, 5135.46 EUR',
        OPENING: EQUITY_AFTER_2,
        GAIN: '-52.23 CAD, 10.56 USD, -11.77 HKD, 68.34 CNY, -73.20 GBP, -68.23 EUR',
    }),
    ('2022-04-18', {  # 8. 3,000.00 USD more arrive in Wise USD
        CHASE: '2500.00 USD, 3177.00 CAD, 19490.79 HKD, 15932.79 CNY, 1847.84 GBP, 2214.40 EUR',
        WISE: '11055.65 USD, 14046.80 CAD, 86406.17 HKD, 70437.76 CNY, 8327.02 GBP, 9982.85 EUR',
        HSBC: '45604.41 HKD, 7356.83 CAD, 5851.52 USD, 37136.63 CNY, 4295.81 GBP, 5135.46 EUR',
        OPENING: EQUITY_AFTER_8,
        GAIN: '-52.23 CAD, 10.56 USD, -11.77 HKD, 68.34 CNY, -73.20 GBP, -68.23 EUR',
    }),
    ('2022-05-02', {  # 9. 5,000.00 USD of Wise USD are sold for 39,242.24 HKD
        CHASE: '2500.00 USD, 3177.00 CAD, 19490.79 HKD, 15932.79 CNY, 1847.84 GBP, 2214.40 EUR',
        WISE: '6055.65 USD, 7694.03 CAD, 47328.34 HKD, 38581.76 CNY, 4561.06 GBP, 5468.03 EUR',
        HSBC: '84846.65 HKD, 13804.33 CAD, 10851.52 USD, 70183.79 CNY, 8291.04 GBP, 9891.66 EUR',
        OPENING: EQUITY_AFTER_8,
        GAIN: '-146.96 CAD, 10.56 USD, -176.18 HKD, -1122.82 CNY, -302.47 GBP, -309.61 EUR',
    }),
    ('2022-05-16', {  # 10. 1,234.56 USD move from Wise USD to Chase USD
        CHASE: '3734.56 USD, 4745.58 CAD, 29139.58 HKD, 23798.42 CNY, 2777.70 GBP, 3329.16 EUR',
        WISE: '4821.09 USD, 6125.45 CAD, 37679.55 HKD, 30716.13 CNY, 3631.20 GBP, 4353.27 EUR',
        HSBC: '84846.65 HKD, 13804.33 CAD, 10851.52 USD, 70183.79 CNY, 8291.04 GBP, 9891.66 EUR',
        OPENING: EQUITY_AFTER_8,
        GAIN: '-146.96 CAD, 10.56 USD, -176.18 HKD, -1122.82 CNY, -302.47 GBP, -309.61 EUR',
    }),
    ('2022-06-01', {  # 11. 33,333.33 HKD are sold for 4,248.75 USD, into Chase USD
        CHASE: '7983.31 USD, 10115.58 CAD, 62472.91 HKD, 52196.09 CNY, 6174.28 GBP, 7311.36 EUR',
        WISE: '4821.09 USD, 6125.45 CAD, 37679.55 HKD, 30716.13 CNY, 3631.20 GBP, 4353.27 EUR',
        HSBC: '51513.32 HKD, 8381.08 CAD, 6588.33 USD, 42610.99 CNY, 5033.78 GBP, 6005.57 EUR',
        OPENING: EQUITY_AFTER_8,
        GAIN: '-93.71 CAD, 25.00 USD, -176.18 HKD, -1947.69 CNY, -441.79 GBP, -405.72 EUR',
    }),
    ('2022-06-15', {  # 12. 3,333.33 USD move from Chase USD to Wise USD
        CHASE: '4649.98 USD, 5891.95 CAD, 36388.14 HKD, 30402.27 CNY, 3596.29 GBP, 4258.59 EUR',
        WISE: '8154.42 USD, 10349.08 CAD, 63764.32 HKD, 52509.95 CNY, 6209.19 GBP, 7406.04 EUR',
        HSBC: '51513.32 HKD, 8381.08 CAD, 6588.33 USD, 42610.99 CNY, 5033.78 GBP, 6005.57 EUR',
        OPENING: EQUITY_AFTER_8,
        GAIN: '-93.71 CAD, 25.00 USD, -176.18 HKD, -1947.69 CNY, -441.79 GBP, -405.72 EUR',
    }),
    ('2022-07-04', {  # 13. 1,000.00 USD of Chase USD are sold for 7,845.73 HKD
        CHASE: '3649.98 USD, 4624.86 CAD, 28562.70 HKD, 23864.12 CNY, 2822.89 GBP, 3342.76 EUR',
        WISE: '8154.42 USD, 10349.08 CAD, 63764.32 HKD, 52509.95 CNY, 6209.19 GBP, 7406.04 EUR',
        HSBC: '59359.05 HKD, 9667.78 CAD, 7588.33 USD, 49309.06 CNY, 5858.85 GBP, 6964.08 EUR',
        OPENING: EQUITY_AFTER_8,
        GAIN: '-113.32 CAD, 25.00 USD, -196.47 HKD, -2107.61 CNY, -493.46 GBP, -448.40 EUR',
    }),
    ('2022-07-18', {  # 14. All 8,154.42 USD of Wise USD move to Chase USD
        CHASE: '11804.40 USD, 14973.94 CAD, 92327.02 HKD, 76374.07 CNY, 9032.08 GBP, 10748.80 EUR',
        HSBC: '59359.05 HKD, 9667.78 CAD, 7588.33 USD, 49309.06 CNY, 5858.85 GBP, 6964.08 EUR',
        OPENING: EQUITY_AFTER_8,
        GAIN: '-113.32 CAD, 25.00 USD, -196.47 HKD, -2107.61 CNY, -493.46 GBP, -448.40 EUR',
    }),
    ('2022-08-02', {  # 15. All 59,359.05 HKD of HSBC HKD are sold for 7,563.02 USD
        CHASE: '19367.42 USD, 24696.95 CAD, 151686.07 HKD, 127467.15 CNY, 15229.03 GBP, 18165.85 EUR',
        OPENING: EQUITY_AFTER_8,
        GAIN: '-168.55 CAD, 50.31 USD, -196.47 HKD, -3891.63 CNY, -831.56 GBP, -901.37 EUR',
    }),
    ('2022-08-15', {  # 16. 5,000.00 USD move from Chase USD to Wise USD
        CHASE: '14367.42 USD, 18321.05 CAD, 112525.96 HKD, 94559.53 CNY, 11297.42 GBP, 13476.05 EUR',
        WISE: '5000.00 USD, 6375.90 CAD, 39160.11 HKD, 32907.62 CNY, 3931.61 GBP, 4689.80 EUR',
        OPENING: EQUITY_AFTER_8,
        GAIN: '-168.55 CAD, 50.31 USD, -196.47 HKD, -3891.63 CNY, -831.56 GBP, -901.37 EUR',
    }),
    ('2022-09-01', {  # 17. 2,500.00 USD of Chase USD are sold for 19,615.61 HKD
        CHASE: '11867.42 USD, 15133.10 CAD, 92945.90 HKD, 78105.72 CNY, 9331.61 GBP, 11131.15 EUR',
        WISE: '5000.00 USD, 6375.90 CAD, 39160.11 HKD, 32907.62 CNY, 3931.61 GBP, 4689.80 EUR',
        HSBC: '19615.61 HKD, 3291.50 CAD, 2500.00 USD, 17260.09 CNY, 2165.46 GBP, 2510.68 EUR',
        OPENING: EQUITY_AFTER_8,
        GAIN: '-272.10 CAD, 50.31 USD, -232.02 HKD, -4697.91 CNY, -1031.21 GBP, -1067.15 EUR',
    }),
    ('2022-09-15', {  # 18. 10,000.00 HKD are sold for 1,274.24 USD, into Wise USD
        CHASE: '11867.42 USD, 15133.10 CAD, 92945.90 HKD, 78105.72 CNY, 9331.61 GBP, 11131.15 EUR',
        WISE: '6274.24 USD, 8057.90 CAD, 49160.11 HKD, 41816.52 CNY, 5040.96 GBP, 5964.43 EUR',
        HSBC: '9615.61 HKD, 1613.50 CAD, 1225.50 USD, 8460.93 CNY, 1061.51 GBP, 1230.74 EUR',
        OPENING: EQUITY_AFTER_8,
        GAIN: '-276.10 CAD, 50.57 USD, -232.02 HKD, -4807.65 CNY, -1036.61 GBP, -1061.84 EUR',
    }),
]


@pytest.fixture(scope='module')
def book(tmp_path_factory):
    """The book after its rates and its eighteen transactions."""
    path = tmp_path_factory.mktemp('three-accounts') / 'book.gnucash'
    for number, step in enumerate((RATES, TRANSACTIONS)):
        args = ['import', str(path), str(FIXTURES / f'{step}.txt')]
        if number == 0:
            args.insert(1, '--new')
        done = _run(CliRunner(), *args)
        assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return path


def _as_of(book, date):
    """What `fx-balances --as-of` lists for each account at the end of `date`."""
    listing = _run(CliRunner(), 'fx-balances', str(book), '--as-of', date)
    assert listing.exit_code == 0, listing.output
    lines = listing.output.splitlines()
    assert lines[1] == f'As of {date}:', listing.output
    return dict(line.split(': ', 1) for line in lines[2:])


@pytest.mark.parametrize('date, held', AFTER_EACH, ids=[date for date, _ in AFTER_EACH])
def test_what_each_account_holds_in_each_currency_after_each_transaction(book, date, held):
    assert _as_of(book, date) == held


@pytest.mark.parametrize('date', [date for date, _ in AFTER_EACH])
def test_every_currency_adds_up_to_zero_across_the_accounts_on_each_day(book, date):
    totals = {}
    for each in _as_of(book, date).values():
        for amount in each.split(', '):
            figure, code = amount.split(' ')
            totals[code] = totals.get(code, Fraction(0)) + Fraction(figure)
    assert totals == dict.fromkeys(('CAD', 'USD', 'HKD', 'CNY', 'GBP', 'EUR'), 0)


def test_the_day_before_a_transaction_states_what_the_one_before_it_left(book):
    """2022-05-15, the day before the 1,234.56 USD move, is as the sale of 2022-05-02 left it."""
    assert _as_of(book, '2022-05-15') == dict(AFTER_EACH)['2022-05-02']


def test_before_the_first_transaction_no_account_holds_anything(book):
    assert _as_of(book, '2022-01-03') == {}


def test_as_the_book_stands_is_as_of_its_last_transaction(book):
    """Without `--as-of`, `fx-balances` lists what each account stores now."""
    listing = _run(CliRunner(), 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    assert dict(line.split(': ', 1) for line in listing.output.splitlines()[1:]) == AFTER_EACH[-1][1]


def test_the_book_is_consistent_and_balanced(book):
    whole = _run(CliRunner(), '--verify-integrity', str(book))
    assert whole.exit_code == 0 and 'The book is consistent and balanced.' in whole.output, whole.output
