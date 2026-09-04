"""What `export` writes for one payment made of two settling splits.

Prints the invoice block, so the shape is read rather than inferred. What it
showed while this was being written was two `payment:` blocks for one payment
— the money having arrived once, which is what made grouping them the answer —
and what it shows now is the one block with a `Transaction` naming both
splits.

Kept because the question outlives the defect: this is how to look at what the
writer actually emits for a grouped payment, which is the half of the
round-trip a test asserting `unchanged` does not show you.
"""

import os
import sys
import tempfile
from pathlib import Path

# The repo root, so `tests` is importable when this is run as a script. The
# editable install puts `cli` and the rest of the package on the path; the
# suite's own directory is not part of it.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', '..')))

from click.testing import CliRunner  # noqa: E402

from tests.conftest import _run  # noqa: E402

FIXTURES = Path('tests/fixtures')

# Every command through `_run`, and importing `tests.conftest` is the half
# that matters: it deletes the backup and log files a second save inside one
# second would collide on. This probe is run as a script, so pytest loads no
# conftest for it, and GnuCash's ERR_FILEIO_BACKUP_ERROR is swallowed by the
# CLI's save handler — three imports back to back would each exit 0 while
# only the first reached the disk, and the block printed below would be
# missing the payment the probe exists to show.


def main():
    tmp = Path(tempfile.mkdtemp())
    book = tmp / 'book.gnucash'
    runner = CliRunner()

    for args in (
        ['import', '--new', str(book),
         str(FIXTURES / 'fx_usd_invoice_cad_income.txt'),
         '--include-business-objects',
         '--fx-rates', str(FIXTURES / 'fx_rates_usd_dated.yaml')],
        ['import', str(book),
         str(FIXTURES / 'money_arriving_as_two_receivable_splits.txt')],
        ['import', str(book),
         str(FIXTURES / 'a_payment_giving_two_settling_splits.txt'),
         '--include-business-objects'],
    ):
        result = _run(runner, *args)
        print(f'{args[0]} {Path(args[3] if args[1] == "--new" else args[2]).name}'
              f' → exit {result.exit_code}')
        if result.exit_code != 0:
            print(result.output)
            return 1

    out = tmp / 'out.txt'
    result = _run(runner, 'export', str(book), '--output', str(out),
                  '--include-business-objects')
    if result.exit_code != 0:
        print(result.output)
        return 1

    text = out.read_text(encoding='utf-8')
    print()
    print('=' * 70)
    print('the invoice block as exported')
    print('=' * 70)
    keep = False
    for line in text.splitlines():
        if line.startswith('invoice "'):
            keep = True
        elif keep and line and not line[0].isspace():
            keep = False
        if keep:
            print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
