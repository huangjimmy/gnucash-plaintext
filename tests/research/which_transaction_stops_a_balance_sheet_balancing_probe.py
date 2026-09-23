"""Draw the balance sheet after each transaction of a ledger, and say which one
stops it balancing or takes a cost basis out of step.

A book always balances once the unrealized gain is on the page: assets equal
liabilities and equity, because the unrealized figure is the difference the
other three leave. And per currency and side, what the cost bases hold is what
the accounts hold. When either stops being true, the way to find out why is to
build the book one transaction at a time and ask both questions after each,
because the step where an answer first changes is the step that is wrong.

    ./scripts/run.sh latest bash -lc 'cd /workspace && \
        python3 -m pip install -e ".[dev]" --quiet --break-system-packages && \
        PYTHONPATH=/workspace python3 \
        tests/research/which_transaction_stops_a_balance_sheet_balancing_probe.py \
            tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt \
            2026-12-31'

Each row prints the two page totals and their difference, the unrealized and
retained figures beside them, and one `USD asset 1400.00/7480.00` group per
currency and side whose cost bases and accounts disagree.
"""

import re
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

import tests.conftest  # noqa: F401  — patches the save so no backup collides
from cli.main import cli

A_TRANSACTION = re.compile(r'^\d{4}-\d{2}-\d{2} \*')
A_BASIS_TOTAL = re.compile(r'^Total (\w+) cost basis balance: ([\d,.]+)', re.M)
A_HOLDING_TOTAL = re.compile(r'^Total (\w+) (held in|owed on) accounts: ([\d,.]+)', re.M)


def blocks_of(text):
    """The ledger split into top-level blocks, in order.

    A block starts at column 0 and takes every indented line under it. Comments
    and blank lines stay with the block above, which keeps the file readable
    when a prefix of it is written back out.
    """
    found = []
    current = []
    for line in text.splitlines(keepends=True):
        if line[:1] not in ('', '\t', ' ', '#', '\n') and current:
            found.append(''.join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        found.append(''.join(current))
    return found


def key_of(page, name):
    """A top-level key's figure, as an exact Fraction, or None."""
    found = re.search(rf'^\t{re.escape(name)}: (-?[\d.]+)', page, re.M)
    return Fraction(found.group(1)) if found else None


def figure(text):
    return Fraction(text.replace(',', ''))


def out_of_step(listing):
    """Each currency and side whose cost bases and accounts disagree.

    `fx-balances` totals the cost bases per currency without saying which side
    each belongs to, so the two sides are added before they are compared — which
    is the comparison this listing supports. A book that holds a currency and
    owes it at once needs the balance sheet's own per-side figures to go further.
    """
    bases = {currency: figure(amount)
             for currency, amount in A_BASIS_TOTAL.findall(listing)}
    held = {}
    for currency, _side, amount in A_HOLDING_TOTAL.findall(listing):
        held[currency] = held.get(currency, Fraction(0)) + figure(amount)
    differ = []
    for currency in sorted(set(bases) | set(held)):
        mine = bases.get(currency, Fraction(0))
        theirs = held.get(currency, Fraction(0))
        if mine != theirs:
            differ.append(f'{currency} {float(mine):.2f}/{float(theirs):.2f}')
    return differ


def main():
    ledger = Path(sys.argv[1])
    as_of = sys.argv[2]
    # A third argument is the currency to draw in, for a book whose own
    # currency nothing states — `comprehensive_test_data.txt` keeps five
    # top-level accounts in five currencies, and the statements are refused
    # without it, so every step of it went unchecked.
    currency = ['--currency', sys.argv[3]] if len(sys.argv) > 3 else []
    blocks = blocks_of(ledger.read_text(encoding='utf-8'))
    transactions = [i for i, block in enumerate(blocks)
                    if A_TRANSACTION.match(block)]
    header = ''.join(blocks[:transactions[0]])

    runner = CliRunner()
    print(f'{"#":>3}  {"assets":>13} {"liab+equity":>13} {"difference":>11} '
          f'{"unrealized":>11} {"gnucash":>11} {"retained":>11}  '
          f'{"bases/accounts":<22} transaction')
    for count, last in enumerate(transactions, start=1):
        part = header + ''.join(blocks[first] for first in transactions[:count])
        description = blocks[last].splitlines()[0].strip()
        with tempfile.TemporaryDirectory() as workspace:
            book = Path(workspace) / 'part.gnucash'
            written = Path(workspace) / 'part.txt'
            written.write_text(part, encoding='utf-8')
            made = runner.invoke(cli, ['import', '--new', str(book), str(written)])
            if made.exit_code != 0:
                print(f'{count:>3}  import refused: {made.output.strip().splitlines()[-1]}')
                continue
            drawn = runner.invoke(cli, ['balance-sheet', str(book),
                                        '--as-of', as_of, '--no-itemize']
                                  + currency)
            listed = runner.invoke(cli, ['fx-balances', str(book)])
            if drawn.exit_code != 0:
                print(f'{count:>3}  balance-sheet refused: {drawn.output.strip()}')
                continue
            page, listing = drawn.output, listed.output
        assets = key_of(page, 'total_assets')
        both = key_of(page, 'total_liabilities_and_equity')
        if assets is None or both is None:
            print(f'{count:>3}  the page states no total_assets or no '
                  f'total_liabilities_and_equity  {description}')
            continue
        # A key the page leaves off is a figure of nothing, not a figure that
        # could not be read: `retained_earnings` and the gain keys are written
        # only where they hold something, so reading their absence as
        # unreadable skipped every step before the book had earned anything —
        # which is the half of the ledger where a fault is cheapest to find.
        unrealized, gnucash, retained = (
            key_of(page, name) or Fraction(0) for name in
            ('total_unrealized_gains', 'gnucash_balancing_amount',
             'retained_earnings'))
        print(f'{count:>3}  {float(assets):>13.2f} {float(both):>13.2f} '
              f'{float(both - assets):>11.2f} {float(unrealized):>11.2f} '
              f'{float(gnucash):>11.2f} {float(retained):>11.2f}  '
              f'{", ".join(out_of_step(listing)) or "agree":<22} {description}')


if __name__ == '__main__':
    main()
