"""Probe: what does GnuCash keep of a price's time, does it keep two prices
for one commodity on one day, and does a book holding only new prices save?

Run:  docker run --rm -e TZ=America/Toronto -v "$PWD:/workspace" -w /workspace \
          gnucash-dev:<tag> python3 tests/research/what_a_price_time_holds_probe.py
"""

import gzip
import os
import sys
import tempfile
import time
from datetime import datetime

sys.path.insert(0, '/workspace')

import contextlib

import gnucash  # noqa: E402
from gnucash import Account, GncNumeric, GncPrice, Session  # noqa: E402
from gnucash.gnucash_core_c import (  # noqa: E402
    ACCT_TYPE_BANK,
    gnc_pricedb_add_price,
    gnc_pricedb_get_db,
    gnc_pricedb_get_prices,
    qof_book_session_not_saved,
)


def new_session(path):
    if hasattr(gnucash, 'SessionOpenMode'):
        return Session(path, gnucash.SessionOpenMode.SESSION_NEW_STORE)
    return Session(path, is_new=True)


def open_session(path):
    if hasattr(gnucash, 'SessionOpenMode'):
        return Session(path, gnucash.SessionOpenMode.SESSION_READ_ONLY)
    return Session(path, ignore_lock=True)


def add_price(book, mnemonic, when, source, num, denom):
    table = book.get_table()
    db = gnc_pricedb_get_db(book.instance)
    price = GncPrice(book)
    price.set_commodity(table.lookup('CURRENCY', mnemonic))
    price.set_currency(table.lookup('CURRENCY', 'CAD'))
    price.set_time64(when)
    price.set_source_string(source)
    price.set_typestr('last')
    price.set_value(GncNumeric(num, denom))
    return gnc_pricedb_add_price(db, price.instance)


def dump(book, mnemonic):
    table = book.get_table()
    db = gnc_pricedb_get_db(book.instance)
    raws = gnc_pricedb_get_prices(
        db, table.lookup('CURRENCY', mnemonic).instance,
        table.lookup('CURRENCY', 'CAD').instance) or []
    print(f'    {mnemonic}/CAD prices: {len(raws)}')
    for raw in raws:
        p = GncPrice(instance=raw)
        v = p.get_value()
        num = v.num() if callable(v.num) else v.num
        denom = v.denom() if callable(v.denom) else v.denom
        print(f'      time={p.get_time64()!r} source={p.get_source_string()!r} '
              f'type={p.get_typestr()!r} value={num}/{denom}')


def xml_price_lines(path):
    with open(path, 'rb') as f:
        data = f.read()
    with contextlib.suppress(OSError):
        data = gzip.decompress(data)
    lines = data.decode('utf-8').splitlines()
    return [' | '.join(x.strip() for x in lines[i:i + 3])
            for i, line in enumerate(lines) if '<price:time>' in line]


def scenario(label, with_account):
    print(f'--- {label} ---')
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, 'prices.gnucash')
    url = 'xml://' + path

    s = new_session(url)
    book = s.book
    if with_account:
        acct = Account(book)
        acct.SetName('Bank')
        acct.SetType(ACCT_TYPE_BANK)
        acct.SetCommodity(book.get_table().lookup('CURRENCY', 'CAD'))
        book.get_root_account().append_child(acct)
    print('  add USD 2026-01-01 15:30:45:',
          add_price(book, 'USD', datetime(2026, 1, 1, 15, 30, 45),
                    'user:price-editor', 13642, 10000))
    print('  add HKD 2026-01-01 09:00:00:',
          add_price(book, 'HKD', datetime(2026, 1, 1, 9, 0, 0),
                    'user:price-editor', 1745, 10000))
    print('  add HKD 2026-01-01 17:00:00:',
          add_price(book, 'HKD', datetime(2026, 1, 1, 17, 0, 0),
                    'user:price-editor', 1750, 10000))
    print('  book marked not-saved before save:',
          qof_book_session_not_saved(book.instance))
    s.save()
    s.end()
    s.destroy()

    print('  files after save:', sorted(os.listdir(tmp)))
    if not os.path.exists(path):
        print('  NO FILE WRITTEN')
        return
    print('  saved XML <price:time>:')
    for line in xml_price_lines(path):
        print('    ' + line)

    s = open_session(url)
    print('  after reload:')
    dump(s.book, 'USD')
    dump(s.book, 'HKD')
    s.end()
    s.destroy()


print(f'TZ={os.environ.get("TZ")!r} tzname={time.tzname}')
scenario('prices only', with_account=False)
scenario('prices and an account', with_account=True)
