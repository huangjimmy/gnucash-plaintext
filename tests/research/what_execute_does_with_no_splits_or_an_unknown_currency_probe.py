"""What `ImportTransactionsUseCase.execute` does with no splits, or with a currency GnuCash does not know.

Each case runs in a child process of its own, because a transaction left with no
splits is destroyed by GnuCash when its edit is committed, and reading it
afterwards has ended the process that did (a segfault in `get_signature`).

Run on one build:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \\
        -v "$PWD":/workspace -w /workspace gnucash-dev:<tag> bash -c \\
        'python3 -m pip install -e ".[dev]" --user -q --break-system-packages \\
         || python3 -m pip install -e ".[dev]" --user -q; \\
         python3 tests/research/what_execute_does_with_no_splits_or_an_unknown_currency_probe.py'
"""

import subprocess
import sys
import tempfile
from pathlib import Path

CHILD = r'''
import sys
from click.testing import CliRunner
from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository
from use_cases.import_transactions import ImportTransactionsUseCase

book, case = sys.argv[1], sys.argv[2]
made = CliRunner().invoke(cli, ['import', '--new', book, 'tests/fixtures/q019_accounts.txt'])
assert made.exit_code == 0, made.output
cases = {
    'no-splits': {'date': '2026-02-10', 'description': 'Nothing moved', 'splits': [], 'currency': 'CAD'},
    'unknown-currency': {'date': '2026-02-10', 'description': 'Unknown currency', 'currency': 'XYZ',
                         'splits': [{'account': 'Expenses:Office Supplies', 'amount': '5.00'},
                                    {'account': 'Assets:Bank', 'amount': '-5.00'}]},
}
repo = GnuCashRepository(book)
repo.open()
try:
    result = ImportTransactionsUseCase(repo).execute([cases[case]])
    print('imported', result.imported_count, 'errors', result.errors)
finally:
    repo.close()
'''

with tempfile.TemporaryDirectory() as directory:
    for case in ('no-splits', 'unknown-currency'):
        book = str(Path(directory) / f'{case}.gnucash')
        done = subprocess.run([sys.executable, '-c', CHILD, book, case], capture_output=True, text=True)
        said = [line for line in (done.stdout + done.stderr).splitlines()
                if line.startswith(('imported', 'Traceback', 'AssertionError')) or 'Error' in line]
        print(f'{case:17} exit {done.returncode:4}  {said[-3:] if said else "(nothing)"}')
