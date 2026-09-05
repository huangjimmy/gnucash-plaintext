"""Probe: can `qof_book_get_string_option` reach a nested slot on 3.4?

Two claims in the tree cannot both hold. The write path only falls back to
`qof_instance_set_kvp` when the engine getter fails to read back what the
engine setter wrote, and the read path has a fallback of its own on the
premise that the getter "cannot resolve a nested path on 3.4 either". If the
getter *can* walk the path, the read fallback is unreachable; if it cannot,
the write fallback never runs.

So: write the nested slot with `qof_instance_set_kvp` and nothing else, then
ask the engine getter for it by path. And ask what a slashed name does to the
setter, since that decides whether there is any junk slot to clean up.

    ./scripts/test.sh debian10 tests/research/whether_the_option_getter_walks_a_path_probe.py
    ./scripts/test.sh latest   tests/research/whether_the_option_getter_walks_a_path_probe.py
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
PATH = b'options/Business/Company Name'


def _nested_write(lib, gobj, ptr, value):
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
    lib.qof_instance_set_kvp(ctypes.c_void_p(ptr), ctypes.byref(gval),
                             ctypes.c_uint(3),
                             b'options', b'Business', b'Company Name')
    gobj.g_value_unset(ctypes.byref(gval))
    _mark_instance_dirty(ptr)
    _mark_session_dirty(ptr)


def _keys_in(book_path):
    raw = Path(book_path).read_bytes()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    return re.findall(r'<slot:key>([^<]*)</slot:key>', raw.decode('utf-8', 'replace'))


def test_what_the_getter_can_reach(tmp_path, capsys):
    runner = CliRunner()
    lines = []

    # (a) nested slot written by KVP alone; asked of the engine getter by path.
    nested = tmp_path / 'nested.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(nested), ACCOUNTS]).exit_code == 0
    repo = GnuCashRepository(str(nested))
    repo.open()
    try:
        lib = load_gnc_engine()
        gobj = _load_gobject()
        lib.qof_book_get_string_option.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lib.qof_book_get_string_option.restype = ctypes.c_char_p
        ptr = int(repo.book.instance)
        _nested_write(lib, gobj, ptr, b'Acme')
        lines.append(('getter, by path, after a KVP nested write',
                      lib.qof_book_get_string_option(ctypes.c_void_p(ptr), PATH)))
        repo.save()
    finally:
        repo.close()
    lines.append(('slot keys in that saved book', _keys_in(nested)))

    # (b) what the engine setter does with a slashed name, on its own.
    slashed = tmp_path / 'slashed.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(slashed), ACCOUNTS]).exit_code == 0
    repo = GnuCashRepository(str(slashed))
    repo.open()
    try:
        lib = load_gnc_engine()
        lib.qof_book_set_string_option.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.qof_book_set_string_option.restype = None
        ptr = int(repo.book.instance)
        lib.qof_book_set_string_option(ctypes.c_void_p(ptr), PATH, b'Acme')
        _mark_instance_dirty(ptr)
        _mark_session_dirty(ptr)
        lines.append(('getter, by path, after the engine setter',
                      lib.qof_book_get_string_option(ctypes.c_void_p(ptr), PATH)))
        repo.save()
    finally:
        repo.close()
    lines.append(('slot keys in that saved book', _keys_in(slashed)))

    with capsys.disabled():
        print()
        for label, answer in lines:
            print(f'{label:<44} {answer!r}')
