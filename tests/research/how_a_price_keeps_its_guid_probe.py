"""Probe: can a price be matched by guid across an export and an import?

Asks the book, on this build:

1. Does a price keep its guid through a save and reload?
2. Can a new price be given a stated guid (qof_instance_set_guid) before it is
   added, and does that guid reach disk -- in a new book, and in an existing
   book where the price is the only change (finding 18: forcing a guid marks
   nothing dirty)?
3. Does gnc_price_lookup find a price by guid after a reload?
4. Does editing a price in place (value, then time moved to another day)
   persist, and keep its guid?
5. When gnc_pricedb_add_price replaces a same-day price, whose guid survives?
6. Does gnc_pricedb_remove_price remove it from disk?

Run inside an image:
  docker run --rm -e TZ=America/Toronto -e TAG=<tag> -v "$PWD:/workspace" -w /workspace \
      gnucash-dev:<tag> python3 tests/research/how_a_price_keeps_its_guid_probe.py
"""

import os
import sys
import tempfile
import time
from ctypes import (
    CDLL,
    CFUNCTYPE,
    RTLD_GLOBAL,
    Structure,
    c_char,
    c_char_p,
    c_int,
    c_int64,
    c_void_p,
    create_string_buffer,
)

import gnucash
from gnucash import Account, GncCommodity, Session
from gnucash.gnucash_core_c import ACCT_TYPE_BANK

ROOTS = (
    '/usr/lib/x86_64-linux-gnu/gnucash/gnucash',
    '/usr/lib/x86_64-linux-gnu/gnucash',
    '/usr/lib64/gnucash',
    '/usr/lib64',
    '/usr/lib/gnucash',
    '/usr/lib',
)
for name in ('libgnc-engine.so', 'libgncmod-engine.so'):
    hits = [os.path.join(r, name) for r in ROOTS if os.path.exists(os.path.join(r, name))]
    if hits:
        CDLL(hits[0], mode=RTLD_GLOBAL)
        break
lib = CDLL(None)


class Numeric(Structure):
    _fields_ = [('num', c_int64), ('denom', c_int64)]


class GUID(Structure):
    _fields_ = [('data', c_char * 16)]


def fn(name, restype, *argtypes):
    f = getattr(lib, name)
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


PRICE_CB = CFUNCTYPE(c_int, c_void_p, c_void_p)
gnc_price_create = fn('gnc_price_create', c_void_p, c_void_p)
gnc_price_begin_edit = fn('gnc_price_begin_edit', None, c_void_p)
gnc_price_commit_edit = fn('gnc_price_commit_edit', None, c_void_p)
gnc_price_set_commodity = fn('gnc_price_set_commodity', None, c_void_p, c_void_p)
gnc_price_set_currency = fn('gnc_price_set_currency', None, c_void_p, c_void_p)
gnc_price_set_time64 = fn('gnc_price_set_time64', None, c_void_p, c_int64)
gnc_price_set_source_string = fn('gnc_price_set_source_string', None, c_void_p, c_char_p)
gnc_price_set_typestr = fn('gnc_price_set_typestr', None, c_void_p, c_char_p)
gnc_price_set_value = fn('gnc_price_set_value', None, c_void_p, Numeric)
gnc_price_unref = fn('gnc_price_unref', None, c_void_p)
gnc_price_get_time64 = fn('gnc_price_get_time64', c_int64, c_void_p)
gnc_price_get_value = fn('gnc_price_get_value', Numeric, c_void_p)
gnc_price_get_source_string = fn('gnc_price_get_source_string', c_char_p, c_void_p)
gnc_price_get_commodity = fn('gnc_price_get_commodity', c_void_p, c_void_p)
gnc_commodity_get_mnemonic = fn('gnc_commodity_get_mnemonic', c_char_p, c_void_p)
gnc_price_lookup = fn('gnc_price_lookup', c_void_p, c_void_p, c_void_p)
gnc_pricedb_get_db = fn('gnc_pricedb_get_db', c_void_p, c_void_p)
gnc_pricedb_add_price = fn('gnc_pricedb_add_price', c_int, c_void_p, c_void_p)
gnc_pricedb_remove_price = fn('gnc_pricedb_remove_price', c_int, c_void_p, c_void_p)
gnc_pricedb_foreach_price = fn('gnc_pricedb_foreach_price', c_int, c_void_p, PRICE_CB, c_void_p, c_int)
qof_instance_get_guid = fn('qof_instance_get_guid', c_void_p, c_void_p)
qof_instance_set_guid = fn('qof_instance_set_guid', None, c_void_p, c_void_p)
guid_to_string_buff = fn('guid_to_string_buff', c_char_p, c_void_p, c_char_p)
string_to_guid = fn('string_to_guid', c_int, c_char_p, c_void_p)
qof_book_session_not_saved = fn('qof_book_session_not_saved', c_int, c_void_p)


def ptr(obj):
    inst = getattr(obj, 'instance', obj)
    try:
        return int(inst)
    except TypeError:
        return int(inst.instance)


def local(y, mo, d, h=0, mi=0, s=0):
    return int(time.mktime((y, mo, d, h, mi, s, 0, 0, -1)))


def fmt(t):
    return time.strftime('%Y-%m-%d %H:%M:%S %z', time.localtime(t))


def guid_of(p):
    buf = create_string_buffer(33)
    guid_to_string_buff(qof_instance_get_guid(p), buf)
    return buf.value.decode()


def guid_struct(text):
    g = GUID()
    string_to_guid(text.encode(), c_void_p.from_buffer(g) and c_void_p(__import__('ctypes').addressof(g)))
    return g


def session(url, mode):
    if hasattr(gnucash, 'SessionOpenMode'):
        return Session(url, getattr(gnucash.SessionOpenMode, mode))
    if mode == 'SESSION_NEW_STORE':
        return Session(url, is_new=True)
    if mode == 'SESSION_READ_ONLY':
        return Session(url, ignore_lock=True)
    return Session(url)


def new_price(book, mnemonic, when, source, num, denom, forced_guid=None):
    table = book.get_table()
    p = gnc_price_create(ptr(book))
    if forced_guid:
        import ctypes
        g = GUID()
        string_to_guid(forced_guid.encode(), ctypes.addressof(g))
        qof_instance_set_guid(p, ctypes.addressof(g))
    gnc_price_begin_edit(p)
    gnc_price_set_commodity(p, ptr(table.lookup('NASDAQ', mnemonic)))
    gnc_price_set_currency(p, ptr(table.lookup('CURRENCY', 'USD')))
    gnc_price_set_time64(p, when)
    gnc_price_set_source_string(p, source.encode())
    gnc_price_set_typestr(p, b'last')
    gnc_price_set_value(p, Numeric(num, denom))
    gnc_price_commit_edit(p)
    added = gnc_pricedb_add_price(gnc_pricedb_get_db(ptr(book)), p)
    return p, added


def listing(book):
    rows = []

    def each(p, _data):
        v = gnc_price_get_value(p)
        rows.append(f'{s(gnc_commodity_get_mnemonic(gnc_price_get_commodity(p)))} {guid_of(p)}'
                    f' {fmt(gnc_price_get_time64(p))} {v.num}/{v.denom}'
                    f' {s(gnc_price_get_source_string(p))}')
        return 1

    gnc_pricedb_foreach_price(gnc_pricedb_get_db(ptr(book)), PRICE_CB(each), None, 1)
    return rows


def s(b):
    return b.decode() if b else None


def show(label, book):
    print(f'  {label}:')
    for row in listing(book):
        print(f'    {row}')
    sys.stdout.flush()


def lookup(book, text):
    import ctypes
    g = GUID()
    string_to_guid(text.encode(), ctypes.addressof(g))
    p = gnc_price_lookup(ctypes.addressof(g), ptr(book))
    if not p:
        return None
    v = gnc_price_get_value(p)
    return f'{fmt(gnc_price_get_time64(p))} {v.num}/{v.denom} {s(gnc_price_get_source_string(p))}'


print(f'TAG={os.environ.get("TAG")} TZ={os.environ.get("TZ")}')
url = 'xml://' + os.path.join(tempfile.mkdtemp(), 'book.gnucash')
STATED_NEW = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
STATED_EXISTING = '0f1e2d3c4b5a69788796a5b4c3d2e1f0'

print('== 1, 2a: a new book, one price with its own guid, one with a stated guid')
sess = session(url, 'SESSION_NEW_STORE')
book = sess.book
table = book.get_table()
for mnemonic in ('AMZN', 'MSFT', 'GOOG'):
    table.insert(GncCommodity(book, mnemonic, 'NASDAQ', mnemonic, '', 10000))
bank = Account(book)
bank.BeginEdit()
bank.SetName('Bank USD')
bank.SetType(ACCT_TYPE_BANK)
bank.SetCommodity(table.lookup('CURRENCY', 'USD'))
book.get_root_account().append_child(bank)
bank.CommitEdit()
own, added = new_price(book, 'AMZN', local(2026, 1, 6, 16), 'Finance::Quote', 21845, 100)
own_guid = guid_of(own)
print(f'  own guid {own_guid}, added {added}')
stated, added = new_price(book, 'MSFT', local(2026, 1, 6, 16), 'user:price-editor', 42310, 100,
                          forced_guid=STATED_NEW)
print(f'  stated guid {STATED_NEW} -> reads back {guid_of(stated)}, added {added}')
sess.save()
sess.end()
time.sleep(1)
sess = session(url, 'SESSION_READ_ONLY')
show('after save and reload', sess.book)
print(f'  3: lookup {own_guid} -> {lookup(sess.book, own_guid)}')
print(f'  3: lookup {STATED_NEW} -> {lookup(sess.book, STATED_NEW)}')
sess.end()
time.sleep(1)

print('== 2b: an existing book, the only change a price with a stated guid')
sess = session(url, 'SESSION_NORMAL_OPEN')
p, added = new_price(sess.book, 'GOOG', local(2026, 1, 7, 16), 'user:price-editor', 19025, 100,
                     forced_guid=STATED_EXISTING)
print(f'  added {added}, reads back {guid_of(p)}, not-saved flag {qof_book_session_not_saved(ptr(sess.book))}')
sess.save()
sess.end()
time.sleep(1)
sess = session(url, 'SESSION_READ_ONLY')
print(f'  lookup {STATED_EXISTING} after reload -> {lookup(sess.book, STATED_EXISTING)}')
sess.end()
time.sleep(1)

print('== 4: an existing book, the AMZN price edited in place (value, then time to another day)')
sess = session(url, 'SESSION_NORMAL_OPEN')
import ctypes  # noqa: E402

g = GUID()
string_to_guid(own_guid.encode(), ctypes.addressof(g))
p = gnc_price_lookup(ctypes.addressof(g), ptr(sess.book))
gnc_price_begin_edit(p)
gnc_price_set_value(p, Numeric(22000, 100))
gnc_price_commit_edit(p)
print(f'  value edited; not-saved flag {qof_book_session_not_saved(ptr(sess.book))}')
sess.save()
sess.end()
time.sleep(1)
sess = session(url, 'SESSION_NORMAL_OPEN')
print(f'  after reload: lookup {own_guid} -> {lookup(sess.book, own_guid)}')
string_to_guid(own_guid.encode(), ctypes.addressof(g))
p = gnc_price_lookup(ctypes.addressof(g), ptr(sess.book))
gnc_price_begin_edit(p)
gnc_price_set_time64(p, local(2026, 1, 9, 16))
gnc_price_commit_edit(p)
print(f'  time moved to 2026-01-09; not-saved flag {qof_book_session_not_saved(ptr(sess.book))}')
sess.save()
sess.end()
time.sleep(1)
sess = session(url, 'SESSION_READ_ONLY')
print(f'  after reload: lookup {own_guid} -> {lookup(sess.book, own_guid)}')
show('all prices', sess.book)
sess.end()
time.sleep(1)

print('== 5: gnc_pricedb_add_price replacing a same-day price: whose guid survives')
sess = session(url, 'SESSION_NORMAL_OPEN')
q, added = new_price(sess.book, 'MSFT', local(2026, 1, 6, 10), 'user:price-editor', 43000, 100)
print(f'  same-day MSFT, same source, guid {guid_of(q)}, added {added}')
r, added = new_price(sess.book, 'MSFT', local(2026, 1, 6, 11), 'Finance::Quote', 44000, 100)
print(f'  same-day MSFT, lower-ranked source, guid {guid_of(r)}, added {added}')
sess.save()
sess.end()
time.sleep(1)
sess = session(url, 'SESSION_READ_ONLY')
show('after reload', sess.book)
print(f'  lookup the stated {STATED_NEW} -> {lookup(sess.book, STATED_NEW)}')
sess.end()
time.sleep(1)

print('== 6: gnc_pricedb_remove_price on the GOOG price')
sess = session(url, 'SESSION_NORMAL_OPEN')
string_to_guid(STATED_EXISTING.encode(), ctypes.addressof(g))
p = gnc_price_lookup(ctypes.addressof(g), ptr(sess.book))
print(f'  removed {gnc_pricedb_remove_price(gnc_pricedb_get_db(ptr(sess.book)), p)},'
      f' not-saved flag {qof_book_session_not_saved(ptr(sess.book))}')
sess.save()
sess.end()
time.sleep(1)
sess = session(url, 'SESSION_READ_ONLY')
print(f'  lookup {STATED_EXISTING} after reload -> {lookup(sess.book, STATED_EXISTING)}')
show('after reload', sess.book)
sys.stdout.flush()
os._exit(0)
