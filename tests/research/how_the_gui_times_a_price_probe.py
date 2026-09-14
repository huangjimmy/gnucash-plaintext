"""Probe: what time GnuCash's own GUI code gives a price, on this build.

Nothing here computes a time. Each case drives the function GnuCash's GUI
runs, under Xvfb, and reads back what the price database holds; the book is
then saved, reloaded, and the <price> blocks of the file itself are printed.

- A date edit's get_date / get_date_end / get_gdate: the Price Editor and the
  post-invoice dialog read get_date, the stock assistant get_date_end, the
  transfer dialog get_gdate.
- The register's date cell, which 3.x's register prices by.
- xaccTransRecordPrice on a transaction dated the way the register dates one
  (xaccTransSetDatePostedSecsNormalized), which 4.x+'s register prices by.
- Price Editor: an existing price opened and OK pressed with nothing changed.
- Price Editor: a new price, a date typed into its date field, OK.
- Transfer dialog: a rate typed, OK.
- Transfer dialog: a to-amount typed, OK.

Run inside an image:
  docker run --rm -e TZ=America/Toronto -e TAG=<tag> -v "$PWD:/workspace" -w /workspace \
      gnucash-dev:<tag> sh tests/research/run_a_gui_probe_under_xvfb.sh tests/research/how_the_gui_times_a_price_probe.py

Add -e ONLY_DATES=1 to run only the date edit and date cell cases, as done
under TZ=Asia/Tokyo, Pacific/Kiritimati and Pacific/Pago_Pago.
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
    c_uint,
    c_void_p,
    string_at,
)

faulthandler.dump_traceback_later(150, exit=True)

import gnucash  # noqa: E402
from gnucash import (  # noqa: E402
    Account,
    GncCommodity,
    GncNumeric,
    GncPrice,
    Session,
    Split,
    Transaction,
)
from gnucash.gnucash_core_c import ACCT_TYPE_BANK, ACCT_TYPE_CURRENCY, ACCT_TYPE_STOCK  # noqa: E402

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


class Numeric(Structure):
    _fields_ = [('num', c_int64), ('denom', c_int64)]


class GDate(Structure):
    _fields_ = [('a', c_uint), ('b', c_uint)]


class GList(Structure):
    _fields_ = [('data', c_void_p), ('next', c_void_p), ('prev', c_void_p)]


def fn(name, restype, *argtypes):
    f = getattr(lib, name, None)
    if f is None:
        return None
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


gtk_init_check = fn('gtk_init_check', c_int, c_void_p, c_void_p)
gtk_window_list_toplevels = fn('gtk_window_list_toplevels', c_void_p)
gtk_window_get_title = fn('gtk_window_get_title', c_char_p, c_void_p)
gtk_widget_get_visible = fn('gtk_widget_get_visible', c_int, c_void_p)
gtk_widget_get_parent = fn('gtk_widget_get_parent', c_void_p, c_void_p)
gtk_container_get_type = fn('gtk_container_get_type', c_size_t)
gtk_container_get_children = fn('gtk_container_get_children', c_void_p, c_void_p)
gtk_buildable_get_name = fn('gtk_buildable_get_name', c_char_p, c_void_p)
gtk_entry_get_text = fn('gtk_entry_get_text', c_char_p, c_void_p)
gtk_entry_set_text = fn('gtk_entry_set_text', None, c_void_p, c_char_p)
gtk_toggle_button_set_active = fn('gtk_toggle_button_set_active', None, c_void_p, c_int)
gtk_dialog_response = fn('gtk_dialog_response', None, c_void_p, c_int)
gtk_events_pending = fn('gtk_events_pending', c_int)
gtk_main_iteration_do = fn('gtk_main_iteration_do', c_int, c_int)
gdk_event_new = fn('gdk_event_new', c_void_p, c_int)
g_type_name = fn('g_type_name', c_char_p, c_size_t)
g_type_check_instance_is_a = fn('g_type_check_instance_is_a', c_int, c_void_p, c_size_t)
g_date_clear = fn('g_date_clear', None, c_void_p, c_uint)
g_free = fn('g_free', None, c_void_p)
g_signal_emit_by_name = lib.g_signal_emit_by_name  # variadic: no argtypes

gnc_set_current_session = fn('gnc_set_current_session', None, c_void_p)
gnc_component_manager_init = fn('gnc_component_manager_init', None)
gnc_date_edit_new = fn('gnc_date_edit_new', c_void_p, c_int64, c_int, c_int)
gnc_date_edit_set_time = fn('gnc_date_edit_set_time', None, c_void_p, c_int64)
gnc_date_edit_get_date = fn('gnc_date_edit_get_date', c_int64, c_void_p)
gnc_date_edit_get_date_end = fn('gnc_date_edit_get_date_end', c_int64, c_void_p)
gnc_date_edit_get_gdate = fn('gnc_date_edit_get_gdate', None, c_void_p, c_void_p)
gdate_to_time64 = fn('gdate_to_time64', c_int64, GDate)
gnc_date_cell_new = fn('gnc_date_cell_new', c_void_p)
gnc_date_cell_set_value_secs = fn('gnc_date_cell_set_value_secs', None, c_void_p, c_int64)
gnc_date_cell_get_date = fn('gnc_date_cell_get_date', None, c_void_p, c_void_p, c_int)
gnc_amount_edit_gtk_entry = fn('gnc_amount_edit_gtk_entry', c_void_p, c_void_p)
gnc_amount_edit_set_amount = fn('gnc_amount_edit_set_amount', None, c_void_p, Numeric)
gnc_price_edit_dialog = fn('gnc_price_edit_dialog', None, c_void_p, c_void_p, c_void_p, c_int)
gnc_xfer_dialog = fn('gnc_xfer_dialog', c_void_p, c_void_p, c_void_p)
gnc_xfer_dialog_select_to_account = fn('gnc_xfer_dialog_select_to_account', None, c_void_p, c_void_p)
gnc_xfer_dialog_set_amount = fn('gnc_xfer_dialog_set_amount', None, c_void_p, Numeric)
gnc_xfer_dialog_set_date = fn('gnc_xfer_dialog_set_date', None, c_void_p, c_int64)
gnc_xfer_dialog_set_price_edit = fn('gnc_xfer_dialog_set_price_edit', None, c_void_p, Numeric)
gnc_xfer_dialog_is_exchange_dialog = fn('gnc_xfer_dialog_is_exchange_dialog', None, c_void_p, c_void_p)
gnc_xfer_dialog_select_to_currency = fn('gnc_xfer_dialog_select_to_currency', None, c_void_p, c_void_p)
gnc_xfer_dialog_hide_from_account_tree = fn('gnc_xfer_dialog_hide_from_account_tree', None, c_void_p)
gnc_xfer_dialog_hide_to_account_tree = fn('gnc_xfer_dialog_hide_to_account_tree', None, c_void_p)
gncInvoiceAddPrice = fn('gncInvoiceAddPrice', None, c_void_p, c_void_p)  # noqa: N816 — GnuCash's own C name
qof_print_date = fn('qof_print_date', c_void_p, c_int64)
xaccTransSetDatePostedSecsNormalized = fn('xaccTransSetDatePostedSecsNormalized', None, c_void_p, c_int64)  # noqa: N816 — GnuCash's own C name
xaccTransGetDate = fn('xaccTransGetDate', c_int64, c_void_p)  # noqa: N816 — GnuCash's own C name
xaccTransRecordPrice = fn('xaccTransRecordPrice', None, c_void_p, c_int)  # noqa: N816 — GnuCash's own C name
gnc_pricedb_get_db = fn('gnc_pricedb_get_db', c_void_p, c_void_p)
gnc_pricedb_add_price = fn('gnc_pricedb_add_price', c_int, c_void_p, c_void_p)
gnc_price_get_commodity = fn('gnc_price_get_commodity', c_void_p, c_void_p)
gnc_price_get_currency = fn('gnc_price_get_currency', c_void_p, c_void_p)
gnc_price_get_time64 = fn('gnc_price_get_time64', c_int64, c_void_p)
# ctypes, not SWIG: 3.4's set_time64 typemap misreads an int (finding 20)
gnc_price_set_time64 = fn('gnc_price_set_time64', None, c_void_p, c_int64)
gnc_price_get_source_string = fn('gnc_price_get_source_string', c_char_p, c_void_p)
gnc_price_get_typestr = fn('gnc_price_get_typestr', c_char_p, c_void_p)
gnc_price_get_value = fn('gnc_price_get_value', Numeric, c_void_p)
gnc_commodity_get_mnemonic = fn('gnc_commodity_get_mnemonic', c_char_p, c_void_p)
PRICE_CB = CFUNCTYPE(c_int, c_void_p, c_void_p)
gnc_pricedb_foreach_price = fn('gnc_pricedb_foreach_price', c_int, c_void_p, PRICE_CB, c_void_p, c_int)

GNC_PRICE_EDIT = 0
GNC_PRICE_NEW = 1
GTK_RESPONSE_OK = -5
GDK_FOCUS_CHANGE = 12
PRICE_SOURCE_SPLIT_REG = 4


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


FORALL_CB = CFUNCTYPE(None, c_void_p, c_void_p)
gtk_container_forall = fn('gtk_container_forall', None, c_void_p, FORALL_CB, c_void_p)


def children(widget):
    # forall, which includes a container's internal children; get_children does not
    found = []
    callback = FORALL_CB(lambda child, _data: found.append(child))
    gtk_container_forall(widget, callback, None)
    return found


def descendants(widget):
    yield widget
    if g_type_check_instance_is_a(widget, gtk_container_get_type()):
        for child in children(widget):
            yield from descendants(child)


def ancestor_names(widget):
    names = []
    parent = gtk_widget_get_parent(widget)
    while parent:
        names.append(s(gtk_buildable_get_name(parent)))
        parent = gtk_widget_get_parent(parent)
    return names


def pump():
    for _ in range(500):
        if not gtk_events_pending():
            return
        gtk_main_iteration_do(0)


def toplevels():
    return list(glist(gtk_window_list_toplevels()))


def the_new_window(before):
    pump()
    found = [w for w in toplevels() if w not in before and gtk_widget_get_visible(w)]
    print(f'    windows opened: {[s(gtk_window_get_title(w)) for w in found]}')
    return found[-1] if found else None


def first_of(window, gtype, within=None):
    for w in descendants(window):
        if type_name(w) == gtype and (within is None or within in ancestor_names(w)):
            return w
    return None


def date_entry_text(window):
    date_edit = first_of(window, 'GNCDateEdit')
    if date_edit is None:
        print(f'    no GNCDateEdit; widget types: {sorted({type_name(w) for w in descendants(window)})}')
        return None, None, None
    entries = [w for w in descendants(window)
               if type_name(w) == 'GtkEntry' and gtk_widget_get_parent(w) == date_edit]
    if not entries:
        print('    no GtkEntry whose parent is the date edit')
        return date_edit, None, None
    entry = entries[0]
    return date_edit, entry, s(gtk_entry_get_text(entry))


def focus_out(entry):
    ret = c_int(0)
    g_signal_emit_by_name(c_void_p(entry), b'focus-out-event',
                          c_void_p(gdk_event_new(GDK_FOCUS_CHANGE)), byref(ret))


def price_lines(book_ptr):
    lines = []

    def each(p, _data):
        v = gnc_price_get_value(p)
        lines.append(
            f'{s(gnc_commodity_get_mnemonic(gnc_price_get_commodity(p)))}'
            f'/{s(gnc_commodity_get_mnemonic(gnc_price_get_currency(p)))}'
            f' {v.num}/{v.denom} source={s(gnc_price_get_source_string(p))!r}'
            f' type={s(gnc_price_get_typestr(p))!r} time={fmt(gnc_price_get_time64(p))}')
        return 1

    gnc_pricedb_foreach_price(gnc_pricedb_get_db(book_ptr), PRICE_CB(each), None, 1)
    return lines


def show_prices(label, book_ptr, only=None):
    print(f'    {label}:')
    for line in price_lines(book_ptr):
        if only is None or line.startswith(only):
            print(f'      {line}')
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

tmp = tempfile.mkdtemp()
path = os.path.join(tmp, 'book.gnucash')
sess = session('xml://' + path, 'SESSION_NEW_STORE')
book = sess.book
table = book.get_table()


def bank(name, mnemonic):
    acct = Account(book)
    acct.BeginEdit()
    acct.SetName(name)
    acct.SetType(ACCT_TYPE_BANK)
    acct.SetCommodity(table.lookup('CURRENCY', mnemonic))
    book.get_root_account().append_child(acct)
    acct.CommitEdit()
    return acct


cad = bank('Bank CAD', 'CAD')
usd = bank('Bank USD', 'USD')
eur = bank('Bank EUR', 'EUR')
sess.save()
book_ptr = ptr(book)
gnc_set_current_session(ptr(sess))
gnc_component_manager_init()

TIMES = [
    ('15:30:45', local(2026, 1, 1, 15, 30, 45)),
    ('00:30:00', local(2026, 1, 1, 0, 30, 0)),
    ('23:30:00', local(2026, 1, 1, 23, 30, 0)),
]

print('== date edit, show_time off (gnc_date_edit_new)')
date_edit = gnc_date_edit_new(TIMES[0][1], 0, 0)
for _label, t in TIMES:
    gnc_date_edit_set_time(date_edit, t)
    gdate = GDate()
    g_date_clear(byref(gdate), 1)
    gnc_date_edit_get_gdate(date_edit, byref(gdate))
    print(f'  set_time {fmt(t)}')
    print(f'    get_date                  -> {fmt(gnc_date_edit_get_date(date_edit))}')
    print(f'    get_date_end              -> {fmt(gnc_date_edit_get_date_end(date_edit))}')
    print(f'    gdate_to_time64(get_gdate) -> {fmt(gdate_to_time64(gdate))}')

print('== register date cell (gnc_date_cell_new, set_value_secs, get_date)')
cell = gnc_date_cell_new()
for _label, t in TIMES:
    gnc_date_cell_set_value_secs(cell, t)
    out = c_int64(0)
    gnc_date_cell_get_date(cell, byref(out), 0)
    print(f'  set_value_secs {fmt(t)} -> get_date {fmt(out.value)}')
sys.stdout.flush()
if os.environ.get('ONLY_DATES'):
    os._exit(0)

print('== register price: xaccTransRecordPrice on a register-dated transaction')
if xaccTransRecordPrice is None:
    print('  xaccTransRecordPrice is not in this build')
else:
    table.insert(GncCommodity(book, 'Amazon.com', 'NASDAQ', 'AMZN', '', 10000))

    def held(name, commodity, kind):
        acct = Account(book)
        acct.BeginEdit()
        acct.SetName(name)
        acct.SetType(kind)
        acct.SetCommodity(commodity)
        book.get_root_account().append_child(acct)
        acct.CommitEdit()
        return acct

    for label, currency, paid_from, into, value, amount, when in (
        ('10 AMZN into a stock account, in USD', 'USD', usd,
         held('AMZN', table.lookup('NASDAQ', 'AMZN'), ACCT_TYPE_STOCK),
         (218450, 100), (100000, 10000), local(2026, 2, 5, 15, 30, 45)),
        ('100.00 USD into a currency account, in CAD', 'CAD', cad,
         held('USD cash', table.lookup('CURRENCY', 'USD'), ACCT_TYPE_CURRENCY),
         (13642, 100), (10000, 100), local(2026, 2, 5, 23, 30, 0)),
    ):
        txn = Transaction(book)
        txn.BeginEdit()
        txn.SetCurrency(table.lookup('CURRENCY', currency))
        out_split = Split(book)
        out_split.SetParent(txn)
        out_split.SetAccount(paid_from)
        out_split.SetValue(GncNumeric(-value[0], value[1]))
        out_split.SetAmount(GncNumeric(-value[0], value[1]))
        in_split = Split(book)
        in_split.SetParent(txn)
        in_split.SetAccount(into)
        in_split.SetValue(GncNumeric(*value))
        in_split.SetAmount(GncNumeric(*amount))
        xaccTransSetDatePostedSecsNormalized(ptr(txn), when)
        txn.CommitEdit()
        print(f'  {label}: SetDatePostedSecsNormalized({fmt(when)})'
              f' -> xaccTransGetDate {fmt(xaccTransGetDate(ptr(txn)))}')
        xaccTransRecordPrice(ptr(txn), PRICE_SOURCE_SPLIT_REG)
    show_prices('prices after xaccTransRecordPrice(user:split-register)', book_ptr)

for mnemonic, when, source in (
    ('GBP', local(2026, 1, 1, 15, 30, 45), 'Finance::Quote'),
    ('JPY', local(2026, 1, 2, 23, 30, 0), 'user:price-editor'),
):
    print(f'== Price Editor, existing {mnemonic}/CAD price at {fmt(when)} source {source}:'
          ' opened, OK, nothing changed')
    price = GncPrice(book)
    price.begin_edit()
    price.set_commodity(table.lookup('CURRENCY', mnemonic))
    price.set_currency(table.lookup('CURRENCY', 'CAD'))
    gnc_price_set_time64(ptr(price), when)
    price.set_source_string(source)
    price.set_typestr('last')
    price.set_value(GncNumeric(17, 10))
    price.commit_edit()
    gnc_pricedb_add_price(gnc_pricedb_get_db(book_ptr), ptr(price))
    before = toplevels()
    gnc_price_edit_dialog(None, ptr(sess), ptr(price), GNC_PRICE_EDIT)
    dialog = the_new_window(before)
    print(f'    date field shows {date_entry_text(dialog)[2]!r}')
    gtk_dialog_response(dialog, GTK_RESPONSE_OK)
    pump()
    show_prices('after OK', book_ptr, only=f'{mnemonic}/')

print('== Price Editor, new EUR/CAD price, 2026-03-10 typed into the date field, OK')
template = GncPrice(book)
template.begin_edit()
template.set_commodity(table.lookup('CURRENCY', 'EUR'))
template.set_currency(table.lookup('CURRENCY', 'CAD'))
gnc_price_set_time64(ptr(template), local(2025, 12, 1, 15, 30, 45))
template.set_source_string('user:price-editor')
template.set_typestr('last')
template.set_value(GncNumeric(15, 10))
template.commit_edit()
before = toplevels()
gnc_price_edit_dialog(None, ptr(sess), ptr(template), GNC_PRICE_NEW)
dialog = the_new_window(before)
date_edit, entry, shown = date_entry_text(dialog)
typed_ptr = qof_print_date(local(2026, 3, 10, 12, 0, 0))
typed = string_at(typed_ptr)
g_free(typed_ptr)
if entry is not None:
    print(f'    date field showed {shown!r}; typing {typed.decode()!r}')
    gtk_entry_set_text(entry, typed)
    focus_out(entry)
else:
    print('    nothing to type into; gnc_date_edit_set_time(2026-03-10 15:30:45 local) instead')
    gnc_date_edit_set_time(date_edit, local(2026, 3, 10, 15, 30, 45))
gnc_amount_edit_set_amount(first_of(dialog, 'GNCAmountEdit'), Numeric(15, 10))
print(f'    date field shows {date_entry_text(dialog)[2]!r}')
gtk_dialog_response(dialog, GTK_RESPONSE_OK)
pump()
show_prices('after OK', book_ptr, only='EUR/')

print('== Transfer dialog, Bank CAD -> Bank USD, 100.00, date set to'
      f' {fmt(local(2026, 2, 3, 15, 30, 45))}, rate 0.73 typed, OK')
before = toplevels()
xfer = gnc_xfer_dialog(None, ptr(cad))
dialog = the_new_window(before)
gnc_xfer_dialog_select_to_account(xfer, ptr(usd))
gnc_xfer_dialog_set_amount(xfer, Numeric(10000, 100))
gnc_xfer_dialog_set_date(xfer, local(2026, 2, 3, 15, 30, 45))
gnc_xfer_dialog_set_price_edit(xfer, Numeric(73, 100))
focus_out(gnc_amount_edit_gtk_entry(first_of(dialog, 'GNCAmountEdit', within='price_hbox')))
print(f'    date field shows {date_entry_text(dialog)[2]!r}')
gtk_dialog_response(dialog, GTK_RESPONSE_OK)
pump()
show_prices('after OK', book_ptr, only='USD/')
show_prices('after OK', book_ptr, only='CAD/')

print('== Transfer dialog, Bank CAD -> Bank EUR, 100.00, date set to'
      f' {fmt(local(2026, 2, 4, 23, 30, 0))}, to-amount 68.00 typed, OK')
before = toplevels()
xfer = gnc_xfer_dialog(None, ptr(cad))
dialog = the_new_window(before)
gnc_xfer_dialog_select_to_account(xfer, ptr(eur))
gnc_xfer_dialog_set_amount(xfer, Numeric(10000, 100))
gnc_xfer_dialog_set_date(xfer, local(2026, 2, 4, 23, 30, 0))
for w in descendants(dialog):
    if s(gtk_buildable_get_name(w)) == 'amount_radio':
        gtk_toggle_button_set_active(w, 1)
to_amount = first_of(dialog, 'GNCAmountEdit', within='right_amount_hbox')
gnc_amount_edit_set_amount(to_amount, Numeric(6800, 100))
focus_out(gnc_amount_edit_gtk_entry(to_amount))
print(f'    date field shows {date_entry_text(dialog)[2]!r}')
gtk_dialog_response(dialog, GTK_RESPONSE_OK)
pump()
show_prices('after OK', book_ptr, only='EUR/')
show_prices('after OK', book_ptr, only='CAD/')

print('== Transfer dialog in exchange-rate mode, as posting a USD invoice to CAD income opens it:'
      f' from Bank USD, to currency CAD, post date {fmt(local(2026, 2, 6, 15, 30, 45))},'
      ' rate 1.37 typed, OK')
exch_rate = Numeric(0, 1)
before = toplevels()
xfer = gnc_xfer_dialog(None, ptr(usd))
dialog = the_new_window(before)
gnc_xfer_dialog_is_exchange_dialog(xfer, byref(exch_rate))
gnc_xfer_dialog_select_to_currency(xfer, ptr(table.lookup('CURRENCY', 'CAD')))
gnc_xfer_dialog_set_date(xfer, local(2026, 2, 6, 15, 30, 45))
gnc_xfer_dialog_set_amount(xfer, Numeric(10000, 100))
gnc_xfer_dialog_set_price_edit(xfer, Numeric(137, 100))
gnc_xfer_dialog_hide_from_account_tree(xfer)
gnc_xfer_dialog_hide_to_account_tree(xfer)
focus_out(gnc_amount_edit_gtk_entry(first_of(dialog, 'GNCAmountEdit', within='price_hbox')))
print(f'    date field shows {date_entry_text(dialog)[2]!r}')
gtk_dialog_response(dialog, GTK_RESPONSE_OK)
pump()
print(f'    exchange rate handed back to the invoice: {exch_rate.num}/{exch_rate.denom}')
show_prices('after OK', book_ptr, only='USD/')
show_prices('after OK', book_ptr, only='CAD/')

print('== an invoice holding a temporary price (gncInvoiceAddPrice), as posting stores its rate')
from gnucash.gnucash_business import Customer, Invoice  # noqa: E402

customer = Customer(book, 'C1', table.lookup('CURRENCY', 'USD'), 'Probe Customer')
invoice = Invoice(book, 'I1', table.lookup('CURRENCY', 'USD'), customer)
temp = GncPrice(book)
temp.begin_edit()
temp.set_commodity(table.lookup('CURRENCY', 'CAD'))
temp.set_currency(table.lookup('CURRENCY', 'USD'))
gnc_price_set_time64(ptr(temp), local(2026, 2, 7, 15, 30, 45))
temp.set_source_string('temporary')
temp.set_typestr('last')
temp.set_value(GncNumeric(73, 100))
temp.commit_edit()
gncInvoiceAddPrice(ptr(invoice), ptr(temp))
show_prices('price database after gncInvoiceAddPrice', book_ptr, only='CAD/USD')

print('== saved and reloaded')
sys.stdout.flush()
sess.save()
sess.end()
time.sleep(1)
reread = session('xml://' + path, 'SESSION_READ_ONLY')
show_prices('prices in the reloaded book', ptr(reread.book))
try:
    with gzip.open(path, 'rt') as f:
        xml = f.read()
except OSError:
    with open(path) as f:
        xml = f.read()
pricedb = re.search(r'<gnc:pricedb.*?</gnc:pricedb>', xml, re.S)
pricedb = pricedb.group(0) if pricedb else ''
print("    <price> blocks in the file's <gnc:pricedb>:")
for block in re.findall(r'<price>.*?</price>', pricedb, re.S):
    def tag(name, text=block):
        m = re.search(rf'<{name}>\s*(.*?)\s*</{name}>', text, re.S)
        return re.sub(r'\s+', ' ', m.group(1)) if m else None
    cmdty = re.sub(r'<[^>]+>', ' ', tag('price:commodity') or '').split()
    curr = re.sub(r'<[^>]+>', ' ', tag('price:currency') or '').split()
    print(f'      {"/".join(cmdty[1:2] + curr[1:2])} time={tag("ts:date")!r}'
          f' source={tag("price:source")!r} type={tag("price:type")!r}'
          f' value={tag("price:value")!r}')
rest = xml.replace(pricedb, '')
print(f'    <price> blocks outside <gnc:pricedb>: {len(re.findall(r"<price>", rest))}')
for m in re.finditer(r'temporary', rest):
    print(f'      "temporary" outside it, under: '
          f'{re.findall(r"<([a-z]+:[a-z-]+)[ >]", rest[max(0, m.start() - 800):m.start()])[-8:]}')
print(f'    invoice elements in the file: {sorted(set(re.findall(r"<(invoice:[a-z-]+)[ >]", xml)))}')
sys.stdout.flush()
os._exit(0)
