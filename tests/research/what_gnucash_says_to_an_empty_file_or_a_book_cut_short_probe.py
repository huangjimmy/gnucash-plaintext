"""What GnuCash says when asked to open an empty file, or a book cut short.

Three files, each opened by `GnuCashRepository` for reading and for writing, in a
child process of its own, because a book GnuCash cannot parse can end the process
that loads it (CLAUDE.md finding 12):

  empty       a file of no bytes
  cut-gzip    a book as GnuCash writes it, gzipped, with the second half removed
  cut-xml     the same book uncompressed, cut off in the middle of its XML

Run on one build:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \\
        -v "$PWD":/workspace -w /workspace gnucash-dev:<tag> bash -c \\
        'python3 -m pip install -e ".[dev]" --user -q --break-system-packages \\
         || python3 -m pip install -e ".[dev]" --user -q; \\
         python3 tests/research/what_gnucash_says_to_an_empty_file_or_a_book_cut_short_probe.py'

Each line gives the file, the mode, how the child ended (a negative number is
the signal that killed it) and what it printed last.
"""

import gzip
import subprocess
import sys
import tempfile
from pathlib import Path

CHILD = r'''
import sys
from repositories.gnucash_repository import BookUnavailableError, GnuCashRepository, SessionMode
repo = GnuCashRepository(sys.argv[1])
try:
    repo.open(SessionMode.READ_ONLY if sys.argv[2] == 'read' else SessionMode.NORMAL)
    print('opened, holding', len(repo.book.get_root_account().get_descendants()), 'accounts')
    repo.close()
except BookUnavailableError as e:
    print('refused:', e.__cause__ if e.__cause__ is not None else e)
'''

MAKE = ('import sys; from click.testing import CliRunner; from cli.main import cli; '
        'r = CliRunner().invoke(cli, ["import", "--new", sys.argv[1], '
        '"tests/fixtures/fx_buy_and_borrow_usd.txt"]); sys.exit(r.exit_code)')

with tempfile.TemporaryDirectory() as directory:
    directory = Path(directory)
    book = directory / 'book.gnucash'
    subprocess.run([sys.executable, '-c', MAKE, str(book)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    written = book.read_bytes()
    xml = gzip.decompress(written) if written[:2] == b'\x1f\x8b' else written

    files = {
        'empty': b'',
        'cut-gzip': written[:len(written) // 2],
        'cut-xml': xml[:len(xml) // 2],
    }
    for name, content in files.items():
        for mode in ('read', 'write'):
            path = directory / f'{name}-{mode}.gnucash'
            path.write_bytes(content)
            done = subprocess.run([sys.executable, '-c', CHILD, str(path), mode],
                                  capture_output=True, text=True)
            said = [line for line in done.stdout.splitlines()
                    if line.startswith(('opened', 'refused'))]
            print(f'{name:9} {mode:5} exit {done.returncode:4}  {said[-1] if said else "(nothing)"}')
