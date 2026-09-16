"""Probe: what time the register gives the price it records when a stock purchase is entered.

Drives GnuCash's own register code, the part that runs under the ledger
window: gnc_ledger_display_simple on a stock account, the cursor moved onto
the blank split, then the cells a person fills in -- date 2026-02-09,
description, transfer account Bank USD, 10 shares, a value of 2,184.50 --
each marked changed, and gnc_split_register_save(reg, TRUE), which is what
leaving the row runs. The price is left for the register to work out from
shares and value.

Prints the transaction's date and every price, then the <price> blocks of
the saved file.

Run inside an image:
  docker run --rm -e TZ=America/Toronto -e TAG=<tag> -v "$PWD:/workspace" -w /workspace \
      gnucash-dev:<tag> sh tests/research/run_a_gui_probe_under_xvfb.sh tests/research/how_the_register_times_a_price_probe.py
"""

import faulthandler
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
    byref,
    c_char_p,
    c_int,
    c_int64,
    c_void_p,
)

faulthandler.dump_traceback_later(150, exit=True)

import gnucash  # noqa: E402
from gnucash import Account, GncCommodity, Session  # noqa: E402
from gnucash.gnucash_core_c import ACCT_TYPE_ASSET, ACCT_TYPE_BANK, ACCT_TYPE_STOCK  # noqa: E402

ROOTS = (
    '/usr/lib/x86_64-linux-gnu/gnucash/gnucash',
    '/usr/lib/x86_64-linux-gnu/gnucash',
    '/usr/lib64/gnucash',
    '/usr/lib64',
    '/usr/lib/gnucash',
    '/usr/lib',
)


def load(*names):
    for name in names:
        for root in ROOTS:
            path = os.path.join(root, name)
            if os.path.exists(path):
                return CDLL(path, mode=RTLD_GLOBAL)
    raise SystemExit(f'no library among {names}')


load('libgnc-core-utils.so')
load('libgnc-engine.so', 'libgncmod-engine.so')
load('libgnc-app-utils.so', 'libgncmod-app-utils.so')
CDLL('libgtk-3.so.0', mode=RTLD_GLOBAL)
load('libgnc-gnome-utils.so', 'libgncmod-gnome-utils.so')
load('libgnc-register-core.so', 'libgncmod-register-core.so')
load('libgnc-register-gnome.so', 'libgncmod-register-gnome.so')
load('libgnc-gnome.so')
for extra in ('libgnc-ledger-core.so', 'libgncmod-ledger-core.so'):
    for root in ROOTS:
        if os.path.exists(os.path.join(root, extra)):
            CDLL(os.path.join(root, extra), mode=RTLD_GLOBAL)
lib = CDLL(None)
# the same reason as the assistants: a price or amount cell can reach
# gnc_exp_parser_parse, which needs Guile started in this process
if getattr(lib, 'scm_init_guile', None) is not None:
    lib.scm_init_guile()


class Numeric(Structure):
    _fields_ = [('num', c_int64), ('denom', c_int64)]


class VirtualCellLocation(Structure):
    _fields_ = [('virt_row', c_int), ('virt_col', c_int)]


class VirtualLocation(Structure):
    _fields_ = [('vcell_loc', VirtualCellLocation), ('phys_row_offset', c_int),
                ('phys_col_offset', c_int)]


def fn(name, restype, *argtypes):
    f = getattr(lib, name, None)
    if f is None:
        print(f'  ({name} is not in this build)')
        return None
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


PRICE_CB = CFUNCTYPE(c_int, c_void_p, c_void_p)

gtk_init_check = fn('gtk_init_check', c_int, c_void_p, c_void_p)
gnc_set_current_session = fn('gnc_set_current_session', None, c_void_p)
gnc_component_manager_init = fn('gnc_component_manager_init', None)
gnc_ledger_display_simple = fn('gnc_ledger_display_simple', c_void_p, c_void_p)
gnc_ledger_display_get_split_register = fn('gnc_ledger_display_get_split_register', c_void_p, c_void_p)
gnc_split_register_get_blank_split = fn('gnc_split_register_get_blank_split', c_void_p, c_void_p)
gnc_split_register_get_split_virt_loc = fn('gnc_split_register_get_split_virt_loc', c_int,
                                           c_void_p, c_void_p, c_void_p)
gnc_split_register_get_current_trans = fn('gnc_split_register_get_current_trans', c_void_p, c_void_p)
gnc_split_register_save = fn('gnc_split_register_save', c_int, c_void_p, c_int)
gnc_table_move_cursor = fn('gnc_table_move_cursor', None, c_void_p, VirtualLocation)
gnc_table_layout_get_cell = fn('gnc_table_layout_get_cell', c_void_p, c_void_p, c_char_p)
gnc_table_current_cursor_changed = fn('gnc_table_current_cursor_changed', c_int, c_void_p, c_int)
gnc_basic_cell_set_value = fn('gnc_basic_cell_set_value', None, c_void_p, c_char_p)
gnc_basic_cell_set_changed = fn('gnc_basic_cell_set_changed', None, c_void_p, c_int)
gnc_basic_cell_get_value = fn('gnc_basic_cell_get_value', c_char_p, c_void_p)
gnc_date_cell_set_value = fn('gnc_date_cell_set_value', None, c_void_p, c_int, c_int, c_int)
gnc_price_cell_set_value = fn('gnc_price_cell_set_value', c_int, c_void_p, Numeric)
gnc_combo_cell_set_value = fn('gnc_combo_cell_set_value', None, c_void_p, c_char_p)
xaccTransGetDate = fn('xaccTransGetDate', c_int64, c_void_p)  # noqa: N816 — GnuCash's own C name
xaccTransGetDescription = fn('xaccTransGetDescription', c_char_p, c_void_p)  # noqa: N816 — GnuCash's own C name
gnc_pricedb_get_db = fn('gnc_pricedb_get_db', c_void_p, c_void_p)
gnc_pricedb_foreach_price = fn('gnc_pricedb_foreach_price', c_int, c_void_p, PRICE_CB, c_void_p, c_int)
gnc_price_get_commodity = fn('gnc_price_get_commodity', c_void_p, c_void_p)
gnc_price_get_currency = fn('gnc_price_get_currency', c_void_p, c_void_p)
gnc_price_get_time64 = fn('gnc_price_get_time64', c_int64, c_void_p)
gnc_price_get_source_string = fn('gnc_price_get_source_string', c_char_p, c_void_p)
gnc_price_get_typestr = fn('gnc_price_get_typestr', c_char_p, c_void_p)
gnc_price_get_value = fn('gnc_price_get_value', Numeric, c_void_p)
gnc_commodity_get_mnemonic = fn('gnc_commodity_get_mnemonic', c_char_p, c_void_p)


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


def show_prices(label, book_ptr):
    print(f'  {label}:')

    def each(p, _data):
        v = gnc_price_get_value(p)
        print(f'    {s(gnc_commodity_get_mnemonic(gnc_price_get_commodity(p)))}'
              f'/{s(gnc_commodity_get_mnemonic(gnc_price_get_currency(p)))}'
              f' {v.num}/{v.denom} source={s(gnc_price_get_source_string(p))!r}'
              f' type={s(gnc_price_get_typestr(p))!r} time={fmt(gnc_price_get_time64(p))}')
        return 1

    gnc_pricedb_foreach_price(gnc_pricedb_get_db(book_ptr), PRICE_CB(each), None, 1)
    sys.stdout.flush()


def session(url, mode):
    if hasattr(gnucash, 'SessionOpenMode'):
        return Session(url, getattr(gnucash.SessionOpenMode, mode))
    if mode == 'SESSION_NEW_STORE':
        return Session(url, is_new=True)
    if mode == 'SESSION_READ_ONLY':
        return Session(url, ignore_lock=True)
    return Session(url)


print(f'TAG={os.environ.get("TAG")} TZ={os.environ.get("TZ")} tzname={time.tzname}')
print(f'gtk_init_check -> {gtk_init_check(None, None)}')
if gnc_ledger_display_simple is None or gnc_split_register_save is None:
    sys.stdout.flush()
    os._exit(0)

tmp = tempfile.mkdtemp()
path = os.path.join(tmp, 'book.gnucash')
sess = session('xml://' + path, 'SESSION_NEW_STORE')
book = sess.book
table = book.get_table()
usd = table.lookup('CURRENCY', 'USD')
table.insert(GncCommodity(book, 'Amazon.com', 'NASDAQ', 'AMZN', '', 10000))
amzn = table.lookup('NASDAQ', 'AMZN')


def account(name, commodity, kind, parent):
    acct = Account(book)
    acct.BeginEdit()
    acct.SetName(name)
    acct.SetType(kind)
    acct.SetCommodity(commodity)
    parent.append_child(acct)
    acct.CommitEdit()
    return acct


brokerage = account('Brokerage', usd, ACCT_TYPE_ASSET, book.get_root_account())
stock = account('AMZN', amzn, ACCT_TYPE_STOCK, brokerage)
bank = account('Bank USD', usd, ACCT_TYPE_BANK, book.get_root_account())
sess.save()
book_ptr = ptr(book)
gnc_set_current_session(ptr(sess))
gnc_component_manager_init()

# The cell factory is empty until the register's cell types are added, which
# the gnucash program does at start-up: gnucash_register_add_cell_types from
# 4.x on, the register-gnome module's init on 3.x. Without it the layout has no
# date, shares or price cell.
if getattr(lib, 'gnucash_register_add_cell_types', None) is not None:
    lib.gnucash_register_add_cell_types()
    print('gnucash_register_add_cell_types()')
elif getattr(lib, 'libgncmod_register_gnome_gnc_module_init', None) is not None:
    lib.libgncmod_register_gnome_gnc_module_init.argtypes = [c_int]
    print(f'libgncmod_register_gnome_gnc_module_init(0) -> '
          f'{lib.libgncmod_register_gnome_gnc_module_init(0)}')

ledger = gnc_ledger_display_simple(ptr(stock))
reg = gnc_ledger_display_get_split_register(ledger)
reg_table = c_void_p.from_address(reg).value            # struct split_register { Table *table; ...
layout = c_void_p.from_address(reg_table).value         # struct table { TableLayout *layout; ...
blank = gnc_split_register_get_blank_split(reg)
vcell = VirtualCellLocation()
found = gnc_split_register_get_split_virt_loc(reg, blank, byref(vcell))
print(f'ledger {ledger:#x} register {reg:#x} blank split {blank:#x}'
      f' at row {vcell.virt_row} col {vcell.virt_col} (found {found})')
gnc_table_move_cursor(reg_table, VirtualLocation(vcell, 0, 0))


def cell(name):
    c = gnc_table_layout_get_cell(layout, name)
    if not c:
        print(f'  no "{name.decode()}" cell in this register')
    return c


date_cell = cell(b'date')
gnc_date_cell_set_value(date_cell, 9, 2, 2026)
gnc_basic_cell_set_changed(date_cell, 1)
description = cell(b'description')
gnc_basic_cell_set_value(description, b'Probe buy')
gnc_basic_cell_set_changed(description, 1)
# "transfer" is the one-line ledger's Transfer column. "account" is the split's
# own account: setting it moved the stock split onto Bank USD, and the register
# then had no priced account to record a price for.
transfer = cell(b'transfer') or cell(b'account')
gnc_combo_cell_set_value(transfer, b'Bank USD')
gnc_basic_cell_set_changed(transfer, 1)
shares = cell(b'shares')
gnc_price_cell_set_value(shares, Numeric(10, 1))
gnc_basic_cell_set_changed(shares, 1)
debit = cell(b'debit')
gnc_price_cell_set_value(debit, Numeric(218450, 100))
gnc_basic_cell_set_changed(debit, 1)
for name, c in ((b'date', date_cell), (b'description', description), (b'account', transfer),
                (b'shares', shares), (b'price', cell(b'price')), (b'debit', debit)):
    if c:
        print(f'  cell {name.decode()!r} holds {s(gnc_basic_cell_get_value(c))!r}')
print(f'  cursor changed: {gnc_table_current_cursor_changed(reg_table, 0)}')
sys.stdout.flush()

trans = gnc_split_register_get_current_trans(reg)
reg_type = c_int.from_address(reg + 8).value           # ... SplitRegisterType type; SplitRegisterStyle style;
reg_style = c_int.from_address(reg + 12).value
print(f'register type {reg_type} style {reg_style}')
print(f'gnc_split_register_save(reg, TRUE) -> {gnc_split_register_save(reg, 1)}')
print(f'transaction {s(xaccTransGetDescription(trans))!r} dated {fmt(xaccTransGetDate(trans))}')
xaccTransGetSplitList = fn('xaccTransGetSplitList', c_void_p, c_void_p)  # noqa: N816 — GnuCash's own C name
xaccSplitGetAccount = fn('xaccSplitGetAccount', c_void_p, c_void_p)  # noqa: N816 — GnuCash's own C name
xaccSplitGetAmount = fn('xaccSplitGetAmount', Numeric, c_void_p)  # noqa: N816 — GnuCash's own C name
xaccSplitGetValue = fn('xaccSplitGetValue', Numeric, c_void_p)  # noqa: N816 — GnuCash's own C name
xaccAccountGetName = fn('xaccAccountGetName', c_char_p, c_void_p)  # noqa: N816 — GnuCash's own C name
node = xaccTransGetSplitList(trans)
while node:
    split_ptr, node = c_void_p.from_address(node).value, c_void_p.from_address(node + 8).value
    acct = xaccSplitGetAccount(split_ptr)
    amount, value = xaccSplitGetAmount(split_ptr), xaccSplitGetValue(split_ptr)
    print(f'  split {s(xaccAccountGetName(acct)) if acct else None!r}'
          f' amount {amount.num}/{amount.denom} value {value.num}/{value.denom}')
show_prices('prices after the save', book_ptr)

sess.save()
sess.end()
reread = session('xml://' + path, 'SESSION_READ_ONLY')
show_prices('prices in the reloaded book', ptr(reread.book))
try:
    with gzip.open(path, 'rt') as f:
        xml = f.read()
except OSError:
    with open(path) as f:
        xml = f.read()
print('<price> blocks in the file:')
for block in re.findall(r'<price>.*?</price>', xml, re.S):
    ids = re.findall(r'<cmdty:id>(.*?)</cmdty:id>', block)
    stamp = re.search(r'<ts:date>(.*?)</ts:date>', block)
    source = re.search(r'<price:source>(.*?)</price:source>', block)
    print(f'  {"/".join(ids)} {stamp.group(1) if stamp else None!r}'
          f' {source.group(1) if source else None!r}')
sys.stdout.flush()
os._exit(0)
