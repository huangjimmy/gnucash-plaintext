"""Whether `qof_book_set_string_option` clears an option whose name holds a slash.

CLAUDE.md finding 21 measured that on GnuCash 3.4 this call stores nothing when
the name holds a slash, so a value is written through `qof_instance_set_kvp`
instead. This asks the other half: given the empty string, which is how a value
is cleared, does the call remove a nested option such as
`options/Business/Fancy Date Format/custom` that is already there?

The option is written first through `set_book_string_option`, which reaches the
slot on every build. Then the engine call alone is made with the empty value,
and the option is read back, before a save and after one.

Run on one build:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \\
        -v "$PWD":/workspace -w /workspace gnucash-dev:<tag> bash -c \\
        'python3 -m pip install -e ".[dev]" --user -q --break-system-packages \\
         || python3 -m pip install -e ".[dev]" --user -q; \\
         python3 tests/research/whether_clearing_a_book_option_with_a_slash_in_its_name_lands_on_3_4_probe.py'
"""

import ctypes
import tempfile
from pathlib import Path

from click.testing import CliRunner

# The suite's `_patch_session_save`: every save deletes the backup a save in
# the same second would collide with.
import tests.conftest  # noqa: F401
from cli.main import cli
from infrastructure.gnucash.kvp import (
    _load_gnc_engine,
    _mark_instance_dirty,
    _mark_session_dirty,
    get_book_string_option,
    set_book_string_option,
)
from repositories.gnucash_repository import GnuCashRepository, SessionMode

SLOT = 'Fancy Date Format/custom'

with tempfile.TemporaryDirectory() as directory:
    book = str(Path(directory) / 'book.gnucash')
    made = CliRunner().invoke(cli, ['import', '--new', book, 'tests/fixtures/q019_accounts.txt'])
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(book)
    repo.open(SessionMode.NORMAL)
    try:
        assert set_book_string_option(repo.book, 'Business', SLOT, '%d %B %Y')
        print('written:', repr(get_book_string_option(repo.book, 'Business', SLOT)))
        repo.save()
    finally:
        repo.close()

    repo = GnuCashRepository(book)
    repo.open(SessionMode.NORMAL)
    try:
        lib = _load_gnc_engine()
        lib.qof_book_set_string_option.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.qof_book_set_string_option.restype = None
        pointer = int(repo.book.instance)
        lib.qof_book_set_string_option(ctypes.c_void_p(pointer),
                                       f'options/Business/{SLOT}'.encode(), b'')
        _mark_instance_dirty(pointer)
        _mark_session_dirty(pointer)
        print('after the engine call with "":',
              repr(get_book_string_option(repo.book, 'Business', SLOT)))
        repo.save()
    finally:
        repo.close()

    repo = GnuCashRepository(book)
    repo.open(SessionMode.READ_ONLY)
    try:
        print('after a save and a reload:', repr(get_book_string_option(repo.book, 'Business', SLOT)))
    finally:
        repo.close()
