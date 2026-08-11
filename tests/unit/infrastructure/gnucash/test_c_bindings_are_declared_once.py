"""Every ctypes signature belongs in the shared engine, and nowhere else.

`argtypes` must be set for every C function that takes a pointer. Without it
ctypes passes a Python integer as a C `int`, truncating a 64-bit pointer to 32
bits on x86_64 and segfaulting inside the C function — so a *missing*
declaration is not a lint issue, it is a crash.

A declaration written beside its caller is one the next caller does without.
Worse, the handle is cached process-wide (`load_gnc_engine` is `lru_cache`d),
so a second declaration of the same symbol is not a local choice: it rewrites
what every earlier caller is holding. Two call sites declaring
`gnc_lot_add_split` as `None` and as `c_int` is one function whose return type
depends on which module was imported last.

So the rule is one place: `infrastructure/gnucash/engine.py`, where
`_setup_lib_restypes` declares them and `verify_ctypes_functions` checks at
load that the build actually has them.

This test is a ratchet. `KNOWN` lists what has not been moved yet, exactly, and
the test fails both ways: a declaration that is not listed is new debt and is
refused, and a listed one that has gone must be struck off. It cannot grow
quietly and it cannot be stale.

Both spellings count. `lib.xaccSplitGetAmount.restype = …` names its symbol in
the attribute chain; the loop form — `f = getattr(lib, name); f.restype = …` —
names only the local, so the symbols are read out of the list the loop
iterates. Recorded by the local instead, one `'f'` entry exempted a whole loop:
two files were covered by one such entry each, standing for 14 and 24 symbols
between them.
"""

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]

# The one place a signature may be declared.
SHARED = 'infrastructure/gnucash/engine.py'

SEARCHED = ['cli', 'services', 'use_cases', 'infrastructure', 'repositories']

# Declarations that predate the rule, by file and by the handle they are set on
# (`lib.xaccSplitGetAmount`, or `ctypes.CDLL` for a handle loaded outside the
# shared loader — which skips its RTLD_GLOBAL promotion and on Ubuntu can bind
# a different copy of the library than the one holding the book).
#
# `f` is the loop form: `f = getattr(lib, name); f.restype = ...`.
#
# Each entry is a line of work, tracked in docs/issues/T-009. Moving one is
# mechanical: add the signature to `_setup_lib_restypes`, add the name to
# `verify_ctypes_functions`, delete the local block, and strike the entry here.
KNOWN = {
    'infrastructure/gnucash/kvp.py': {
        # A second engine loader with its own RTLD_GLOBAL promotion, plus a
        # GObject handle the shared loader knows nothing about.
        'ctypes.CDLL',
        'gobj.g_value_get_string',
        'gobj.g_value_init',
        'gobj.g_value_set_string',
        'gobj.g_value_unset',
        'lib.qof_book_get_string_option',
        'lib.qof_book_set_string_option',
        'lib.qof_instance_get_kvp',
        'lib.qof_instance_set_dirty',
        'lib.qof_instance_set_kvp',
    },
    'services/gnucash_importer.py': {
        # GUID plumbing, declared in four places on a bare `CDLL(None)`.
        'ctypes.CDLL',
        'lib.guid_to_string_buff',
        'lib.qof_instance_get_guid',
        'lib.qof_instance_set_guid',
        'lib.string_to_guid',
        'lib.xaccAccountLookup',
    },
    'services/transaction_matcher.py': {
        'lib.gncOwnerGetID',
        'lib.gncOwnerGetOwnerFromTxn',
        'lib.gncOwnerGetType',
    },
    'use_cases/account_balance.py': {
        'lib.gnc_price_get_value',
    },
    'use_cases/export_business_objects.py': {
        'lib.guid_to_string_buff',
        'lib.qof_instance_get_guid',
    },
    'use_cases/export_transactions.py': {
        '_lib.gncInvoiceGetInvoiceFromLot',
        '_lib.gncOwnerGetGUID',
        '_lib.gncOwnerGetID',
        '_lib.gncOwnerGetOwnerFromLot',
        '_lib.gncOwnerGetOwnerFromTxn',
        '_lib.gncOwnerGetType',
        '_lib.guid_to_string_buff',
        '_lib.xaccSplitGetLot',
        '_lib.xaccTransGetTxnType',
    },
    # Both of these declare in the loop form, so until this test read the names
    # out of the list they iterate, each was one `'f'` entry — a blanket
    # exemption covering 14 and 24 symbols respectively, under which a new
    # conflicting declaration would have passed silently.
    'use_cases/unapply_payment.py': {
        'gnc_commodity_get_mnemonic', 'gnc_lot_get_balance',
        'gnc_lot_get_split_list', 'gnc_lot_remove_split', 'guid_to_string_buff',
        'qof_instance_get_guid', 'xaccAccountGetType', 'xaccSplitGetAccount',
        'xaccSplitGetAmount', 'xaccSplitGetParent', 'xaccSplitSetAccount',
        'xaccTransBeginEdit', 'xaccTransCommitEdit', 'xaccTransGetCurrency',
    },
    'use_cases/unpost_business_objects.py': {
        'gncInvoiceGetInvoiceFromLot', 'gncOwnerGetID', 'gncOwnerGetName',
        'gncOwnerGetOwnerFromTxn', 'gncOwnerGetType', 'gnc_account_get_parent',
        'gnc_commodity_get_fraction', 'gnc_commodity_get_mnemonic',
        'gnc_lot_get_split_list', 'guid_to_string_buff',
        'qof_instance_get_guid', 'xaccAccountGetName', 'xaccAccountGetType',
        'xaccSplitGetAccount', 'xaccSplitGetAmount', 'xaccSplitGetLot',
        'xaccSplitGetMemo', 'xaccSplitGetParent', 'xaccTransCountSplits',
        'xaccTransGetCurrency', 'xaccTransGetDate', 'xaccTransGetDescription',
        'xaccTransGetSplit', 'xaccTransGetTxnType',
    },
}


def _dotted(node):
    """`lib.xaccSplitGetAmount` for the attribute chain, `f` for a bare name.

    Written out rather than taken from `ast.unparse`, which arrived in Python
    3.9 — Ubuntu 20.04 ships 3.8, and it is the oldest version this project
    supports.
    """
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    parts.append(node.id if isinstance(node, ast.Name) else '<expression>')
    return '.'.join(reversed(parts))


def _symbols_declared_in_a_loop(tree):
    """The C function names a `for name, ... in [...]` declaration loop sets.

    The loop form assigns to a local — `f = getattr(lib, name); f.restype = …` —
    so the attribute chain says `f` and nothing about which symbol was declared.
    Recorded that way, one `'f'` entry exempts a whole loop: a new conflicting
    declaration added to it passes silently, and a removed one keeps the entry
    alive. Most of the remaining debt lives in that form, so the names are read
    out of the list the loop iterates instead.
    """
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.iter, ast.List):
            continue
        for element in node.iter.elts:
            first = element.elts[0] if isinstance(element, ast.Tuple) else element
            # `ast.Constant` only: it is what a string literal parses to from
            # Python 3.8, and `ast.Str` — the pre-3.8 spelling kept as a
            # deprecated alias — was removed in 3.12, which Arch ships.
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                names.add(first.value)
    return names


def _declarations_outside_the_shared_engine():
    """{path: {symbol or handle, ...}} for every ctypes declaration made here.

    Read from the syntax tree rather than by matching text: a signature split
    across two lines, or written with a different amount of whitespace, is the
    same declaration and has to count as one.
    """
    found = {}
    for root in SEARCHED:
        for path in sorted((REPO_ROOT / root).rglob('*.py')):
            relative = path.relative_to(REPO_ROOT).as_posix()
            if relative == SHARED:
                continue
            handles = set()
            tree = ast.parse(path.read_text())
            declares_in_a_loop = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (isinstance(target, ast.Attribute)
                                and target.attr in ('argtypes', 'restype')):
                            dotted = _dotted(target.value)
                            if '.' in dotted:
                                handles.add(dotted)
                            else:
                                declares_in_a_loop = True
                # Both spellings: `ctypes.CDLL(...)` is how the tree writes it,
                # and a bare `CDLL(...)` off a `from ctypes import CDLL` loads
                # the same library while reading as an ordinary call.
                if isinstance(node, ast.Call) and (
                        (isinstance(node.func, ast.Attribute)
                         and node.func.attr == 'CDLL')
                        or (isinstance(node.func, ast.Name)
                            and node.func.id == 'CDLL')):
                    handles.add('ctypes.CDLL')
            if declares_in_a_loop:
                handles |= _symbols_declared_in_a_loop(tree)
            if handles:
                found[relative] = handles
    return found


def test_no_new_c_binding_is_declared_outside_the_shared_engine():
    """Nothing may declare a signature of its own that is not already known."""
    added = {}
    for path, handles in _declarations_outside_the_shared_engine().items():
        new = handles - KNOWN.get(path, set())
        if new:
            added[path] = sorted(new)
    assert not added, (
        'ctypes signatures declared outside ' + SHARED + ':\n'
        + '\n'.join(f'  {path}: {", ".join(names)}'
                    for path, names in sorted(added.items()))
        + '\n\nDeclare them in _setup_lib_restypes() and name them in '
          'verify_ctypes_functions() instead. The handle is cached '
          'process-wide, so a second declaration of a symbol rewrites what '
          'every other caller is holding.')


def test_the_known_list_has_nothing_stale_on_it():
    """A declaration that has been moved must come off the list.

    Without this the list becomes a place names go to be forgotten, and the
    next reader cannot tell which entries are real.
    """
    live = _declarations_outside_the_shared_engine()
    stale = {}
    for path, handles in KNOWN.items():
        gone = handles - live.get(path, set())
        if gone:
            stale[path] = sorted(gone)
    assert not stale, (
        'KNOWN lists declarations that are no longer there — strike them '
        'off:\n'
        + '\n'.join(f'  {path}: {", ".join(names)}'
                    for path, names in sorted(stale.items())))


def test_only_one_place_puts_a_split_in_an_existing_lot():
    """`xaccSplitSetLot` is called through `_attach_split_to_lot` and nowhere else.

    It puts the split in the lot without adding it to that lot's split list,
    so every reader of "what does this lot hold" is short by one split until
    the book is written and read back. `_attach_split_to_lot` leaves a note
    saying which lots that has happened to, and readers walk the whole account
    for those and take the cheap answer for the rest — a receivable carries
    the history of the business, so paying that cost everywhere is not free.

    A call that reaches past the helper leaves no note, and the readers go on
    believing a short list. That is not a failure anything would show: the
    figures still balance, the document just reads as owing more than it does.

    Searched over the whole tree, not the importer alone, and matching both
    spellings — `gc.xaccSplitSetLot(...)` and a bare `xaccSplitSetLot(...)` off
    a `from gnucash.gnucash_core_c import …`. A note that only one module is
    obliged to leave is not a rule, and the same reader in another module would
    be the one believing the short list.
    """
    calls = []
    for root in SEARCHED:
        for path in sorted((REPO_ROOT / root).rglob('*.py')):
            relative = path.relative_to(REPO_ROOT).as_posix()
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call):
                    continue
                named = ((isinstance(node.func, ast.Attribute)
                          and node.func.attr == 'xaccSplitSetLot')
                         or (isinstance(node.func, ast.Name)
                             and node.func.id == 'xaccSplitSetLot'))
                if named:
                    calls.append(f'{relative}:{node.lineno}')
    assert calls == ['services/gnucash_importer.py:'
                     + str(_attach_split_to_lot_line())], (
        f'xaccSplitSetLot is called at {calls} — it belongs in '
        f'_attach_split_to_lot alone, which records the lot so readers know '
        f'its split list is short.')


def _attach_split_to_lot_line():
    """The line `_attach_split_to_lot` makes its one call on."""
    tree = ast.parse((REPO_ROOT / 'services' / 'gnucash_importer.py').read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '_attach_split_to_lot':
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == 'xaccSplitSetLot'):
                    return inner.lineno
    raise AssertionError('_attach_split_to_lot does not call xaccSplitSetLot')


def test_the_ratchet_sees_a_bare_cdll_import():
    """`from ctypes import CDLL` is a library load too.

    The check matches how the tree writes it — `ctypes.CDLL(...)` — and a bare
    name would read as an ordinary call. Nothing does this today; stated so
    that adding it is a decision rather than an oversight.
    """
    tree = ast.parse('from ctypes import CDLL\nlib = CDLL(None)\n')
    loads = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and ((isinstance(node.func, ast.Attribute)
                   and node.func.attr == 'CDLL')
                  or (isinstance(node.func, ast.Name) and node.func.id == 'CDLL'))]
    assert len(loads) == 1


@pytest.mark.parametrize('name', [
    'xaccSplitSetAccount', 'gnc_lot_new', 'gnc_lot_add_split',
    'xaccAccountInsertLot', 'xaccAccountGetLotList', 'gnc_lot_get_balance',
    'gnc_lot_is_closed', 'gnc_lot_get_earliest_split',
    'gncInvoiceGetInvoiceFromLot', 'xaccSplitGetParent', 'xaccSplitGetAmount',
    'xaccTransGetDate', 'gncOwnerInitCustomer', 'gncOwnerInitVendor',
    'gncOwnerAttachToLot',
])
def test_the_shared_engine_declares_what_lot_handling_calls(name):
    """The signatures the credit and overpayment paths need are set at load.

    Declared nowhere, a pointer argument is passed as a 32-bit int and the
    call segfaults; declared late, the first caller to reach the symbol gets
    whatever the last writer left. Both are answered by setting them once,
    when the library is loaded.
    """
    from infrastructure.gnucash.engine import load_gnc_engine

    lib = load_gnc_engine()
    function = getattr(lib, name)
    assert function.argtypes, f'{name} has no argtypes on the shared handle'
    assert all(argument is not None for argument in function.argtypes), name
