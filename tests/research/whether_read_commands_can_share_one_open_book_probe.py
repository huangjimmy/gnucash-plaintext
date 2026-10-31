"""Whether read commands can run against one book opened once, and what that saves.

The question behind a read-only batch: a person runs several read commands
against one book (two balance sheets, an income statement, an export), and
each opens the book, reads it and closes it, in a process of its own.

This probe runs the same commands four ways and times each:

1. each in a process of its own, as a person runs them from a shell;
2. each in this process, opening and closing the book itself, as they do today;
3. each in this process against one session opened once, by standing
   `GnuCashRepository.open` and `close` in for the shared session;
4. `gnucash-plaintext batch`, in a process of its own, as a person runs it.

It compares what each command printed in (2) and (3) byte for byte, and each
file (4) wrote with what the command writes alone.

Then it asks whether one command leaves anything behind that the next reads,
on a book holding US dollars: `balance-sheet --fx-rates` adds the file's
prices to the book for the run, and nothing takes them off, because the book
is closed straight afterwards. Shared, the next `balance-sheet` with no rates
file might read them.

Measured on GnuCash 5.10 (Debian 13), 2026-10-29, on a book of 18,000
transactions, 1.67 MB on disk, with six commands: two balance sheets, two
income statements, an export and verify-integrity. This was before the
balance sheet's split listing was fixed (Q-058), so the times are longer than
the table below.

- Each in a process of its own: 32.58 s. Each in this process opening the
  book itself: 24.78 s. Against one book opened once: 18.46 s, the open
  included. The batch takes 14.12 s less than six processes.
- A process that starts, imports the CLI and GnuCash and exits takes 0.29 s.
  Opening the book read-only and closing it takes 0.75 to 0.78 s.
- An income statement took 1.22 s opening the book itself and 0.15 s on the
  open book, so the open was most of it.
- Every command printed and wrote the same thing, byte for byte, either way.
- A rates file's prices reach the next command. On a book holding USD and
  EUR, `balance-sheet --fx-rates` stated 7,000.00 CAD of assets, and the
  next `balance-sheet` with no rates file stated 7,000.00 CAD on the shared
  book where it states 4,050.20 CAD alone. The book on disk was unchanged.

Measured on all eleven builds, 2026-10-30, one build at a time with nothing
else running, the same book and the same six commands, all four ways. Every
command printed the same thing in (2) and (3), every file `batch` wrote was
the same as the command's alone, and in (3) a rates file's prices reached the
next command, on every build. `batch` itself reads the book from disk again
after such a command, so in (4) they do not.

The run below was made 2026-10-31, the same way, with the balance sheet's
listing fixed, what a read reads kept (the splits of the book and each
object's custom metadata, for as long as only books open to read are open),
the export reading each account's facts once a pass, and lists walked from
ctypes below 3.8 (Q-058). Every output was the same in it too. In the runs of
2026-10-30, (4) took 23.16 s on 3.4, 10.70 to 13.22 s from 3.8 to 5.5 and
6.60 to 8.39 s from 5.10 with what a read reads kept, and 153.70 s, 12.38 to
15.20 s and 8.83 to 11.32 s with nothing kept.

| GnuCash | image | one open and close | (1) six processes | (3) one book, this process | (4) `batch` | (4) saved on (1) |
|---|---|---|---|---|---|---|
| 3.4 | debian10 | 5.17 – 5.83 s | 43.26 s | 15.34 s | 12.25 s | 31.01 s, 72% |
| 3.8 | ubuntu20 | 4.95 – 5.29 s | 41.62 s | 12.85 s | 11.29 s | 30.33 s, 73% |
| 4.4 | debian11 | 4.85 – 5.51 s | 38.84 s | 13.07 s | 10.39 s | 28.45 s, 73% |
| 4.8 | ubuntu22 | 3.80 – 5.16 s | 35.03 s | 12.51 s | 9.71 s | 25.32 s, 72% |
| 4.13 | debian12 | 3.46 – 4.19 s | 31.87 s | 11.19 s | 9.20 s | 22.67 s, 71% |
| 5.5 | ubuntu24 | 4.01 – 4.24 s | 41.09 s | 14.27 s | 10.76 s | 30.33 s, 74% |
| 5.10 | latest | 0.74 – 0.76 s | 11.82 s | 5.54 s | 5.41 s | 6.41 s, 54% |
| 5.13 | fedora41 | 0.86 – 0.87 s | 13.18 s | 5.88 s | 6.13 s | 7.05 s, 53% |
| 5.14 | ubuntu26 | 0.70 – 0.71 s | 11.06 s | 5.15 s | 5.24 s | 5.82 s, 53% |
| 5.15 | arch | 0.69 – 0.71 s | 11.72 s | 5.50 s | 5.68 s | 6.04 s, 52% |
| 5.16 | opensuse | 0.72 – 0.73 s | 12.79 s | 6.47 s | 6.61 s | 6.18 s, 48% |

- From 5.10, (4) took between 0.13 s less and 0.25 s more than (3). Up to
  5.5 it took 1.56 to 3.51 s less, because the open in (3) was slower (4.95
  to 6.88 s) than the open in (4).
- On the open book, on every build, the first balance sheet took 0.65 to
  1.17 s, the second 0.35 to 0.55 s, an income statement 0.14 to 0.27 s, the
  export 1.98 to 2.88 s and verify-integrity 0.91 to 1.42 s. 3.4 is the
  slowest of each.
- GnuCash's report system costs about 0.3 s to load on 5.10, measured on a
  book of 300 transactions held open: the first balance sheet took 0.32 s and
  each after it 0.02 s.
- Opening the book takes 3.5 to 5.8 s on every build up to 5.5 and 0.7 to
  0.9 s from 5.10. Up to 5.5 most of it is GnuCash searching an account's
  list of splits each time it puts a split in the account, and again as it
  frees the book (Q-058).

Run:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \\
        -v "$PWD:/workspace" -w /workspace gnucash-dev:<tag> sh -c \\
        'python3 -m pip install -e ".[dev]" --break-system-packages --user -q;
         python3 tests/research/whether_read_commands_can_share_one_open_book_probe.py'
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from click.testing import CliRunner
from gnucash import Account, GncNumeric, Split, Transaction

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

TRANSACTIONS = int(os.environ.get('PROBE_TRANSACTIONS', '18000'))
FIXTURES = Path('tests/fixtures')


def build_book(path, transactions):
    """A CAD book: a bank, salary and three expense accounts, over 2024 and 2025."""
    repo = GnuCashRepository(path)
    repo.open(SessionMode.NEW)
    book = repo.book
    cad = book.get_table().lookup('CURRENCY', 'CAD')
    root = book.get_root_account()
    made = {}
    for label, kind in (('Bank', 2), ('Salary', 8), ('Groceries', 9), ('Rent', 9), ('Travel', 9)):
        account = Account(book)
        account.BeginEdit()
        account.SetName(label)
        account.SetType(kind)
        account.SetCommodity(cad)
        root.append_child(account)
        account.CommitEdit()
        made[label] = account
    for i in range(transactions):
        tx = Transaction(book)
        tx.BeginEdit()
        tx.SetCurrency(cad)
        tx.SetDate(1 + i % 28, 1 + (i // 28) % 12, 2024 + i % 2)
        other = ('Salary', 'Groceries', 'Rent', 'Travel')[i % 4]
        cents = 100000 + i if other == 'Salary' else -(1000 + i % 9000)
        tx.SetDescription(f'{other} {i}')
        for account, amount in ((made['Bank'], cents), (made[other], -cents)):
            split = Split(book)
            split.SetParent(tx)
            split.SetAccount(account)
            split.SetValue(GncNumeric(amount, 100))
            split.SetAmount(GncNumeric(amount, 100))
        tx.CommitEdit()
    repo.save()
    repo.close()


COMMANDS = [
    ['balance-sheet', '--as-of', '2025-12-31'],
    ['balance-sheet', '--as-of', '2024-12-31'],
    ['income-statement', '--start', '2025-01-01', '--end', '2025-12-31'],
    ['income-statement', '--start', '2024-01-01', '--end', '2024-12-31'],
    ['export', '{out}'],
    ['verify-integrity'],
]


def with_book(command, book, out=None):
    rest = [str(out) if word == '{out}' else word for word in command[1:]]
    return [command[0], str(book)] + rest


def what_it_wrote(done, out):
    """What a command printed, and what it wrote to its output file."""
    written = out.read_text() if out.exists() else ''
    if out.exists():
        out.unlink()
    return done.output + written


class OneOpenBook:
    """`GnuCashRepository.open` and `close` stood in for one session opened once."""

    def __init__(self, path):
        self.repo = GnuCashRepository(str(path))
        self.repo.open(SessionMode.READ_ONLY)
        self.opens = 0

    def __enter__(self):
        shared = self.repo
        probe = self
        self.real_open, self.real_close = GnuCashRepository.open, GnuCashRepository.close

        def open_(repo, mode=SessionMode.NORMAL):
            if mode != SessionMode.READ_ONLY:
                raise RuntimeError(f'a read command asked for the book in mode {mode!r}')
            probe.opens += 1
            repo.session, repo._book, repo._read_only = shared.session, shared.book, True

        def close_(repo):
            if repo is shared:
                return probe.real_close(repo)
            repo.session, repo._book = None, None

        GnuCashRepository.open, GnuCashRepository.close = open_, close_
        return self

    def __exit__(self, *exc):
        GnuCashRepository.open, GnuCashRepository.close = self.real_open, self.real_close
        self.repo.close()


def run(args):
    started = time.perf_counter()
    done = CliRunner().invoke(cli, args)
    return time.perf_counter() - started, done


def timings(book, out):
    print(f'\nbook of {TRANSACTIONS} transactions, {os.path.getsize(book):,} bytes on disk')

    started = time.perf_counter()
    subprocess.run([sys.executable, '-c', 'import cli.main'], check=True, capture_output=True)
    print(f'a process that starts, imports the CLI and GnuCash, and exits: '
          f'{time.perf_counter() - started:.2f} s')
    for _ in range(3):
        started = time.perf_counter()
        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.READ_ONLY)
        opened = time.perf_counter() - started
        repo.close()
        print(f'open read-only and close, alone: {opened:.2f} s')

    print('\n1. each command in a process of its own')
    total = 0.0
    for command in COMMANDS:
        started = time.perf_counter()
        done = subprocess.run([sys.executable, '-m', 'cli.main'] + with_book(command, book, out),
                              capture_output=True)
        took = time.perf_counter() - started
        total += took
        if out.exists():
            out.unlink()
        print(f'   {took:6.2f} s  exit {done.returncode}  {" ".join(command)}')
    print(f'   {total:6.2f} s  in all')

    # The first report a process runs loads GnuCash's report system, so the
    # commands are run once before either way is timed, and both are timed warm.
    for command in COMMANDS:
        _, done = run(with_book(command, book, out))
        what_it_wrote(done, out)

    print('\n2. timing baseline only: each command in this process, opening the book itself')
    alone, total = {}, 0.0
    for command in COMMANDS:
        took, done = run(with_book(command, book, out))
        total += took
        alone[tuple(command)] = what_it_wrote(done, out)
        print(f'   {took:6.2f} s  exit {done.exit_code}  {" ".join(command)}')
    print(f'   {total:6.2f} s  in all')

    print('\n3. the batch: every command against one book opened once')
    started = time.perf_counter()
    with OneOpenBook(book) as shared:
        print(f'   {time.perf_counter() - started:6.2f} s  the one open')
        for command in COMMANDS:
            took, done = run(with_book(command, book, out))
            same = what_it_wrote(done, out) == alone[tuple(command)]
            print(f'   {took:6.2f} s  exit {done.exit_code}  same as alone: {same}  {" ".join(command)}')
    print(f'   {time.perf_counter() - started:6.2f} s  in all, the open and close included; '
          f'{shared.opens} opens not made')

    print('\n4. `gnucash-plaintext batch`, in a process of its own, as a person runs it')
    listed = out.parent / 'batch.txt'
    written = out.parent / 'batch-out'
    written.mkdir(exist_ok=True)
    listed.write_text(''.join(
        f'{" ".join(word for word in command if word != "{out}")}\n{written}/{number}.txt\n'
        for number, command in enumerate(COMMANDS)))
    started = time.perf_counter()
    done = subprocess.run([sys.executable, '-m', 'cli.main', 'batch', str(book), str(listed)],
                          capture_output=True, text=True)
    print(f'   {time.perf_counter() - started:6.2f} s  exit {done.returncode}')
    for line in done.stdout.splitlines():
        print(f'   {line}')
    for number, command in enumerate(COMMANDS):
        # What `export` printed alone is its progress, then the ledger it wrote;
        # the batch's file is the ledger.
        text = (written / f'{number}.txt').read_text()
        same = (alone[tuple(command)].endswith(text) if command[0] == 'export'
                else text == alone[tuple(command)])
        print(f'   same as alone: {same}  {" ".join(command)}')


def what_a_rates_file_leaves_behind(directory):
    print('\nwhether a rates file one command reads reaches the next')
    book = directory / 'usd.gnucash'
    for number, step in enumerate((
            'acmu_1_opens_with_1000_usd_that_cost_1298_80_cad_on_2020_01_01',
            'acmu_2_invoices_abc_1000_usd_at_1_2732_cad_per_usd_and_abc_europe_1000_eur_at_1_5608_cad_per_eur_'
            'and_is_paid_in_full')):
        args = ['import', str(book), str(FIXTURES / f'{step}.txt'), '--include-business-objects']
        if number == 0:
            args.insert(1, '--new')
        else:
            time.sleep(1.1)  # two saves in one second collide on GnuCash's backup file name
        done = CliRunner().invoke(cli, args)
        assert done.exit_code == 0, done.output
    rates = directory / 'rates.yaml'
    rates.write_text('USD/CAD:\n  2021-12-31: 2.00\nEUR/CAD:\n  2021-12-31: 3.00\n')
    plain = ['balance-sheet', str(book), '--as-of', '2021-12-31']
    with_rates = plain + ['--fx-rates', str(rates)]

    _, alone = run(plain)
    _, alone_with_rates = run(with_rates)
    with OneOpenBook(book):
        _, first = run(with_rates)
        _, after = run(plain)
    _, alone_afterwards = run(plain)
    total = [line for line in alone.output.splitlines() if 'total_assets' in line]
    print(f'   alone, no rates file:              {total}')
    print(f'   alone, with the rates file:        '
          f'{[line for line in alone_with_rates.output.splitlines() if "total_assets" in line]}')
    print(f'   shared, with the rates file:       '
          f'{[line for line in first.output.splitlines() if "total_assets" in line]}'
          f'  same as alone: {first.output == alone_with_rates.output}')
    print(f'   shared, next, no rates file:       '
          f'{[line for line in after.output.splitlines() if "total_assets" in line]}'
          f'  same as alone: {after.output == alone.output}')
    print(f'   alone again, the book on disk:     same as before: {alone_afterwards.output == alone.output}')


def main():
    directory = Path(tempfile.mkdtemp())
    book = directory / 'book.gnucash'
    started = time.perf_counter()
    build_book(str(book), TRANSACTIONS)
    print(f'built in {time.perf_counter() - started:.1f} s')
    timings(book, directory / 'out.txt')
    what_a_rates_file_leaves_behind(directory)


if __name__ == '__main__':
    main()
