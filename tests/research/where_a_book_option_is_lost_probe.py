"""Probe: a book string option, followed from the write to the reloaded file.

`set_book_string_option` calls `qof_book_set_string_option` through ctypes, and
on GnuCash 3.4 (Debian 10) every test that reads one back gets `None`. The
symptom says only that it is gone by the end; this says which step loses it.

Four readings, in order:

    set returned      what the wrapper reported
    same session      the value read straight back, before any save
    after reload      the value read from the file
    in the XML        whether the key and the value are in the saved bytes

    ./scripts/test.sh debian10 tests/research/where_a_book_option_is_lost_probe.py
    ./scripts/test.sh latest   tests/research/where_a_book_option_is_lost_probe.py
"""

import gzip
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import (
    get_book_string_option,
    set_book_string_option,
)
from repositories.gnucash_repository import GnuCashRepository

ACCOUNTS = str(Path('tests/fixtures/q019_accounts.txt'))


def test_where_the_option_goes(tmp_path, capsys):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        wrote = set_book_string_option(repo.book, 'Business',
                                       'Company Name', 'Acme')
        same_session = get_book_string_option(repo.book, 'Business',
                                              'Company Name')
        repo.save()
    finally:
        repo.close()

    again = GnuCashRepository(str(book))
    again.open()
    try:
        after_reload = get_book_string_option(again.book, 'Business',
                                              'Company Name')
    finally:
        again.close()

    raw = book.read_bytes()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)

    with capsys.disabled():
        import gnucash
        print(f'\ngnucash bindings  {getattr(gnucash, "__file__", "?")}')
        print(f'set returned      {wrote}')
        print(f'same session      {same_session!r}')
        print(f'after reload      {after_reload!r}')
        print(f'in the XML: key   {b"Company Name" in raw}')
        print(f'in the XML: value {b"Acme" in raw}')
