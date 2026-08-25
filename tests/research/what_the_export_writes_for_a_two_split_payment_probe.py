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

import sys
import tempfile
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')


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
         str(FIXTURES / 'a_payment_naming_two_settling_splits.txt'),
         '--include-business-objects'],
    ):
        # GnuCash names its backup to the second and refuses a collision.
        time.sleep(1.1)
        result = runner.invoke(cli, args)
        print(f'{args[0]} {Path(args[3] if args[1] == "--new" else args[2]).name}'
              f' → exit {result.exit_code}')
        if result.exit_code != 0:
            print(result.output)
            return 1

    out = tmp / 'out.txt'
    result = runner.invoke(cli, ['export', str(book), '--output', str(out),
                                 '--include-business-objects'])
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
