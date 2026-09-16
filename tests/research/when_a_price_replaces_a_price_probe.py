"""Probe: when does a second price replace the first, and does a price added
to an existing book reach disk when nothing else in the session changed?

Also: does a price of two currencies one way round replace a price of the same
two the other way round (USD in HKD against HKD in USD), when added and when an
edit moves one onto the other's day?

Run under TZ=America/Toronto so a local day and a UTC day differ:
  docker run --rm -e TZ=America/Toronto -v "$PWD:/workspace" -w /workspace \
      gnucash-dev:<tag> python3 tests/research/when_a_price_replaces_a_price_probe.py
"""

import os
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, '/workspace')

import gnucash  # noqa: E402
from gnucash import Account, GncNumeric, GncPrice, Session  # noqa: E402
from gnucash.gnucash_core_c import (  # noqa: E402
    ACCT_TYPE_BANK,
    gnc_pricedb_add_price,
    gnc_pricedb_get_db,
    gnc_pricedb_get_prices,
    qof_book_session_not_saved,
)

# The suite's `_patch_session_save`: every save deletes the backup a save in
# the same second would collide with.
import tests.conftest  # noqa: E402,F401
from infrastructure.gnucash.engine import load_gnc_engine  # noqa: E402


def qof_book_mark_session_dirty(book_instance):
    # Not in SWIG on any build; the repo's own ctypes declaration.
    load_gnc_engine().qof_book_mark_session_dirty(int(book_instance))


def session(path, mode):
    if hasattr(gnucash, 'SessionOpenMode'):
        return Session(path, getattr(gnucash.SessionOpenMode, mode))
    if mode == 'SESSION_NEW_STORE':
        return Session(path, is_new=True)
    if mode == 'SESSION_READ_ONLY':
        return Session(path, ignore_lock=True)
    return Session(path)


def add_price(book, mnemonic, when, source, num, denom,
              namespace='CURRENCY', currency='CAD'):
    table = book.get_table()
    price = GncPrice(book)
    price.set_commodity(table.lookup(namespace, mnemonic))
    price.set_currency(table.lookup('CURRENCY', currency))
    price.set_time64(when)
    price.set_source_string(source)
    price.set_typestr('last')
    price.set_value(GncNumeric(num, denom))
    return gnc_pricedb_add_price(gnc_pricedb_get_db(book.instance), price.instance)


def prices(book, mnemonic, namespace='CURRENCY', currency='CAD'):
    table = book.get_table()
    raws = gnc_pricedb_get_prices(
        gnc_pricedb_get_db(book.instance),
        table.lookup(namespace, mnemonic).instance,
        table.lookup('CURRENCY', currency).instance) or []
    out = []
    for raw in raws:
        p = GncPrice(instance=raw)
        v = p.get_value()
        num = v.num() if callable(v.num) else v.num
        denom = v.denom() if callable(v.denom) else v.denom
        out.append(f'{p.get_time64():%Y-%m-%d %H:%M:%S} {p.get_source_string()} {num}/{denom}')
    return out


def show(label, book, mnemonic, namespace='CURRENCY', currency='CAD'):
    got = prices(book, mnemonic, namespace, currency)
    print(f'  {label}: {len(got)} kept -> {got}')


print(f'TZ={os.environ.get("TZ")!r} tzname={time.tzname} '
      f'gnucash={getattr(gnucash, "__version__", "?")}')

tmp = tempfile.mkdtemp()
url = 'xml://' + os.path.join(tmp, 'book.gnucash')

# --- one session: replacement rules ---------------------------------------
s = session(url, 'SESSION_NEW_STORE')
book = s.book
acct = Account(book)
acct.SetName('Bank')
acct.SetType(ACCT_TYPE_BANK)
acct.SetCommodity(book.get_table().lookup('CURRENCY', 'CAD'))
book.get_root_account().append_child(acct)

print('which day counts (local times; Toronto is UTC-5 in January):')
# different local days, same UTC day (2026-01-02 01:00Z and 15:00Z)
add_price(book, 'EUR', datetime(2026, 1, 1, 20, 0, 0), 'user:price-editor', 1, 1)
add_price(book, 'EUR', datetime(2026, 1, 2, 10, 0, 0), 'user:price-editor', 2, 1)
show('EUR local 01-01 20:00 then 01-02 10:00 (same UTC day)', book, 'EUR')
# same local day, different UTC days (2026-01-03 15:00Z and 2026-01-04 02:00Z)
add_price(book, 'GBP', datetime(2026, 1, 3, 10, 0, 0), 'user:price-editor', 1, 1)
add_price(book, 'GBP', datetime(2026, 1, 3, 21, 0, 0), 'user:price-editor', 2, 1)
show('GBP local 01-03 10:00 then 01-03 21:00 (different UTC days)', book, 'GBP')

print('source ranking, same day:')
r1 = add_price(book, 'JPY', datetime(2026, 1, 5, 10, 0, 0), 'Finance::Quote', 1, 100)
r2 = add_price(book, 'JPY', datetime(2026, 1, 5, 11, 0, 0), 'user:price-editor', 2, 100)
print(f'  JPY add returned {r1}, {r2}')
show('JPY Finance::Quote then user:price-editor', book, 'JPY')
r1 = add_price(book, 'CHF', datetime(2026, 1, 5, 10, 0, 0), 'user:price-editor', 1, 1)
r2 = add_price(book, 'CHF', datetime(2026, 1, 5, 11, 0, 0), 'Finance::Quote', 2, 1)
print(f'  CHF add returned {r1}, {r2}')
show('CHF user:price-editor then Finance::Quote', book, 'CHF')
r1 = add_price(book, 'AUD', datetime(2026, 1, 5, 10, 0, 0), 'user:price-editor', 1, 1)
r2 = add_price(book, 'AUD', datetime(2026, 1, 5, 10, 0, 0), 'user:price-editor', 2, 1)
print(f'  AUD add returned {r1}, {r2}')
show('AUD same source, same second, new value', book, 'AUD')

print('a stock, NASDAQ:AMZN in USD:')
from gnucash import GncCommodity  # noqa: E402

table = book.get_table()
table.insert(GncCommodity(book, 'Amazon.com Inc', 'NASDAQ', 'AMZN', '', 100000))
r1 = add_price(book, 'AMZN', datetime(2026, 1, 6, 16, 0, 0), 'Finance::Quote',
               21845, 100, namespace='NASDAQ', currency='USD')
r2 = add_price(book, 'AMZN', datetime(2026, 1, 7, 16, 0, 0), 'user:price-editor',
               22010, 100, namespace='NASDAQ', currency='USD')
print(f'  AMZN add returned {r1}, {r2}')
show('AMZN two days', book, 'AMZN', namespace='NASDAQ', currency='USD')

print('two currencies, either way round (local times):')
from services.prices import prices_in_book  # noqa: E402


def between(book, a, b):
    """Every price of `a` and `b`, whichever way round, read one by one from the database."""
    rows = []
    for p in prices_in_book(book):
        if {p.mnemonic, p.currency_mnemonic} == {a, b}:
            rows.append(f'{p.mnemonic} in {p.currency_mnemonic} '
                        f'{time.strftime("%m-%d %H:%M", time.localtime(p.time))} {p.source}')
    return sorted(rows)


def price_object(book, mnemonic, when, source, num, denom, currency):
    table = book.get_table()
    price = GncPrice(book)
    price.set_commodity(table.lookup('CURRENCY', mnemonic))
    price.set_currency(table.lookup('CURRENCY', currency))
    price.set_time64(when)
    price.set_source_string(source)
    price.set_typestr('last')
    price.set_value(GncNumeric(num, denom))
    added = gnc_pricedb_add_price(gnc_pricedb_get_db(book.instance), price.instance)
    return added, price


r1 = add_price(book, 'USD', datetime(2026, 1, 8, 10, 0, 0), 'user:price', 780, 100, currency='HKD')
r2 = add_price(book, 'HKD', datetime(2026, 1, 8, 15, 0, 0), 'user:price', 128, 1000, currency='USD')
print(f'  add returned {r1}, {r2}')
print(f'  USD in HKD 01-08 then HKD in USD 01-08, same source: {between(book, "USD", "HKD")}')
add_price(book, 'USD', datetime(2026, 1, 9, 10, 0, 0), 'user:price', 134, 100, currency='SGD')
add_price(book, 'SGD', datetime(2026, 1, 10, 10, 0, 0), 'user:price', 746, 1000, currency='USD')
print(f'  USD in SGD 01-09 then SGD in USD 01-10: {between(book, "USD", "SGD")}')
r1 = add_price(book, 'USD', datetime(2026, 1, 11, 10, 0, 0), 'user:price-editor', 1050, 100,
               currency='SEK')
r2 = add_price(book, 'SEK', datetime(2026, 1, 11, 15, 0, 0), 'Finance::Quote', 95, 1000,
               currency='USD')
print(f'  add returned {r1}, {r2}')
print(f'  USD in SEK user:price-editor then SEK in USD Finance::Quote, one day: '
      f'{between(book, "USD", "SEK")}')
add_price(book, 'USD', datetime(2026, 1, 12, 10, 0, 0), 'user:price', 1070, 100, currency='NOK')
_, moved = price_object(book, 'NOK', datetime(2026, 1, 13, 10, 0, 0), 'user:price', 93, 1000, 'USD')
print(f'  USD in NOK 01-12, NOK in USD 01-13: {between(book, "USD", "NOK")}')
moved.begin_edit()
moved.set_time64(datetime(2026, 1, 12, 15, 0, 0))
moved.commit_edit()
print(f'  after an edit moves NOK in USD to 01-12 15:00: {between(book, "USD", "NOK")}')
add_price(book, 'NZD', datetime(2026, 1, 14, 10, 0, 0), 'user:price', 470, 100, currency='HKD')
_, moved = price_object(book, 'NZD', datetime(2026, 1, 15, 10, 0, 0), 'user:price', 471, 100, 'HKD')
print(f'  NZD in HKD 01-14 and 01-15: {between(book, "NZD", "HKD")}')
moved.begin_edit()
moved.set_time64(datetime(2026, 1, 14, 15, 0, 0))
moved.commit_edit()
print(f'  after an edit moves the 01-15 one to 01-14 15:00: {between(book, "NZD", "HKD")}')

s.save()
s.end()
s.destroy()

# --- an existing book: does a price alone reach disk? ---------------------
print('existing book, a price and nothing else:')
s = session(url, 'SESSION_NORMAL_OPEN')
add_price(s.book, 'USD', datetime(2026, 2, 1, 12, 0, 0), 'user:price-editor', 13642, 10000)
print('  not-saved flag after add:', qof_book_session_not_saved(s.book.instance))
s.save()
s.end()
s.destroy()
s = session(url, 'SESSION_READ_ONLY')
show('AMZN after the first save and reload', s.book, 'AMZN', namespace='NASDAQ', currency='USD')
show('USD after save and reload, no dirty mark', s.book, 'USD')
s.end()
s.destroy()

print('existing book, a price and qof_book_mark_session_dirty:')
s = session(url, 'SESSION_NORMAL_OPEN')
add_price(s.book, 'CNY', datetime(2026, 2, 1, 12, 0, 0), 'user:price-editor', 19, 100)
qof_book_mark_session_dirty(s.book.instance)
print('  not-saved flag after mark:', qof_book_session_not_saved(s.book.instance))
s.save()
s.end()
s.destroy()
s = session(url, 'SESSION_READ_ONLY')
show('CNY after save and reload, dirty mark', s.book, 'CNY')
show('USD after that second save', s.book, 'USD')
s.end()
s.destroy()
