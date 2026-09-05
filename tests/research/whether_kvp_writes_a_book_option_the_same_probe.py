"""Probe: writing a book option through `qof_instance_set_kvp` instead.

`qof_book_set_string_option` reads its argument as a path from GnuCash 4 on and
as a bare slot name on 3.4, so the one call cannot serve both
(`what_path_a_book_option_wants_probe.py`). `qof_instance_set_kvp` is the
primitive every other slot in this tool is written with, it is variadic over
the path segments, and it is present on 3.4.

The question is not whether it works but whether it writes *the same thing* —
a swap that stored the option somewhere else would leave GnuCash's own File →
Properties dialog reading nothing. So both routes are written into two books
built the same way, and the slot subtrees are compared as text.

    ./scripts/test.sh debian10 tests/research/whether_kvp_writes_a_book_option_the_same_probe.py
    ./scripts/test.sh latest   tests/research/whether_kvp_writes_a_book_option_the_same_probe.py
"""

import ctypes
import gzip
import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.kvp import (
    _G_TYPE_STRING,
    _GValue,
    _load_gobject,
    _mark_instance_dirty,
    _mark_session_dirty,
)
from repositories.gnucash_repository import GnuCashRepository

ACCOUNTS = str(Path('tests/fixtures/q019_accounts.txt'))


def _book(runner, tmp_path, name):
    book = tmp_path / name
    made = runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output
    return book


def _by_the_option_call(book_ptr, value):
    lib = load_gnc_engine()
    lib.qof_book_set_string_option.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
    ]
    lib.qof_book_set_string_option.restype = None
    lib.qof_book_set_string_option(
        ctypes.c_void_p(book_ptr), b'options/Business/Company Name', value)


def _by_the_kvp_call(book_ptr, value):
    gobj = _load_gobject()
    lib = load_gnc_engine()
    gobj.g_value_init.argtypes = [ctypes.POINTER(_GValue), ctypes.c_ulong]
    gobj.g_value_init.restype = ctypes.POINTER(_GValue)
    gobj.g_value_set_string.argtypes = [ctypes.POINTER(_GValue), ctypes.c_char_p]
    gobj.g_value_set_string.restype = None
    gobj.g_value_unset.argtypes = [ctypes.POINTER(_GValue)]
    gobj.g_value_unset.restype = None
    lib.qof_instance_set_kvp.restype = None

    gval = _GValue()
    gobj.g_value_init(ctypes.byref(gval), _G_TYPE_STRING)
    gobj.g_value_set_string(ctypes.byref(gval), value)
    lib.qof_instance_set_kvp(
        ctypes.c_void_p(book_ptr), ctypes.byref(gval), ctypes.c_uint(3),
        b'options', b'Business', b'Company Name')
    gobj.g_value_unset(ctypes.byref(gval))
    # Finding 11: a slot written on an object the book already held reaches
    # disk only if something marks it dirty. The book is such an object, and
    # `write_book_string_option` marks it for the same reason.
    _mark_instance_dirty(book_ptr)
    _mark_session_dirty(book_ptr)


def _slots_of(book_path):
    raw = Path(book_path).read_bytes()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    text = raw.decode('utf-8', 'replace')
    found = re.search(r'<gnc:book.*?>(.*?)<gnc:count-data', text, re.S)
    body = found.group(1) if found else ''
    slots = re.search(r'<book:slots>(.*?)</book:slots>', body, re.S)
    return re.sub(r'\s+', ' ', slots.group(1)).strip() if slots else '(no slots)'


def _write_and_read(book, writer, value=b'Acme'):
    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        writer(int(repo.book.instance), value)
        repo.save()
    finally:
        repo.close()
    from infrastructure.gnucash.kvp import get_book_string_option
    again = GnuCashRepository(str(book))
    again.open()
    try:
        return get_book_string_option(again.book, 'Business', 'Company Name'), _slots_of(book)
    finally:
        again.close()


def test_the_two_routes_write_the_same_slot(tmp_path, capsys):
    runner = CliRunner()
    option_read, option_slots = _write_and_read(
        _book(runner, tmp_path, 'by_option.gnucash'), _by_the_option_call)
    kvp_read, kvp_slots = _write_and_read(
        _book(runner, tmp_path, 'by_kvp.gnucash'), _by_the_kvp_call)

    with capsys.disabled():
        print()
        print(f'qof_book_set_string_option  reads back {option_read!r}')
        print(f'qof_instance_set_kvp        reads back {kvp_read!r}')
        print(f'same slot subtree:          {option_slots == kvp_slots}')
        print()
        print(f'  by option call: {option_slots[:400]}')
        print(f'  by kvp call:    {kvp_slots[:400]}')
