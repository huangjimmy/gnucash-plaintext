"""Probe: does a price's source and type round-trip exactly, whatever wrote it?

A book's prices come from GnuCash's own dialogs, assistants, register and
Finance::Quote, so an export must write back the source and type each one
carries, and an import must store exactly what a block says. On this build:

1. Every source string GnuCash defines, plus one it does not, set with
   gnc_price_set_source_string: what reads back at once, after a save and
   reload, and what the file's <price:source> holds.
2. Every type string, plus one GnuCash does not use: the same three readings.
3. A price created with no source and no type set: what reads back, and what
   the file holds.

Each price is on its own day, so no same-day replacement interferes.

Run inside an image:
  docker run --rm -e TZ=America/Toronto -e TAG=<tag> -v "$PWD:/workspace" -w /workspace \
      gnucash-dev:<tag> python3 tests/research/what_a_price_source_keeps_probe.py
"""

import ctypes
import gzip
import os
import re
import sys
import tempfile
import time
from ctypes import (
    CDLL,
    CFUNCTYPE,
    RTLD_GLOBAL,
    Structure,
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
gnc_price_get_time64 = fn('gnc_price_get_time64', c_int64, c_void_p)
gnc_price_get_source = fn('gnc_price_get_source', c_int, c_void_p)
gnc_price_get_source_string = fn('gnc_price_get_source_string', c_char_p, c_void_p)
gnc_price_get_typestr = fn('gnc_price_get_typestr', c_char_p, c_void_p)
gnc_price_get_commodity = fn('gnc_price_get_commodity', c_void_p, c_void_p)
gnc_commodity_get_mnemonic = fn('gnc_commodity_get_mnemonic', c_char_p, c_void_p)
gnc_pricedb_get_db = fn('gnc_pricedb_get_db', c_void_p, c_void_p)
gnc_pricedb_add_price = fn('gnc_pricedb_add_price', c_int, c_void_p, c_void_p)
gnc_pricedb_foreach_price = fn('gnc_pricedb_foreach_price', c_int, c_void_p, PRICE_CB, c_void_p, c_int)
qof_instance_get_guid = fn('qof_instance_get_guid', c_void_p, c_void_p)
guid_to_string_buff = fn('guid_to_string_buff', c_char_p, c_void_p, c_char_p)

SOURCES = ['user:price-editor', 'Finance::Quote', 'user:price', 'user:xfer-dialog',
           'user:split-register', 'user:split-import', 'user:stock-split',
           'user:stock-transaction', 'user:invoice-post', 'temporary', 'invalid',
           'a-source-gnucash-does-not-define']
TYPES = ['bid', 'ask', 'last', 'nav', 'transaction', 'unknown', 'pricedb',
         'a-type-gnucash-does-not-use']


def ptr(obj):
    inst = getattr(obj, 'instance', obj)
    try:
        return int(inst)
    except TypeError:
        return int(inst.instance)


def local(y, mo, d, h=0, mi=0, s=0):
    return int(time.mktime((y, mo, d, h, mi, s, 0, 0, -1)))


def s(b):
    return b.decode() if b is not None else None


def guid_of(p):
    buf = create_string_buffer(33)
    guid_to_string_buff(qof_instance_get_guid(p), buf)
    return buf.value.decode()


def session(url, mode):
    if hasattr(gnucash, 'SessionOpenMode'):
        return Session(url, getattr(gnucash.SessionOpenMode, mode))
    if mode == 'SESSION_NEW_STORE':
        return Session(url, is_new=True)
    if mode == 'SESSION_READ_ONLY':
        return Session(url, ignore_lock=True)
    return Session(url)


print(f'TAG={os.environ.get("TAG")} TZ={os.environ.get("TZ")}')
path = os.path.join(tempfile.mkdtemp(), 'book.gnucash')
sess = session('xml://' + path, 'SESSION_NEW_STORE')
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
db = gnc_pricedb_get_db(ptr(book))
usd = ptr(table.lookup('CURRENCY', 'USD'))

# guid -> (what was set, what read back at once)
set_and_read = {}


def add(mnemonic, day, source=None, typestr=None):
    p = gnc_price_create(ptr(book))
    gnc_price_begin_edit(p)
    gnc_price_set_commodity(p, ptr(table.lookup('NASDAQ', mnemonic)))
    gnc_price_set_currency(p, usd)
    gnc_price_set_time64(p, local(2026, 1, day, 12))
    if source is not None:
        gnc_price_set_source_string(p, source.encode())
    if typestr is not None:
        gnc_price_set_typestr(p, typestr.encode())
    gnc_price_set_value(p, Numeric(100 + day, 1))
    gnc_price_commit_edit(p)
    added = gnc_pricedb_add_price(db, p)
    set_and_read[guid_of(p)] = (
        mnemonic, day, source, typestr, added,
        s(gnc_price_get_source_string(p)), gnc_price_get_source(p), s(gnc_price_get_typestr(p)))


for day, source in enumerate(SOURCES, start=1):
    add('AMZN', day, source=source, typestr='last')
for day, typestr in enumerate(TYPES, start=1):
    add('MSFT', day, source='user:price-editor', typestr=typestr)
add('GOOG', 1)

sess.save()
sess.end()
time.sleep(1)
reread = session('xml://' + path, 'SESSION_READ_ONLY')
after_reload = {}


def each(p, _data):
    after_reload[guid_of(p)] = (s(gnc_price_get_source_string(p)), gnc_price_get_source(p),
                                s(gnc_price_get_typestr(p)))
    return 1


gnc_pricedb_foreach_price(gnc_pricedb_get_db(ptr(reread.book)), PRICE_CB(each), None, 1)
try:
    with gzip.open(path, 'rt') as f:
        xml = f.read()
except OSError:
    with open(path) as f:
        xml = f.read()
in_file = {}
for block in re.findall(r'<price>.*?</price>', xml, re.S):
    guid = re.search(r'<price:id type="guid">(.*?)</price:id>', block)
    source = re.search(r'<price:source>(.*?)</price:source>', block, re.S)
    typestr = re.search(r'<price:type>(.*?)</price:type>', block, re.S)
    if guid:
        in_file[guid.group(1)] = (source.group(1) if source else '(no element)',
                                  typestr.group(1) if typestr else '(no element)')

print('commodity day | set source / type | added | read at once: source (enum) / type'
      ' | after reload: source (enum) / type | file: <price:source> / <price:type>')
for guid, (mnemonic, day, source, typestr, added, src_now, enum_now, type_now) in set_and_read.items():
    src_after, enum_after, type_after = after_reload.get(guid, ('(gone)', None, '(gone)'))
    file_source, file_type = in_file.get(guid, ('(not in file)', '(not in file)'))
    print(f'{mnemonic} {day:2} | {source!r} / {typestr!r} | {added}'
          f' | {src_now!r} ({enum_now}) / {type_now!r}'
          f' | {src_after!r} ({enum_after}) / {type_after!r}'
          f' | {file_source!r} / {file_type!r}')
sys.stdout.flush()
os._exit(0)
