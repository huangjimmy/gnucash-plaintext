"""Probe: what the itemized balance sheet becomes on a book with thousands of splits.

Every itemized key lists one entry per thing it is measured from, and nothing
caps any of the four:

- `gnucash_balancing_amount` lists one `split:` per split whose transaction is
  stated in that currency, on every account holding it;
- `unrealized_gains_assets_fx` lists one `cost_basis:` per cost basis;
- `realized_gains_fx` lists one `split:` per disposal that took a difference;
- `unrealized_gains_other` lists one `security:` per security.

On the eleven committed examples the longest list is 39 splits, which reads
fine. A real book is not eleven transactions.

**Every purchase here is different, and that is the point of the probe.** An
earlier version bought 1.00 USD at 1.30 two and a half thousand times, so the
entries came out identical and any roll-up looked free — a property of the
generator, not of the format. Here the amount, the rate and so the
`cost_share_price`, the date, and both accounts vary from one purchase to the
next, which is what a real book looks like.

So the probe measures, rather than assumes, how far the entries would collapse
if they were grouped: how many distinct accounts the listed splits are on, and
how many distinct account-and-price pairs the cost bases fall into. Where those
counts are close to the number of entries, grouping buys nothing and only a cap
can shorten the page.

    ./scripts/test.sh latest tests/research/how_a_page_grows_with_the_splits_behind_it_probe.py

`GNC_TEST_MEMORY=2g` if a larger size is added.
"""

import datetime
import random
import time
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

AS_OF = '2026-12-31'

SIZES = (25, 250, 2500)

SEED = 20260919

ITEMIZED = ('unrealized_gains_assets_fx', 'realized_gains_fx',
            'unrealized_gains_other', 'gnucash_balancing_amount')

USD_ACCOUNTS = ('Assets:USD Bank Alpha', 'Assets:USD Bank Beta',
                'Assets:USD Bank Gamma', 'Assets:USD Bank Delta')
CAD_ACCOUNTS = ('Assets:CAD Bank One', 'Assets:CAD Bank Two',
                'Assets:CAD Bank Three')

FIRST_DAY = datetime.date(2026, 2, 1)
LAST_DAY = datetime.date(2026, 11, 30)


def _account_block(name, commodity):
    return (f'2026-01-01 open {name}\n'
            f'\ttype: "Bank"\n'
            f'\tcommodity.namespace: "CURRENCY"\n'
            f'\tcommodity.mnemonic: "{commodity}"\n')


def _header():
    parts = ['''2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity USD
\tmnemonic: "USD"
\tfullname: "US Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: "Asset"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Equity
\ttype: "Equity"
\tplaceholder: #True
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Equity:Opening CAD
\ttype: "Equity"
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
''']
    for name in CAD_ACCOUNTS:
        parts.append(_account_block(name, 'CAD'))
    for name in USD_ACCOUNTS:
        parts.append(_account_block(name, 'USD'))
    parts.append('''
price
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"
\tcurrency.mnemonic: "CAD"
\ttime: "2026-12-31 12:00:00 +0000"
\tvalue: "29/20"
\tsource: "user:price-editor"
\ttype: "last"

2026-01-15 * "Opening capital"
\tcurrency.mnemonic: "CAD"
\tAssets:CAD Bank One 100000000.00 CAD
\tEquity:Opening CAD -100000000.00 CAD
''')
    return ''.join(parts)


def _money(cents):
    return f'{cents // 100}.{cents % 100:02d}'


def _ledger(count):
    """`count` purchases, no two alike.

    The amount is a cent figure of its own, and the value another, so the
    price each basis records is `value / amount` — a different fraction for
    every one of them. Dates walk the year and the accounts rotate, so no two
    entries agree on account, date, amount, price or cost.
    """
    rng = random.Random(SEED)
    span = (LAST_DAY - FIRST_DAY).days
    blocks = [_header()]
    for index in range(count):
        amount_cents = rng.randint(100, 500000)
        rate = Fraction(rng.randint(12000, 15000), 10000)
        value_cents = int(amount_cents * rate)
        if value_cents <= 0:
            value_cents = 1
        price = Fraction(value_cents, amount_cents)
        when = FIRST_DAY + datetime.timedelta(days=rng.randint(0, span))
        usd = USD_ACCOUNTS[index % len(USD_ACCOUNTS)]
        cad = CAD_ACCOUNTS[index % len(CAD_ACCOUNTS)]
        blocks.append(
            f'{when.isoformat()} * "Buy {_money(amount_cents)} USD, number {index + 1}"\n'
            f'\tcurrency.mnemonic: "CAD"\n'
            f'\t{usd} {_money(amount_cents)} USD\n'
            f'\t\taccount.commodity.mnemonic: "USD"\n'
            f'\t\tshare_price: "{price.numerator}/{price.denominator}"\n'
            f'\t\tvalue: "{_money(value_cents)}"\n'
            f'\t{cad} -{_money(value_cents)} CAD\n')
    return '\n'.join(blocks)


def _blocks(page):
    """Each indent-1 key on the page, with the lines indented under it."""
    found = {}
    current = None
    for line in page.splitlines():
        if line.startswith('\t') and not line.startswith('\t\t'):
            current = line.strip().split(':')[0]
            found[current] = []
        elif current is not None and line.startswith('\t\t'):
            found[current].append(line)
    return found


def _entries(lines, opener, fields):
    """Every `opener:` entry in `lines`, as a dict of the `fields` under it.

    Read off the rendered page rather than from the book, so what is counted
    is what a reader would actually be scrolling past.
    """
    found = []
    current = None
    for line in lines:
        stripped = line.strip()
        if stripped == f'{opener}:':
            current = {}
            found.append(current)
            continue
        if current is None:
            continue
        for field in fields:
            if stripped.startswith(f'{field}: '):
                current[field] = stripped[len(field) + 2:]
    return found


def _make(tmp_path, count):
    book = tmp_path / f'probe-{count}.gnucash'
    ledger = tmp_path / f'ledger-{count}.txt'
    ledger.write_text(_ledger(count), encoding='utf-8')

    started = time.monotonic()
    made = CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger)])
    assert made.exit_code == 0, made.output
    return book, time.monotonic() - started


def _draw(book, *extra):
    started = time.monotonic()
    drawn = CliRunner().invoke(
        cli, ['balance-sheet', str(book), '--as-of', AS_OF] + list(extra))
    assert drawn.exit_code == 0, drawn.output
    return drawn.output, time.monotonic() - started


def test_how_a_page_grows_with_the_splits_behind_it(tmp_path, capsys):
    pages = {}
    books = {}
    drew_in = {}
    with capsys.disabled():
        print()
        print(f'{"purchases":>10} {"splits":>8} {"page lines":>11} {"page KB":>9} '
              f'{"import s":>9} {"draw s":>8}')
        for count in SIZES:
            book, imported = _make(tmp_path, count)
            page, drew = _draw(book)
            books[count] = book
            pages[count] = page
            drew_in[count] = drew
            print(f'{count:>10} {count * 2:>8} {len(page.splitlines()):>11} '
                  f'{len(page.encode()) / 1024:>9.1f} {imported:>9.1f} {drew:>8.1f}')

        print()
        print('lines under each itemized key:')
        print(f'{"purchases":>10}' + ''.join(f'{name:>32}' for name in ITEMIZED))
        for count in SIZES:
            blocks = _blocks(pages[count])
            print(f'{count:>10}'
                  + ''.join(f'{len(blocks.get(name, [])):>32}' for name in ITEMIZED))

        print()
        print('how far the entries would collapse if they were grouped:')
        print(f'{"purchases":>10} {"split entries":>14} {"distinct accts":>15} '
              f'{"basis entries":>14} {"distinct acct+price":>20}')
        for count in SIZES:
            blocks = _blocks(pages[count])
            splits = _entries(blocks.get('gnucash_balancing_amount', []),
                              'split', ('account', 'value'))
            bases = _entries(blocks.get('unrealized_gains_assets_fx', []),
                             'cost_basis', ('account', 'cost_share_price'))
            accounts = {entry.get('account') for entry in splits}
            pairs = {(entry.get('account'), entry.get('cost_share_price'))
                     for entry in bases}
            print(f'{count:>10} {len(splits):>14} {len(accounts):>15} '
                  f'{len(bases):>14} {len(pairs):>20}')

        biggest = pages[SIZES[-1]]
        block = _blocks(biggest).get('unrealized_gains_assets_fx', [])
        print()
        print(f'==== unrealized_gains_assets_fx on {SIZES[-1]} purchases: '
              f'{len(block)} lines ====')
        for line in block[:32]:
            print(line)
        print(f'    … {len(block) - 40} lines not shown …')
        for line in block[-8:]:
            print(line)

        print()
        print('the whole page, for scale:')
        print(f'  {len(biggest.splitlines())} lines, '
              f'{len(biggest.encode()) / 1024:.0f} KB, of which the four itemized '
              f'keys are '
              f'{sum(len(_blocks(biggest).get(n, [])) for n in ITEMIZED)} lines')

        # The same book, the same command, one option added.
        widest = SIZES[-1]
        capped, capped_drew = _draw(books[widest], '--max-items', '5')
        print()
        print(f'==== the same {widest}-purchase book with --max-items 5 ====')
        print(f'  every entry: {len(pages[widest].splitlines()):>6} lines, '
              f'{len(pages[widest].encode()) / 1024:>7.1f} KB, '
              f'drawn in {drew_in[widest]:.1f} s')
        print(f'  capped:      {len(capped.splitlines()):>6} lines, '
              f'{len(capped.encode()) / 1024:>7.1f} KB, '
              f'drawn in {capped_drew:.1f} s')
        print()
        print('  and the four keys in full, so the shape can be read rather than')
        print('  described — every total below is summed over all the entries,')
        print('  not over the ones listed:')
        for name in ITEMIZED:
            block = _blocks(capped).get(name, [])
            print()
            print(f'---- {name}: {len(block)} lines ----')
            for line in block:
                print(line)

        # The pages themselves, to be opened rather than scrolled past: forty
        # thousand lines is a file, not output.
        #
        # Under `/tmp`, never `/workspace`. `scripts/test.sh` mounts the
        # project there, so writing to it puts two root-owned files of about
        # 1.4 MB into the working tree — untracked, unignored, and an obstacle
        # to `git worktree remove` like the rest of the container-owned build
        # output. The path is printed, and a reader who wants them kept copies
        # them out.
        pages_at = Path('/tmp/itemized-pages')
        pages_at.mkdir(parents=True, exist_ok=True)
        whole = pages_at / 'itemized-every-entry.txt'
        short = pages_at / 'itemized-max-items-5.txt'
        whole.write_text(pages[widest], encoding='utf-8')
        short.write_text(capped, encoding='utf-8')
        print()
        print(f'written: {whole} ({len(pages[widest].splitlines())} lines)')
        print(f'         {short} ({len(capped.splitlines())} lines)')
