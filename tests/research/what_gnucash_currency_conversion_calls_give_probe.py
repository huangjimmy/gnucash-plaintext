"""What GnuCash's own currency conversion calls give on a multi-currency book, on this build (Q-042).

The book, all in 2026, kept in CAD:

- USD Bank: 3000.00 USD opened on 01-03, less 2000.00 USD paid for AMZN on 01-04.
- HKD Bank: 5500.00 HKD opened on 01-03.
- AMZN: 10 shares bought on 01-04 for 2000.00 USD.

Prices:

- USD in CAD: 1.30 on 01-02, 1.40 on 02-02 (both at 12:00 UTC).
- HKD: stored the other way round only, CAD in HKD 5.5 on 01-10.
- AMZN in USD: 210 on 01-15, 220 on 02-15.

Asked as of the end of 01-25 (the nearest USD price, 02-02, is after the date;
the latest before it is 01-02), 02-10 (the nearest AMZN price, 02-15, is after
it) and 03-01 (every price is before it).

Every call goes through ctypes: SWIG misreads a date given as seconds on 3.4
(CLAUDE.md finding 20).

Run: ./scripts/run.sh <tag> env PYTHONPATH=/workspace python3 tests/research/what_gnucash_currency_conversion_calls_give_probe.py
"""

import calendar
import ctypes
import os
import tempfile
from fractions import Fraction

from gnucash import (
    ACCT_TYPE_BANK,
    ACCT_TYPE_EQUITY,
    ACCT_TYPE_STOCK,
    Account,
    GncCommodity,
    GncNumeric,
    Split,
    Transaction,
)

from infrastructure.gnucash.engine import GncNumericC, load_gnc_engine
from infrastructure.gnucash.utils import qof_pointer
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.integration.prices_in_a_book import add_prices


def utc(year, month, day, hour=0, minute=0, second=0):
    return calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))


def build(path):
    repo = GnuCashRepository(path)
    repo.open(SessionMode.NEW)
    book = repo.book
    table = book.get_table()
    usd = table.lookup('CURRENCY', 'USD')
    hkd = table.lookup('CURRENCY', 'HKD')
    table.insert(GncCommodity(book, 'Amazon.com Inc', 'NASDAQ', 'AMZN', '', 10000))
    amzn = table.lookup('NASDAQ', 'AMZN')
    root = book.get_root_account()

    def account(name, kind, commodity):
        made = Account(book)
        made.BeginEdit()
        made.SetName(name)
        made.SetType(kind)
        made.SetCommodity(commodity)
        root.append_child(made)
        made.CommitEdit()
        return made

    usd_bank = account('USD Bank', ACCT_TYPE_BANK, usd)
    hkd_bank = account('HKD Bank', ACCT_TYPE_BANK, hkd)
    stock = account('AMZN', ACCT_TYPE_STOCK, amzn)
    opening_usd = account('Opening USD', ACCT_TYPE_EQUITY, usd)
    opening_hkd = account('Opening HKD', ACCT_TYPE_EQUITY, hkd)

    def transaction(day, month, currency, splits):
        made = Transaction(book)
        made.BeginEdit()
        made.SetCurrency(currency)
        made.SetDate(day, month, 2026)
        for target, value, amount in splits:
            split = Split(book)
            split.SetParent(made)
            split.SetAccount(target)
            split.SetValue(GncNumeric(*value))
            split.SetAmount(GncNumeric(*amount))
        made.CommitEdit()

    transaction(3, 1, usd, [(usd_bank, (300000, 100), (300000, 100)),
                            (opening_usd, (-300000, 100), (-300000, 100))])
    transaction(3, 1, hkd, [(hkd_bank, (550000, 100), (550000, 100)),
                            (opening_hkd, (-550000, 100), (-550000, 100))])
    transaction(4, 1, usd, [(stock, (200000, 100), (100000, 10000)),
                            (usd_bank, (-200000, 100), (-200000, 100))])
    repo.save()
    repo.close()
    add_prices(path, [
        {'commodity': 'CURRENCY:USD', 'currency': 'CAD', 'time': utc(2026, 1, 2, 12), 'value': '13/10',
         'source': 'user:price-editor', 'type': 'last'},
        {'commodity': 'CURRENCY:USD', 'currency': 'CAD', 'time': utc(2026, 2, 2, 12), 'value': '14/10',
         'source': 'user:price-editor', 'type': 'last'},
        {'commodity': 'CURRENCY:CAD', 'currency': 'HKD', 'time': utc(2026, 1, 10, 12), 'value': '55/10',
         'source': 'user:price-editor', 'type': 'last'},
        {'commodity': 'NASDAQ:AMZN', 'currency': 'USD', 'time': utc(2026, 1, 15, 12), 'value': '210',
         'source': 'user:price-editor', 'type': 'last'},
        {'commodity': 'NASDAQ:AMZN', 'currency': 'USD', 'time': utc(2026, 2, 15, 12), 'value': '220',
         'source': 'user:price-editor', 'type': 'last'},
    ])


def shown(numeric):
    if numeric.denom == 0:
        return f'{numeric.num}/0 (no answer)'
    return f'{numeric.num}/{numeric.denom} (= {Fraction(numeric.num, numeric.denom)})'


def declare(lib):
    lib.xaccAccountGetBalanceAsOfDate.restype = GncNumericC
    lib.xaccAccountGetBalanceAsOfDate.argtypes = [ctypes.c_void_p, ctypes.c_int64]
    lib.xaccAccountGetBalanceAsOfDateInCurrency.restype = GncNumericC
    lib.xaccAccountGetBalanceAsOfDateInCurrency.argtypes = [
        ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p, ctypes.c_int]
    lib.xaccAccountConvertBalanceToCurrencyAsOfDate.restype = GncNumericC
    lib.xaccAccountConvertBalanceToCurrencyAsOfDate.argtypes = [
        ctypes.c_void_p, GncNumericC, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64]
    lib.gnc_pricedb_convert_balance_nearest_price_t64.restype = GncNumericC
    lib.gnc_pricedb_convert_balance_nearest_price_t64.argtypes = [
        ctypes.c_void_p, GncNumericC, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64]
    lib.gnc_pricedb_convert_balance_latest_price.restype = GncNumericC
    lib.gnc_pricedb_convert_balance_latest_price.argtypes = [
        ctypes.c_void_p, GncNumericC, ctypes.c_void_p, ctypes.c_void_p]
    lib.xaccAccountGetCommodity.restype = ctypes.c_void_p
    lib.xaccAccountGetCommodity.argtypes = [ctypes.c_void_p]


def main():
    lib = load_gnc_engine()
    declare(lib)
    print(f'GnuCash {lib.gnc_version().decode()}, TZ={os.environ.get("TZ")!r}')
    path = os.path.join(tempfile.mkdtemp(), 'book.gnucash')
    build(path)

    repo = GnuCashRepository(path)
    repo.open(SessionMode.NORMAL)
    try:
        book = repo.book
        table = book.get_table()
        cad = qof_pointer(table.lookup('CURRENCY', 'CAD'))
        db = lib.gnc_pricedb_get_db(qof_pointer(book))
        accounts = {child.GetName(): child for child in book.get_root_account().get_children()}
        for when in ((2026, 1, 25), (2026, 2, 10), (2026, 3, 1)):
            t = utc(*when, 23, 59, 59)
            print(f'as of the end of {when[0]}-{when[1]:02d}-{when[2]:02d}:')
            for name in ('USD Bank', 'HKD Bank', 'AMZN'):
                account = qof_pointer(accounts[name])
                own = lib.xaccAccountGetCommodity(account)
                balance = lib.xaccAccountGetBalanceAsOfDate(account, t)
                print(f'  {name}: balance {shown(balance)}')
                print(f'    GetBalanceAsOfDateInCurrency CAD:            '
                      f'{shown(lib.xaccAccountGetBalanceAsOfDateInCurrency(account, t, cad, 0))}')
                print(f'    ConvertBalanceToCurrencyAsOfDate CAD:        '
                      f'{shown(lib.xaccAccountConvertBalanceToCurrencyAsOfDate(account, balance, own, cad, t))}')
                print(f'    pricedb convert_balance_nearest_price CAD:   '
                      f'{shown(lib.gnc_pricedb_convert_balance_nearest_price_t64(db, balance, own, cad, t))}')
                print(f'    pricedb convert_balance_latest_price CAD:    '
                      f'{shown(lib.gnc_pricedb_convert_balance_latest_price(db, balance, own, cad))}')
    finally:
        repo.close()


if __name__ == '__main__':
    main()
