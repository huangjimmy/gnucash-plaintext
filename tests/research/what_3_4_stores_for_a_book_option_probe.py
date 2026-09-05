"""Probe: GnuCash 3.4's own layout for a book option.

`qof_book_set_string_option` takes a path from GnuCash 4 on and a bare slot
name on 3.4 (`what_path_a_book_option_wants_probe.py`). Before anything is
written against that, this asks what 3.4 does with the bare name it accepts:
where the slot lands, whether the engine's own getter finds it again, and
whether it survives a save.

`qof_book_get_string_option` is asked with the same spelling that was written,
which is the pairing GnuCash itself uses.

    ./scripts/test.sh debian10 tests/research/what_3_4_stores_for_a_book_option_probe.py
    ./scripts/test.sh latest   tests/research/what_3_4_stores_for_a_book_option_probe.py
"""

import ctypes
import gzip
import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from repositories.gnucash_repository import GnuCashRepository

ACCOUNTS = str(Path('tests/fixtures/q019_accounts.txt'))


def _declare(lib):
    lib.qof_book_set_string_option.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    lib.qof_book_set_string_option.restype = None
    lib.qof_book_get_string_option.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.qof_book_get_string_option.restype = ctypes.c_char_p


def _all_slots(book_path):
    raw = Path(book_path).read_bytes()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    text = raw.decode('utf-8', 'replace')
    keys = re.findall(r'<slot:key>([^<]*)</slot:key>', text)
    acme = re.findall(r'<slot:value type="string">(Acme[^<]*)</slot:value>', text)
    return keys, acme


def test_what_3_4_does_with_a_bare_option_name(tmp_path, capsys):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        lib = load_gnc_engine()
        _declare(lib)
        ptr = ctypes.c_void_p(int(repo.book.instance))
        lib.qof_book_set_string_option(ptr, b'Company Name', b'Acme')
        engine_read_same_session = lib.qof_book_get_string_option(ptr, b'Company Name')
        repo.save()
    finally:
        repo.close()

    again = GnuCashRepository(str(book))
    again.open()
    try:
        lib = load_gnc_engine()
        _declare(lib)
        ptr = ctypes.c_void_p(int(again.book.instance))
        engine_read_after_reload = lib.qof_book_get_string_option(ptr, b'Company Name')
    finally:
        again.close()

    keys, acme = _all_slots(book)

    with capsys.disabled():
        print()
        print(f'engine getter, same session  {engine_read_same_session!r}')
        print(f'engine getter, after reload  {engine_read_after_reload!r}')
        print(f'slot keys in the saved file  {sorted(set(keys))}')
        print(f'string values starting Acme  {acme}')
