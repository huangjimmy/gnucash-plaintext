"""Probe: which argument GnuCash's `qof_book_set_string_option` wants.

Both GnuCash 3.4 and 5.10 export the symbol, and the same call that lands on
5.10 stores nothing on 3.4 — not even in the same session
(`where_a_book_option_is_lost_probe.py`). So the name is right and something
about the argument is not.

This writes one option per spelling, into a book of its own each time, and
reports what the saved file holds. What is being looked for is the spelling
whose key and value both reach the XML on the build under test.

    ./scripts/test.sh debian10 tests/research/what_path_a_book_option_wants_probe.py
    ./scripts/test.sh latest   tests/research/what_path_a_book_option_wants_probe.py
"""

import ctypes
import gzip
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from repositories.gnucash_repository import GnuCashRepository

ACCOUNTS = str(Path('tests/fixtures/q019_accounts.txt'))

SPELLINGS = [
    'options/Business/Company Name',
    'Business/Company Name',
    'Company Name',
    'options/Business/Company Name/',
]


def _write_with(book_path, opt_path):
    repo = GnuCashRepository(str(book_path))
    repo.open()
    try:
        lib = load_gnc_engine()
        lib.qof_book_set_string_option.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
        ]
        lib.qof_book_set_string_option.restype = None
        lib.qof_book_set_string_option(
            ctypes.c_void_p(int(repo.book.instance)),
            opt_path.encode(),
            b'Acme',
        )
        repo.save()
    finally:
        repo.close()

    raw = Path(book_path).read_bytes()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    return raw


def test_which_spelling_lands(tmp_path, capsys):
    runner = CliRunner()
    results = []
    for n, spelling in enumerate(SPELLINGS):
        book = tmp_path / f'book{n}.gnucash'
        made = runner.invoke(cli, ['import', '--new', str(book), ACCOUNTS])
        assert made.exit_code == 0, made.output
        try:
            raw = _write_with(book, spelling)
            results.append((spelling, b'Acme' in raw,
                            raw.count(b'<gnc:count-data') and b'Business' in raw))
        except Exception as e:  # a spelling the engine refuses outright
            results.append((spelling, f'raised {type(e).__name__}', ''))

    with capsys.disabled():
        print()
        print(f'{"opt_name argument":<36} {"value in XML":<14} section in XML')
        for spelling, landed, section in results:
            print(f'{spelling:<36} {str(landed):<14} {section}')
