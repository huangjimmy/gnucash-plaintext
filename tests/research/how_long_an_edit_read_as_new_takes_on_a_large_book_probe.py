"""How long `import --strategy update` takes on a book of 5,000 transactions, when the edits are read as new.

An edit that moves a split on a transaction touching a cost basis is read as
the transaction would be read if it were new (Q-051). This measures what such
an edit costs on a large book, beside an edit changing only a description and
the book's own export unchanged. When it was written, two of the steps that
reading takes, and one every transaction touching a cost basis took, walked
every split in the book once per edit; they now ask an index of the book
(`splits_drawing_on`).

This builds one book of 5,000 transactions through the CLI. The counts are
of transactions:

- 3,000 transactions of office supplies paid from a chequing account, in
  Canadian dollars only;
- 1,000 transactions buying US dollars, 100.00 USD for 140.00 CAD each, each
  opening a cost basis;
- 800 transactions selling US dollars, 50.00 USD each, each drawing on one
  of those purchases;
- 200 statement lines, each one transaction: a 100.00 USD deposit against
  `Assets:Due from director`, with a 1.00 USD fee drawing on it.

Then, each on a fresh copy of that book, it times `import --strategy update`
of the book's own export with K of the statement lines changed:

- unchanged: the export as it is;
- description: K descriptions changed, which is edited in place;
- read as new: K deposits booked as income and their fees as a bank charge,
  which moves a split and is read as new.

And profiles the largest read-as-new run, to say where the time goes.

Measured on Debian 13 (GnuCash 5.10): before the fixes the unchanged update
was still running after 8 minutes; once no step walked the whole book per
transaction it took 58.2 s, and every edited run 58 to 61 s; once a
transaction the file states as the book holds it was left alone, 2.2 s, with
200 lines read as new 7.6 s. Every build is in the section "How long an
update takes as the book grows" of
`docs/issues/Q-051-let-a-statement-line-on-a-holding-account-be-edited-into-the-invoice-or-bill-it-settles.md`.

Run, with the project installed in the container as `scripts/test.sh` does:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
        -e PYTHONPATH=/workspace -v "$PWD:/workspace" -w /workspace \
        gnucash-dev:<tag> sh -c 'python3 -m pip install -e ".[dev]" \
            --break-system-packages --user -q && python3 \
            tests/research/how_long_an_edit_read_as_new_takes_on_a_large_book_probe.py'
"""

import cProfile
import io
import pstats
import re
import shutil
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

from click.testing import CliRunner

import tests.conftest  # noqa: F401  (removes the backup a second save in one second would collide on)
from cli.main import cli

PLAIN = 3000
PURCHASES = 1000
SALES = 800
LINES = 200
EDITS = (1, 10, 50, 200)

HEADER = '''2025-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2025-01-01 commodity USD
\tmnemonic: "USD"
\tfullname: "US Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
'''

ACCOUNTS = [
    ('Assets', 'Asset', 'CAD', True),
    ('Assets:Wise USD', 'Bank', 'USD', False),
    ('Assets:Chequing', 'Bank', 'CAD', False),
    ('Assets:Due from director', 'Asset', 'CAD', False),
    ('Expenses', 'Expense', 'CAD', True),
    ('Expenses:Office', 'Expense', 'CAD', False),
    ('Expenses:Bank charges', 'Expense', 'CAD', False),
    ('Income', 'Income', 'CAD', True),
    ('Income:Sales', 'Income', 'CAD', False),
    ('Income:FX gain', 'Income', 'CAD', False),
]


def ledger() -> str:
    parts = [HEADER]
    for name, kind, commodity, placeholder in ACCOUNTS:
        parts.append(f'2025-01-01 open {name}\n\ttype: "{kind}"\n'
                     + ('\tplaceholder: #True\n' if placeholder else '')
                     + f'\tcommodity.namespace: "CURRENCY"\n'
                       f'\tcommodity.mnemonic: "{commodity}"\n')
    start = date(2025, 1, 2)
    for i in range(PLAIN):
        when = start + timedelta(days=i % 365)
        cents = 1000 + i
        amount = f'{cents // 100}.{cents % 100:02d}'
        parts.append(f'{when} * "Office supplies {i}"\n'
                     f'\tguid: "a{i:031x}"\n'
                     f'\tcurrency.mnemonic: "CAD"\n'
                     f'\tExpenses:Office {amount} CAD\n\t\tguid: "b{i:031x}"\n'
                     f'\tAssets:Chequing -{amount} CAD\n\t\tguid: "c{i:031x}"\n')
    # Purchases first, in 2025, so every sale finds its cost basis in the book.
    for p in range(PURCHASES):
        when = start + timedelta(days=p % 300)
        parts.append(f'{when} * "Dollars bought {p}"\n'
                     f'\tguid: "1{p:031x}"\n'
                     f'\tcurrency.mnemonic: "CAD"\n'
                     f'\tAssets:Wise USD 100.00 USD\n\t\tguid: "2{p:031x}"\n'
                     f'\t\taccount.commodity.mnemonic: "USD"\n\t\tvalue: "140.00"\n'
                     f'\tAssets:Chequing -140.00 CAD\n\t\tguid: "3{p:031x}"\n')
    # Each sale draws half of one purchase, valued at its cost, 1.40.
    for s in range(SALES):
        when = date(2025, 11, 1) + timedelta(days=s % 60)
        parts.append(f'{when} * "Dollars sold {s}"\n'
                     f'\tguid: "4{s:031x}"\n'
                     f'\tcurrency.mnemonic: "CAD"\n'
                     f'\tAssets:Wise USD -50.00 USD\n\t\tguid: "5{s:031x}"\n'
                     f'\t\taccount.commodity.mnemonic: "USD"\n\t\tvalue: "-70.00"\n'
                     f'\t\tcost_basis_split_guid: "2{s:031x}"\n'
                     f'\tAssets:Chequing 72.00 CAD\n\t\tguid: "6{s:031x}"\n'
                     f'\tIncome:FX gain -2.00 CAD\n\t\tguid: "7{s:031x}"\n')
    for j in range(LINES):
        when = date(2026, 1, 1) + timedelta(days=j)
        split = [f'e{4 * j + k:031x}' for k in range(4)]
        parts.append(f'{when} * "Statement line {j}"\n'
                     f'\tguid: "d{j:031x}"\n'
                     f'\tcurrency.mnemonic: "CAD"\n'
                     f'\tAssets:Wise USD 100.00 USD\n\t\tguid: "{split[0]}"\n'
                     f'\t\taccount.commodity.mnemonic: "USD"\n\t\tvalue: "140.00"\n'
                     f'\tAssets:Due from director -140.00 CAD\n\t\tguid: "{split[1]}"\n'
                     f'\tAssets:Due from director 1.40 CAD\n\t\tguid: "{split[2]}"\n'
                     f'\tAssets:Wise USD -1.00 USD\n\t\tguid: "{split[3]}"\n'
                     f'\t\taccount.commodity.mnemonic: "USD"\n\t\tvalue: "-1.40"\n'
                     f'\t\tcost_basis_split_guid: "{split[0]}"\n')
    return '\n'.join(parts)


def run(*args):
    done = CliRunner().invoke(cli, [str(each) for each in args])
    assert done.exit_code == 0 and (args[0] != 'import' or 'Errors:       0' in done.output), \
        done.output
    return done


def block(text, j):
    return re.search(rf'\d{{4}}-\d\d-\d\d \* "Statement line {j}"\n(?:\t[^\n]*\n)*',
                     text).group(0)


def edited(text, count, how):
    for j in range(count):
        old = block(text, j)
        if how == 'description':
            new = old.replace(f'"Statement line {j}"', f'"Statement line {j}, checked"')
        else:
            new = (old.replace('Assets:Due from director -140.00 CAD', 'Income:Sales -140.00 CAD')
                   .replace('Assets:Due from director 1.40 CAD', 'Expenses:Bank charges 1.40 CAD'))
        assert new != old
        text = text.replace(old, new)
    return text


def main():
    work = Path(tempfile.mkdtemp())
    source = work / 'ledger.txt'
    source.write_text(ledger())
    book = work / 'book.gnucash'
    started = time.perf_counter()
    run('import', '--new', book, source)
    print(f'built: {PLAIN + PURCHASES + SALES + LINES} transactions '
          f'({PLAIN} Canadian dollar only, {PURCHASES} purchases, {SALES} sales, '
          f'{LINES} statement lines) in {time.perf_counter() - started:.1f} s')
    exported = work / 'exported.txt'
    run('export', book, exported)
    text = exported.read_text()

    def timed(label, content, profile=False):
        copy = work / 'copy.gnucash'
        shutil.copy(book, copy)
        edit = work / 'edit.txt'
        edit.write_text(content)
        profiler = cProfile.Profile() if profile else None
        started = time.perf_counter()
        if profiler:
            profiler.enable()
        run('import', copy, edit, '--strategy', 'update')
        if profiler:
            profiler.disable()
        print(f'{label:<28} {time.perf_counter() - started:7.1f} s')
        return profiler

    timed('unchanged', text)
    for count in EDITS:
        timed(f'{count} descriptions', edited(text, count, 'description'))
        timed(f'{count} read as new', edited(text, count, 'read as new'))

    profiler = timed(f'{EDITS[-1]} read as new, profiled',
                     edited(text, EDITS[-1], 'read as new'), profile=True)
    out = io.StringIO()
    pstats.Stats(profiler, stream=out).sort_stats('cumulative').print_stats(
        r'gnucash_importer|foreign_currency', 30)
    print(out.getvalue())
    shutil.rmtree(work)


if __name__ == '__main__':
    main()
