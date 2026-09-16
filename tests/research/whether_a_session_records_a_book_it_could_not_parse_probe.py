"""Whether a session that opened a book cut short records that it could not parse it.

`what_gnucash_says_to_an_empty_file_or_a_book_cut_short_probe.py` measures that
GnuCash 3.4 refuses such a book with `ERR_FILEIO_PARSE_ERROR` while later builds
open it as a book holding nothing. This asks the session opened on a later build
what error it holds, through `Session.get_error()` and `qof_session_get_error`,
and what `import` does with such a book: its exit, and what the file holds after.

Run on one build:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \\
        -v "$PWD":/workspace -w /workspace gnucash-dev:<tag> bash -c \\
        'python3 -m pip install -e ".[dev]" --user -q --break-system-packages \\
         || python3 -m pip install -e ".[dev]" --user -q; \\
         python3 tests/research/whether_a_session_records_a_book_it_could_not_parse_probe.py'
"""

import gzip
import subprocess
import sys
import tempfile
from pathlib import Path

ASK = r'''
import sys
from gnucash import Session
try:
    from gnucash import SessionOpenMode
    session = Session('xml://' + sys.argv[1], SessionOpenMode.SESSION_READ_ONLY)
except ImportError:
    session = Session('xml://' + sys.argv[1], ignore_lock=True)
except Exception as e:
    print('raised:', e)
    sys.exit(0)
print('get_error:', session.get_error())
print('accounts:', len(session.book.get_root_account().get_descendants()))
session.destroy()
'''

MAKE = ('import sys; from click.testing import CliRunner; from cli.main import cli; '
        'r = CliRunner().invoke(cli, ["import", "--new", sys.argv[1], '
        '"tests/fixtures/fx_buy_and_borrow_usd.txt"]); sys.exit(r.exit_code)')

IMPORT = ('from cli.main import cli; import sys; sys.argv[0] = "gnucash-plaintext"; cli()')

HOLDS = ('import sys; from repositories.gnucash_repository import GnuCashRepository, SessionMode; '
         'r = GnuCashRepository(sys.argv[1]); r.open(SessionMode.READ_ONLY); '
         'print("holds", len(r.book.get_root_account().get_descendants()), "accounts"); r.close()')

with tempfile.TemporaryDirectory() as directory:
    directory = Path(directory)
    book = directory / 'book.gnucash'
    subprocess.run([sys.executable, '-c', MAKE, str(book)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    written = book.read_bytes()
    xml = gzip.decompress(written) if written[:2] == b'\x1f\x8b' else written
    cut = directory / 'cut.gnucash'
    cut.write_bytes(xml[:len(xml) // 2])

    asked = subprocess.run([sys.executable, '-c', ASK, str(cut)], capture_output=True, text=True)
    print('\n'.join(line for line in asked.stdout.splitlines()
                    if line.startswith(('raised', 'get_error', 'accounts'))))

    ledger = directory / 'more.txt'
    ledger.write_text('2026-01-01 open Other\n\ttype: Bank\n'
                      '\tcommodity.namespace: "CURRENCY"\n\tcommodity.mnemonic: "CAD"\n')
    before = cut.stat().st_size
    imported = subprocess.run([sys.executable, '-c', IMPORT, 'import', str(cut), str(ledger)],
                              capture_output=True, text=True)
    print('import exit', imported.returncode)
    print('size before', before, 'after', cut.stat().st_size)
    held = subprocess.run([sys.executable, '-c', HOLDS, str(cut)], capture_output=True, text=True)
    print(held.stdout.strip() or held.stderr.strip()[-300:])
    print('beside it:', sorted(p.name for p in directory.iterdir()))
