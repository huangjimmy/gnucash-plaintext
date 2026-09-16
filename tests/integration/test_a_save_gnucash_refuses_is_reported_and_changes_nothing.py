"""A save GnuCash refuses is reported, and the book is left as it was.

GnuCash keeps a backup of a book it saves, under the second the save happens
in: `<book>.<YYYYMMDDHHMMSS>.gnucash`. When a file of that name is already
there, the save stops with `ERR_FILEIO_BACKUP_ERROR`. `cli/_saving.py` read that
error as a collision the book itself survived, and said nothing.

The commands run in a process of their own: `tests/conftest.py` deletes the
backup file a save is about to collide with, which is what keeps the rest of
the suite from ever meeting this.
"""

import subprocess
import sys
import time
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

NOTE = 'Thank you for your business'


def _cli(*args):
    return subprocess.run([sys.executable, '-c', 'from cli.main import cli; cli()', *args],
                          capture_output=True, text=True)


def test_a_command_whose_save_gnucash_refuses_says_so_and_changes_nothing(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), 'tests/fixtures/closing_book.txt')
    assert made.exit_code == 0, made.output
    # Every backup name a save could want for the next minute is already taken.
    now = time.time()
    for second in range(60):
        stamp = time.strftime('%Y%m%d%H%M%S', time.localtime(now + second))
        Path(f'{book}.{stamp}.gnucash').write_text('taken', encoding='utf-8')

    result = _cli('set-invoice-style', str(book), '--note', NOTE)

    said = result.stdout + result.stderr
    assert result.returncode != 0, said
    assert 'Failed to save' in said and 'ERR_FILEIO_BACKUP_ERROR' in said, said
    shown = _cli('set-invoice-style', str(book), '--show')
    assert shown.returncode == 0, shown.stdout + shown.stderr
    assert NOTE not in shown.stdout, shown.stdout
