"""Probe: what time the stock transaction assistant gives the price it records.

Drives gnc_stock_transaction_assistant under Xvfb, page by page, the way a
person fills it in: the first transaction type offered, 2026-02-09 typed into
the details page's date field, 10 shares, a value of 2,184.50 USD, Bank USD as
the cash account, then Apply. Prints the transaction's date and the price the
assistant added, then the <price> blocks of the saved file.

Run inside an image:
  docker run --rm -e TZ=America/Toronto -e TAG=<tag> -v "$PWD:/workspace" -w /workspace \
      gnucash-dev:<tag> sh tests/research/run_a_gui_probe_under_xvfb.sh tests/research/how_the_stock_assistant_times_a_price_probe.py
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
    c_size_t,
    c_void_p,
    string_at,
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
lib = CDLL(None)
# An amount field with "10" in it runs gnc_exp_parser_parse, which loads Scheme
# through Guile: gdb showed it segfault in scm_primitive_load_path while Guile
# was not started in this process. The gnucash program starts it itself.
if getattr(lib, 'scm_init_guile', None) is not None:
    lib.scm_init_guile()


class Numeric(Structure):
    _fields_ = [('num', c_int64), ('denom', c_int64)]


class GList(Structure):
    _fields_ = [('data', c_void_p), ('next', c_void_p), ('prev', c_void_p)]


def fn(name, restype, *argtypes):
    f = getattr(lib, name, None)
    if f is None:
        return None
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


FORALL_CB = CFUNCTYPE(None, c_void_p, c_void_p)
PRICE_CB = CFUNCTYPE(c_int, c_void_p, c_void_p)

gtk_init_check = fn('gtk_init_check', c_int, c_void_p, c_void_p)
gtk_window_list_toplevels = fn('gtk_window_list_toplevels', c_void_p)
gtk_window_get_title = fn('gtk_window_get_title', c_char_p, c_void_p)
gtk_widget_get_visible = fn('gtk_widget_get_visible', c_int, c_void_p)
gtk_widget_get_parent = fn('gtk_widget_get_parent', c_void_p, c_void_p)
gtk_container_get_type = fn('gtk_container_get_type', c_size_t)
gtk_container_forall = fn('gtk_container_forall', None, c_void_p, FORALL_CB, c_void_p)
gtk_buildable_get_name = fn('gtk_buildable_get_name', c_char_p, c_void_p)
gtk_entry_set_text = fn('gtk_entry_set_text', None, c_void_p, c_char_p)
gtk_label_get_text = fn('gtk_label_get_text', c_char_p, c_void_p)
gtk_combo_box_text_get_active_text = fn('gtk_combo_box_text_get_active_text', c_void_p, c_void_p)
gtk_assistant_next_page = fn('gtk_assistant_next_page', None, c_void_p)
gtk_assistant_get_current_page = fn('gtk_assistant_get_current_page', c_int, c_void_p)
gtk_assistant_get_n_pages = fn('gtk_assistant_get_n_pages', c_int, c_void_p)
gtk_assistant_get_nth_page = fn('gtk_assistant_get_nth_page', c_void_p, c_void_p, c_int)
gtk_assistant_get_page_title = fn('gtk_assistant_get_page_title', c_char_p, c_void_p, c_void_p)
gtk_events_pending = fn('gtk_events_pending', c_int)
gtk_main_iteration_do = fn('gtk_main_iteration_do', c_int, c_int)
gdk_event_new = fn('gdk_event_new', c_void_p, c_int)
g_type_name = fn('g_type_name', c_char_p, c_size_t)
g_type_check_instance_is_a = fn('g_type_check_instance_is_a', c_int, c_void_p, c_size_t)
g_free = fn('g_free', None, c_void_p)
g_signal_emit_by_name = lib.g_signal_emit_by_name  # variadic: no argtypes

gnc_set_current_session = fn('gnc_set_current_session', None, c_void_p)
gnc_component_manager_init = fn('gnc_component_manager_init', None)
gnc_stock_transaction_assistant = fn('gnc_stock_transaction_assistant', None, c_void_p, c_void_p)
gnc_date_edit_get_date_end = fn('gnc_date_edit_get_date_end', c_int64, c_void_p)
gnc_amount_edit_gtk_entry = fn('gnc_amount_edit_gtk_entry', c_void_p, c_void_p)
gnc_amount_edit_set_amount = fn('gnc_amount_edit_set_amount', None, c_void_p, Numeric)
gnc_account_sel_set_account = fn('gnc_account_sel_set_account', None, c_void_p, c_void_p, c_int)
qof_print_date = fn('qof_print_date', c_void_p, c_int64)
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

GDK_FOCUS_CHANGE = 12


def ptr(obj):
    inst = getattr(obj, 'instance', obj)
    try:
        return int(inst)
    except TypeError:
        return int(inst.instance)


def local(y, mo, d, h=0, mi=0, s=0):
    return int(time.mktime((y, mo, d, h, mi, s, 0, 0, -1)))


def fmt(t):
    return (f'{time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(t))}'
            f' = {time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t))}Z')


def s(b):
    return b.decode() if b else None


def glist(p):
    while p:
        node = GList.from_address(p)
        yield node.data
        p = node.next


def type_name(widget):
    klass = c_void_p.from_address(widget).value
    return s(g_type_name(c_size_t.from_address(klass).value))


def children(widget):
    found = []
    callback = FORALL_CB(lambda child, _data: found.append(child))
    gtk_container_forall(widget, callback, None)
    return found


def descendants(widget):
    yield widget
    if g_type_check_instance_is_a(widget, gtk_container_get_type()):
        for child in children(widget):
            yield from descendants(child)


def parent_name(widget):
    parent = gtk_widget_get_parent(widget)
    return s(gtk_buildable_get_name(parent)) if parent else None


def pump():
    for _ in range(500):
        if not gtk_events_pending():
            return
        gtk_main_iteration_do(0)


def focus_out(entry):
    ret = c_int(0)
    g_signal_emit_by_name(c_void_p(entry), b'focus-out-event',
                          c_void_p(gdk_event_new(GDK_FOCUS_CHANGE)), byref(ret))


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
if gnc_stock_transaction_assistant is None:
    print('gnc_stock_transaction_assistant is not in this build')
    sys.stdout.flush()
    os._exit(0)
print(f'gtk_init_check -> {gtk_init_check(None, None)}')

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

before = list(glist(gtk_window_list_toplevels()))
gnc_stock_transaction_assistant(None, ptr(stock))
pump()
opened = [w for w in glist(gtk_window_list_toplevels())
          if w not in before and gtk_widget_get_visible(w)]
print(f'windows opened: {[s(gtk_window_get_title(w)) for w in opened]}')
assistant = opened[-1]
n_pages = gtk_assistant_get_n_pages(assistant)
typed_date = local(2026, 2, 9, 12, 0, 0)

for _step in range(n_pages + 2):
    index = gtk_assistant_get_current_page(assistant)
    page = gtk_assistant_get_nth_page(assistant, index)
    widgets = list(descendants(page))
    print(f'page {index}/{n_pages - 1} {s(gtk_assistant_get_page_title(assistant, page))!r}')
    amount_edits = {parent_name(w): w for w in widgets if type_name(w) == 'GNCAmountEdit'}
    if amount_edits:
        print(f'  amount edits under: {sorted(k or "" for k in amount_edits)}')
    for w in widgets:
        name = s(gtk_buildable_get_name(w))
        if name == 'transaction_type_page_combobox':
            text = gtk_combo_box_text_get_active_text(w)
            print(f'  transaction type: {string_at(text).decode() if text else None!r}')
            g_free(text)
        if name == 'transaction_description_entry':
            gtk_entry_set_text(w, b'Probe buy')
    for date_edit in [w for w in widgets if type_name(w) == 'GNCDateEdit']:
        entry = next(w for w in descendants(date_edit)
                     if type_name(w) == 'GtkEntry' and gtk_widget_get_parent(w) == date_edit)
        text_ptr = qof_print_date(typed_date)
        text = string_at(text_ptr)
        g_free(text_ptr)
        gtk_entry_set_text(entry, text)
        focus_out(entry)
        print(f'  typed {text.decode()!r} into the date field;'
              f' gnc_date_edit_get_date_end now {fmt(gnc_date_edit_get_date_end(date_edit))}')
    for owner, value in (('stock_amount_table', Numeric(10, 1)),
                         ('stock_value_table', Numeric(218450, 100)),
                         ('cash_table', Numeric(218450, 100))):
        if owner in amount_edits:
            gnc_amount_edit_set_amount(amount_edits[owner], value)
            focus_out(gnc_amount_edit_gtk_entry(amount_edits[owner]))
            print(f'  {owner}: {value.num}/{value.denom}')
    for sel in [w for w in widgets if type_name(w) == 'GNCAccountSel']:
        if parent_name(sel) == 'cash_table':
            gnc_account_sel_set_account(sel, ptr(bank), 0)
            print('  cash account: Bank USD')
    pump()
    if index == n_pages - 1:
        for w in widgets:
            if type_name(w) == 'GtkLabel' and gtk_label_get_text(w):
                print(f'  | {s(gtk_label_get_text(w))}')
        # the glade wires stock_assistant_finish_cb to "close"
        print('  Finish ("close")')
        g_signal_emit_by_name(c_void_p(assistant), b'close')
        pump()
        break
    gtk_assistant_next_page(assistant)
    pump()

for split in bank.GetSplitList():
    txn = ptr(split.GetParent())
    print(f'transaction {s(xaccTransGetDescription(txn))!r} dated {fmt(xaccTransGetDate(txn))}')
show_prices('prices after Apply', book_ptr)

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
print('<price> times in the file:')
for block in re.findall(r'<price>.*?</price>', xml, re.S):
    ids = re.findall(r'<cmdty:id>(.*?)</cmdty:id>', block)
    stamp = re.search(r'<ts:date>(.*?)</ts:date>', block)
    source = re.search(r'<price:source>(.*?)</price:source>', block)
    print(f'  {"/".join(ids)} {stamp.group(1) if stamp else None!r}'
          f' {source.group(1) if source else None!r}')
sys.stdout.flush()
os._exit(0)
