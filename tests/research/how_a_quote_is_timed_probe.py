"""Probe: what time GnuCash stores for a Finance::Quote price, through its own quote path.

Only the network fetch is replaced. PERL5LIB puts a stand-in Finance::Quote
module (tests/research/fake_finance_quote/Finance/Quote.pm) ahead of the real one, so GnuCash's own
gnc-fq-helper (3.x, 4.x) or finance-quote-wrapper (5.x) runs, and GnuCash's
own Scheme or C++ turns its answer into a price. The stand-in answers:

  NASDAQ:AMZN  date "01/06/2026", no time
  NASDAQ:MSFT  date "01/06/2026", time "16:00"
  NASDAQ:GOOG  no date, no time
  CAD          a currency rate (Finance::Quote never dates one)

Run inside an image:
  docker run --rm -e TZ=America/Toronto -e TAG=<tag> -v "$PWD:/workspace" -w /workspace \
      gnucash-dev:<tag> sh tests/research/run_a_gui_probe_under_xvfb.sh tests/research/how_a_quote_is_timed_probe.py
"""

import gzip
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import CDLL, CFUNCTYPE, RTLD_GLOBAL, Structure, c_char_p, c_int, c_int64, c_void_p

import gnucash
from gnucash import Account, GncCommodity, Session
from gnucash.gnucash_core_c import ACCT_TYPE_BANK, ACCT_TYPE_STOCK

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


gnc_quote_source_lookup_by_internal = fn('gnc_quote_source_lookup_by_internal', c_void_p, c_char_p)
gnc_commodity_begin_edit = fn('gnc_commodity_begin_edit', None, c_void_p)
gnc_commodity_commit_edit = fn('gnc_commodity_commit_edit', None, c_void_p)
gnc_commodity_set_quote_flag = fn('gnc_commodity_set_quote_flag', None, c_void_p, c_int)
gnc_commodity_set_quote_source = fn('gnc_commodity_set_quote_source', None, c_void_p, c_void_p)
gnc_commodity_get_mnemonic = fn('gnc_commodity_get_mnemonic', c_char_p, c_void_p)
gnc_pricedb_get_db = fn('gnc_pricedb_get_db', c_void_p, c_void_p)
gnc_price_get_commodity = fn('gnc_price_get_commodity', c_void_p, c_void_p)
gnc_price_get_currency = fn('gnc_price_get_currency', c_void_p, c_void_p)
gnc_price_get_time64 = fn('gnc_price_get_time64', c_int64, c_void_p)
gnc_price_get_source_string = fn('gnc_price_get_source_string', c_char_p, c_void_p)
gnc_price_get_typestr = fn('gnc_price_get_typestr', c_char_p, c_void_p)
gnc_price_get_value = fn('gnc_price_get_value', Numeric, c_void_p)
PRICE_CB = CFUNCTYPE(c_int, c_void_p, c_void_p)
gnc_pricedb_foreach_price = fn('gnc_pricedb_foreach_price', c_int, c_void_p, PRICE_CB, c_void_p, c_int)


def ptr(obj):
    inst = getattr(obj, 'instance', obj)
    try:
        return int(inst)
    except TypeError:
        return int(inst.instance)


def fmt(t):
    return (f'{time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(t))}'
            f' = {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))}Z')


def s(b):
    return b.decode() if b else None


def session(url, mode):
    if hasattr(gnucash, 'SessionOpenMode'):
        return Session(url, getattr(gnucash.SessionOpenMode, mode))
    if mode == 'SESSION_NEW_STORE':
        return Session(url, is_new=True)
    if mode == 'SESSION_READ_ONLY':
        return Session(url, ignore_lock=True)
    return Session(url)


print(f'TAG={os.environ.get("TAG")} TZ={os.environ.get("TZ")} tzname={time.tzname}'
      f' PERL5LIB={os.environ.get("PERL5LIB")}')

tmp = tempfile.mkdtemp()
path = os.path.join(tmp, 'book.gnucash')
sess = session('xml://' + path, 'SESSION_NEW_STORE')
book = sess.book
table = book.get_table()
root = book.get_root_account()


def account(name, commodity, kind):
    acct = Account(book)
    acct.BeginEdit()
    acct.SetName(name)
    acct.SetType(kind)
    acct.SetCommodity(commodity)
    root.append_child(acct)
    acct.CommitEdit()


source = None
for internal in (b'yahoo_json', b'alphavantage', b'yahoo'):
    source = gnc_quote_source_lookup_by_internal(internal)
    if source:
        print(f'stock quote source: {internal.decode()}')
        break


def quoted(commodity, src):
    p = ptr(commodity)
    gnc_commodity_begin_edit(p)
    gnc_commodity_set_quote_flag(p, 1)
    gnc_commodity_set_quote_source(p, src)
    gnc_commodity_commit_edit(p)


for mnemonic in ('AMZN', 'MSFT', 'GOOG'):
    commodity = GncCommodity(book, mnemonic, 'NASDAQ', mnemonic, '', 1)
    table.insert(commodity)
    commodity = table.lookup('NASDAQ', mnemonic)
    quoted(commodity, source)
    account(mnemonic, commodity, ACCT_TYPE_STOCK)
quoted(table.lookup('CURRENCY', 'CAD'), gnc_quote_source_lookup_by_internal(b'currency'))
account('Bank CAD', table.lookup('CURRENCY', 'CAD'), ACCT_TYPE_BANK)
account('Bank USD', table.lookup('CURRENCY', 'USD'), ACCT_TYPE_BANK)
sess.save()
sess.end()
sess.destroy()

env = dict(os.environ, ALPHAVANTAGE_API_KEY='probe')
if shutil.which('gnucash-cli'):
    cmd = ['gnucash-cli', '--quotes', 'get', path]
else:
    cmd = ['gnucash', '--add-price-quotes', path]
print(f'running {cmd}')
sys.stdout.flush()
started = int(time.time())
run = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     text=True, timeout=240)
finished = int(time.time())
print(f'  exit {run.returncode}; ran from {fmt(started)} to {fmt(finished)}')
for line in run.stdout.splitlines():
    if line.strip() and 'dconf' not in line and 'D-Bus' not in line:
        print(f'  | {line}')

reread = session('xml://' + path, 'SESSION_READ_ONLY')
print('prices in the book after the quote run:')


def each(p, _data):
    t = gnc_price_get_time64(p)
    v = gnc_price_get_value(p)
    during = ' (inside the run: the moment of the fetch)' if started <= t <= finished else ''
    print(f'  {s(gnc_commodity_get_mnemonic(gnc_price_get_commodity(p)))}'
          f'/{s(gnc_commodity_get_mnemonic(gnc_price_get_currency(p)))}'
          f' {v.num}/{v.denom} source={s(gnc_price_get_source_string(p))!r}'
          f' type={s(gnc_price_get_typestr(p))!r} time={fmt(t)}{during}')
    return 1


gnc_pricedb_foreach_price(gnc_pricedb_get_db(ptr(reread.book)), PRICE_CB(each), None, 1)
try:
    with gzip.open(path, 'rt') as f:
        xml = f.read()
except OSError:
    with open(path) as f:
        xml = f.read()
print('<price> times in the file:')
for block in re.findall(r'<price>.*?</price>', xml, re.S):
    ids = re.findall(r'<cmdty:id>(.*?)</cmdty:id>', block)
    stamp = re.search(r'<ts:date>(.*?)</ts:date>', block)
    print(f'  {"/".join(ids)} {stamp.group(1) if stamp else None!r}')
sys.stdout.flush()
os._exit(0)
