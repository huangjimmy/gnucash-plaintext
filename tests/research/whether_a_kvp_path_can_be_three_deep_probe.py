"""Probe: does `qof_instance_set_kvp` take more than one path segment here?

The tool writes every slot with this call and always with one segment. A book
option lives three deep — `options` → section → name — and an attempt to write
one that way stored nothing on either version, which is either the call being
wrong or the depth being unsupported.

This separates the two. The same plumbing writes a one-segment slot and a
three-segment slot on the same book, and both are read straight back with the
matching getter before anything is saved.

    ./scripts/test.sh debian10 tests/research/whether_a_kvp_path_can_be_three_deep_probe.py
    ./scripts/test.sh latest   tests/research/whether_a_kvp_path_can_be_three_deep_probe.py
"""

import ctypes
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.kvp import _G_TYPE_STRING, _GValue, _load_gobject
from repositories.gnucash_repository import GnuCashRepository

ACCOUNTS = str(Path('tests/fixtures/q019_accounts.txt'))


def _gobject():
    gobj = _load_gobject()
    gobj.g_value_init.argtypes = [ctypes.POINTER(_GValue), ctypes.c_ulong]
    gobj.g_value_init.restype = ctypes.POINTER(_GValue)
    gobj.g_value_set_string.argtypes = [ctypes.POINTER(_GValue), ctypes.c_char_p]
    gobj.g_value_set_string.restype = None
    gobj.g_value_get_string.argtypes = [ctypes.POINTER(_GValue)]
    gobj.g_value_get_string.restype = ctypes.c_char_p
    gobj.g_value_unset.argtypes = [ctypes.POINTER(_GValue)]
    gobj.g_value_unset.restype = None
    return gobj


def _set(lib, gobj, ptr, value, *segments):
    lib.qof_instance_set_kvp.restype = None
    gval = _GValue()
    gobj.g_value_init(ctypes.byref(gval), _G_TYPE_STRING)
    gobj.g_value_set_string(ctypes.byref(gval), value)
    lib.qof_instance_set_kvp(ctypes.c_void_p(ptr), ctypes.byref(gval),
                             ctypes.c_uint(len(segments)), *segments)
    gobj.g_value_unset(ctypes.byref(gval))


def _get(lib, gobj, ptr, *segments):
    lib.qof_instance_get_kvp.restype = None
    gval = _GValue()
    lib.qof_instance_get_kvp(ctypes.c_void_p(ptr), ctypes.byref(gval),
                             ctypes.c_uint(len(segments)), *segments)
    try:
        return gobj.g_value_get_string(ctypes.byref(gval))
    except Exception as e:
        return f'raised {type(e).__name__}: {e}'


def test_how_deep_a_path_may_be(tmp_path, capsys):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        lib = load_gnc_engine()
        gobj = _gobject()
        ptr = int(repo.book.instance)

        _set(lib, gobj, ptr, b'one-deep', b'ProbeFlat')
        one = _get(lib, gobj, ptr, b'ProbeFlat')

        _set(lib, gobj, ptr, b'three-deep', b'options', b'Business', b'Company Name')
        three = _get(lib, gobj, ptr, b'options', b'Business', b'Company Name')
    finally:
        repo.close()

    with capsys.disabled():
        print()
        print(f'one segment  -> {one!r}')
        print(f'three segments -> {three!r}')
