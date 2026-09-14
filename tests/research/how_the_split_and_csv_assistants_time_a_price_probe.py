"""Probe: what time the stock split assistant and the CSV price import assistant give a price.

Both are driven under Xvfb the way a person fills them in:

- Stock split (gnc_stock_split_dialog), on an account holding 10 NASDAQ:AMZN:
  2026-02-12 typed into the date field, 10 shares distributed, a price of
  110.00 USD, Apply.
- CSV price import (gnc_file_csv_price_import): a file of two prices,
  2026-02-10 for AMZN and 2026-02-11 for MSFT, the file picked in the file
  chooser, each column's type chosen in the preview's column header, Apply.

Prints what the price database holds after each, then the <price> blocks of
the saved file.

Run inside an image:
  docker run --rm -e TZ=America/Toronto -e TAG=<tag> -v "$PWD:/workspace" -w /workspace \
      gnucash-dev:<tag> sh tests/research/run_a_gui_probe_under_xvfb.sh \
      tests/research/how_the_split_and_csv_assistants_time_a_price_probe.py

Add -e SKIP_SPLIT=1 to run only the CSV price import.
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
    c_char,
    c_char_p,
    c_int,
    c_int64,
    c_size_t,
    c_void_p,
    string_at,
)

faulthandler.dump_traceback_later(200, exit=True)

import gnucash  # noqa: E402
from gnucash import Account, GncCommodity, GncNumeric, Session, Split, Transaction  # noqa: E402
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
for names in (('libgnc-generic-import.so', 'libgncmod-generic-import.so'),
              ('libgnc-csv-import.so', 'libgncmod-csv-import.so')):
    try:
        load(*names)
    except (OSError, SystemExit) as err:
        print(f'loading {names}: {err}')
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


class TreeIter(Structure):
    _fields_ = [('stamp', c_int), ('user_data', c_void_p), ('user_data2', c_void_p),
                ('user_data3', c_void_p)]


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
gtk_container_child_get = lib.gtk_container_child_get  # variadic: no argtypes
gtk_buildable_get_name = fn('gtk_buildable_get_name', c_char_p, c_void_p)
gtk_entry_set_text = fn('gtk_entry_set_text', None, c_void_p, c_char_p)
gtk_label_get_text = fn('gtk_label_get_text', c_char_p, c_void_p)
gtk_assistant_next_page = fn('gtk_assistant_next_page', None, c_void_p)
gtk_assistant_get_current_page = fn('gtk_assistant_get_current_page', c_int, c_void_p)
gtk_assistant_get_n_pages = fn('gtk_assistant_get_n_pages', c_int, c_void_p)
gtk_assistant_get_nth_page = fn('gtk_assistant_get_nth_page', c_void_p, c_void_p, c_int)
gtk_assistant_get_page_title = fn('gtk_assistant_get_page_title', c_char_p, c_void_p, c_void_p)
gtk_assistant_get_page_complete = fn('gtk_assistant_get_page_complete', c_int, c_void_p, c_void_p)
gtk_file_chooser_set_filename = fn('gtk_file_chooser_set_filename', c_int, c_void_p, c_char_p)
gtk_file_chooser_get_filename = fn('gtk_file_chooser_get_filename', c_void_p, c_void_p)
gtk_combo_box_get_model = fn('gtk_combo_box_get_model', c_void_p, c_void_p)
gtk_combo_box_set_active_iter = fn('gtk_combo_box_set_active_iter', None, c_void_p, c_void_p)
gtk_tree_model_get_iter_first = fn('gtk_tree_model_get_iter_first', c_int, c_void_p, c_void_p)
gtk_tree_model_iter_next = fn('gtk_tree_model_iter_next', c_int, c_void_p, c_void_p)
gtk_tree_model_get_value = fn('gtk_tree_model_get_value', None, c_void_p, c_void_p, c_int, c_void_p)
gtk_events_pending = fn('gtk_events_pending', c_int)
gtk_main_iteration_do = fn('gtk_main_iteration_do', c_int, c_int)
gdk_event_new = fn('gdk_event_new', c_void_p, c_int)
g_type_name = fn('g_type_name', c_char_p, c_size_t)
g_type_check_instance_is_a = fn('g_type_check_instance_is_a', c_int, c_void_p, c_size_t)
g_value_get_int = fn('g_value_get_int', c_int, c_void_p)
g_value_unset = fn('g_value_unset', None, c_void_p)
g_object_get_data = fn('g_object_get_data', c_void_p, c_void_p, c_char_p)
g_free = fn('g_free', None, c_void_p)
g_signal_emit_by_name = lib.g_signal_emit_by_name  # variadic: no argtypes

gnc_set_current_session = fn('gnc_set_current_session', None, c_void_p)
gnc_component_manager_init = fn('gnc_component_manager_init', None)
gnc_stock_split_dialog = fn('gnc_stock_split_dialog', None, c_void_p, c_void_p)
gnc_file_csv_price_import = fn('gnc_file_csv_price_import', None)
gnc_version = fn('gnc_version', c_char_p)
gnc_date_edit_get_date = fn('gnc_date_edit_get_date', c_int64, c_void_p)
gnc_amount_edit_set_amount = fn('gnc_amount_edit_set_amount', None, c_void_p, Numeric)
qof_print_date = fn('qof_print_date', c_void_p, c_int64)
xaccTransSetDatePostedSecsNormalized = fn('xaccTransSetDatePostedSecsNormalized', None, c_void_p, c_int64)  # noqa: N816 — GnuCash's own C name
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
PRICE_DATE, PRICE_AMOUNT, PRICE_FROM_SYMBOL, PRICE_FROM_NAMESPACE, PRICE_TO_CURRENCY = 1, 2, 3, 4, 5


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


def pump(rounds=3):
    for _ in range(rounds):
        for _ in range(500):
            if not gtk_events_pending():
                break
            gtk_main_iteration_do(0)
        time.sleep(0.05)


def focus_out(entry):
    ret = c_int(0)
    g_signal_emit_by_name(c_void_p(entry), b'focus-out-event',
                          c_void_p(gdk_event_new(GDK_FOCUS_CHANGE)), byref(ret))


def toplevels():
    return list(glist(gtk_window_list_toplevels()))


def the_new_window(before):
    pump()
    found = [w for w in toplevels() if w not in before and gtk_widget_get_visible(w)]
    print(f'  windows opened: {[s(gtk_window_get_title(w)) for w in found]}')
    return found[-1] if found else None


def page_now(assistant):
    index = gtk_assistant_get_current_page(assistant)
    page = gtk_assistant_get_nth_page(assistant, index)
    print(f'  page {index}/{gtk_assistant_get_n_pages(assistant) - 1}'
          f' {s(gtk_assistant_get_page_title(assistant, page))!r}')
    return index, page


def labels(widget):
    for w in descendants(widget):
        if type_name(w) == 'GtkLabel' and gtk_label_get_text(w):
            print(f'    | {s(gtk_buildable_get_name(w))}: {s(gtk_label_get_text(w))!r}'[:300])


def type_date(date_edit, when):
    entry = next(w for w in descendants(date_edit)
                 if type_name(w) == 'GtkEntry' and gtk_widget_get_parent(w) == date_edit)
    text_ptr = qof_print_date(when)
    text = string_at(text_ptr)
    g_free(text_ptr)
    gtk_entry_set_text(entry, text)
    focus_out(entry)
    return text.decode()


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

tmp = tempfile.mkdtemp()
path = os.path.join(tmp, 'book.gnucash')
sess = session('xml://' + path, 'SESSION_NEW_STORE')
book = sess.book
table = book.get_table()
usd = table.lookup('CURRENCY', 'USD')
for mnemonic in ('AMZN', 'MSFT'):
    table.insert(GncCommodity(book, mnemonic, 'NASDAQ', mnemonic, '', 10000))
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

buy = Transaction(book)
buy.BeginEdit()
buy.SetCurrency(usd)
for acct, value, amount in ((bank, (-218450, 100), (-218450, 100)),
                            (stock, (218450, 100), (100000, 10000))):
    split = Split(book)
    split.SetParent(buy)
    split.SetAccount(acct)
    split.SetValue(GncNumeric(*value))
    split.SetAmount(GncNumeric(*amount))
xaccTransSetDatePostedSecsNormalized(ptr(buy), local(2026, 2, 1, 12, 0, 0))
buy.CommitEdit()
sess.save()
book_ptr = ptr(book)
gnc_set_current_session(ptr(sess))
gnc_component_manager_init()

print('== stock split assistant, on AMZN holding 10 shares')
if gnc_stock_split_dialog is None or os.environ.get('SKIP_SPLIT'):
    print(f'  skipped: in this build {gnc_stock_split_dialog is not None},'
          f' SKIP_SPLIT={os.environ.get("SKIP_SPLIT")!r}')
else:
    before = toplevels()
    gnc_stock_split_dialog(None, ptr(stock))
    assistant = the_new_window(before)
    for _step in range(8):
        index, page = page_now(assistant)
        widgets = list(descendants(page))
        for date_edit in [w for w in widgets if type_name(w) == 'GNCDateEdit']:
            typed = type_date(date_edit, local(2026, 2, 12, 12, 0, 0))
            print(f'    typed {typed!r} into the date field;'
                  f' gnc_date_edit_get_date now {fmt(gnc_date_edit_get_date(date_edit))}')
        for w in widgets:
            if s(gtk_buildable_get_name(w)) == 'description_entry':
                gtk_entry_set_text(w, b'Probe split')
            if type_name(w) == 'GNCAmountEdit' and parent_name(w) == 'stock_details_table':
                row = c_int(-1)
                gtk_container_child_get(c_void_p(gtk_widget_get_parent(w)), c_void_p(w),
                                        b'top-attach', byref(row), c_void_p(None))
                value = {1: Numeric(10, 1), 5: Numeric(11000, 100)}.get(row.value)
                if value is not None:
                    gnc_amount_edit_set_amount(w, value)
                    print(f'    grid row {row.value}: {value.num}/{value.denom}')
        pump()
        if index == gtk_assistant_get_n_pages(assistant) - 1:
            labels(page)
            # the stock split glade wires gnc_stock_split_assistant_finish to "close"
            print('    Finish ("close")')
            g_signal_emit_by_name(c_void_p(assistant), b'close')
            pump()
            break
        gtk_assistant_next_page(assistant)
        pump()
    show_prices('prices after Apply', book_ptr)

print('== CSV price import assistant')
if gnc_file_csv_price_import is None:
    print('  gnc_file_csv_price_import is not in this build')
else:
    version = s(gnc_version()) if gnc_version else None
    print(f'  gnc_version {version}')
    csv_path = os.path.join(tmp, 'prices.csv')
    if version == '3.4':
        # 3.4's column types are None, Date, Amount, Commodity From, Currency To;
        # Commodity From takes a mnemonic and looks it up in every namespace
        rows = '2026-02-10,218.45,AMZN,USD\n2026-02-11,423.10,MSFT,USD\n'
        column_types = (PRICE_DATE, PRICE_AMOUNT, 3, 4)
    else:
        rows = '2026-02-10,218.45,AMZN,NASDAQ,USD\n2026-02-11,423.10,MSFT,NASDAQ,USD\n'
        column_types = (PRICE_DATE, PRICE_AMOUNT, PRICE_FROM_SYMBOL,
                        PRICE_FROM_NAMESPACE, PRICE_TO_CURRENCY)
    with open(csv_path, 'w') as f:
        f.write(rows)
    with open(csv_path) as f:
        print(f'  file: {f.read()!r}')
    before = toplevels()
    gnc_file_csv_price_import()
    assistant = the_new_window(before)
    index, page = page_now(assistant)
    gtk_assistant_next_page(assistant)
    pump()
    index, page = page_now(assistant)
    chooser = next((w for w in descendants(page) if type_name(w) == 'GtkFileChooserWidget'), None)
    if chooser is None:
        print(f'    no file chooser; widget types {sorted({type_name(w) for w in descendants(page)})}')
    else:
        gtk_file_chooser_set_filename(chooser, csv_path.encode())
        for _ in range(60):
            pump(1)
            chosen = gtk_file_chooser_get_filename(chooser)
            if chosen:
                print(f'    file chooser holds {string_at(chosen).decode()!r}')
                g_free(chosen)
                break
        g_signal_emit_by_name(c_void_p(chooser), b'file-activated')
        pump(5)
    index, page = page_now(assistant)

    def header_combos():
        combos = {}
        for view in [w for w in descendants(page) if type_name(w) == 'GtkTreeView']:
            for w in descendants(view):
                if type_name(w) == 'GtkComboBox':
                    combos[g_object_get_data(w, b'col-num') or 0] = w
        return combos

    def choose(combo, wanted):
        model = gtk_combo_box_get_model(combo)
        it = TreeIter()
        ok = gtk_tree_model_get_iter_first(model, byref(it))
        while ok:
            value = (c_char * 24)()
            gtk_tree_model_get_value(model, byref(it), 1, value)
            got = g_value_get_int(value)
            g_value_unset(value)
            if got == wanted:
                gtk_combo_box_set_active_iter(combo, byref(it))
                return True
            ok = gtk_tree_model_iter_next(model, byref(it))
        return False

    pump(5)
    print(f'    column header combos: {sorted(header_combos())}')
    for column, wanted in enumerate(column_types):
        combo = header_combos().get(column)
        print(f'    column {column} -> type {wanted}:'
              f' {choose(combo, wanted) if combo else "no combo"}')
        pump(3)
    complete = gtk_assistant_get_page_complete(assistant, page)
    print(f'    preview page complete: {complete}')
    labels(page)
    if not complete:
        # Apply on an incomplete preview opens a modal error dialog and waits for a click
        print('    not pressing Apply: the preview page is not complete')
    else:
        gtk_assistant_next_page(assistant)
        pump()
        index, page = page_now(assistant)
        print('    Apply')
        g_signal_emit_by_name(c_void_p(assistant), b'apply')
        pump()
        gtk_assistant_next_page(assistant)
        pump()
        index, page = page_now(assistant)
        labels(page)
    show_prices('prices after Apply', book_ptr)

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
print('  <price> blocks in the file:')
for block in re.findall(r'<price>.*?</price>', xml, re.S):
    ids = re.findall(r'<cmdty:id>(.*?)</cmdty:id>', block)
    stamp = re.search(r'<ts:date>(.*?)</ts:date>', block)
    source = re.search(r'<price:source>(.*?)</price:source>', block)
    print(f'    {"/".join(ids)} {stamp.group(1) if stamp else None!r}'
          f' {source.group(1) if source else None!r}')
sys.stdout.flush()
os._exit(0)
