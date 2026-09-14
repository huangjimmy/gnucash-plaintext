"""Whether closing a book opened read-only closes a file the process opened, on the descriptor a locked book used before it.

A book opened for writing holds `<book>.LCK` open, on some descriptor N. A book
opened read-only takes no lock. If the backend of a read-only book still closes
its lock descriptor when the session ends, and that field holds whatever the
previous backend left at the same address, it closes N: by then N may be a file
of the process's own.

Each round, five times over:

1. open the book for writing, note its lock descriptor, and close the book;
2. open a file (it takes the lowest free number, which is the lock's);
3. open the book read-only and close it;
4. ask whether the file is still open.

Once with `GnuCashRepository.close` as it is (`destroy()`), and once with
`session.end()` alone.

Measured on all eleven builds, 2026-09-14, before `GnuCashRepository.open`
opened a book to read as a private copy on these builds:

| GnuCash | `destroy()` | `end()` alone |
|---|---|---|
| 3.4, 3.8, 4.4 | the file closed in 5 of 5 rounds | 5 of 5 |
| 4.8, 4.13, 5.5, 5.10, 5.13, 5.14, 5.15, 5.16 | 0 of 5 | 0 of 5 |

Run now, it measures the repository with that copy, and the file stays open
(CLAUDE.md finding 27).

Run:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
        -e PYTHONPATH=/workspace -v "$PWD:/workspace" -w /workspace \
        gnucash-dev:<tag> python3 tests/research/whether_closing_a_read_only_book_closes_a_file_it_never_opened_probe.py
"""

import contextlib
import os
import tempfile

import gnucash

from repositories.gnucash_repository import GnuCashRepository, SessionMode

ROUNDS = 5


def lock_fd(book):
    for entry in os.listdir('/proc/self/fd'):
        with contextlib.suppress(OSError):
            if os.readlink(f'/proc/self/fd/{entry}').endswith(os.path.basename(book) + '.LCK'):
                return int(entry)
    return None


def build(book):
    repo = GnuCashRepository(book)
    repo.open(SessionMode.NEW)
    account = gnucash.Account(repo.book)
    account.BeginEdit()
    account.SetName('Bank')
    account.SetType(2)
    account.SetCommodity(repo.book.get_table().lookup('CURRENCY', 'CAD'))
    repo.book.get_root_account().append_child(account)
    account.CommitEdit()
    repo.save()
    repo.close()


def a_round(book, work, end_only):
    writer = GnuCashRepository(book)
    writer.open(SessionMode.NORMAL)
    lock = lock_fd(book)
    writer.close()

    mine = os.open(os.path.join(work, 'a-file-of-mine.txt'), os.O_CREAT | os.O_RDWR)

    reader = GnuCashRepository(book)
    reader.open(SessionMode.READ_ONLY)
    if end_only:
        session = reader.session
        reader.session = None
        reader._book = None
        session.end()
    else:
        reader.close()

    try:
        os.fstat(mine)
        closed = False
        os.close(mine)
    except OSError:
        closed = True
    return lock, mine, closed


def main():
    work = tempfile.mkdtemp()
    book = os.path.join(work, 'book.gnucash')
    build(book)
    for end_only, called in ((False, 'close(), which calls destroy()'), (True, 'session.end() alone')):
        results = [a_round(book, work, end_only) for _ in range(ROUNDS)]
        closed = sum(1 for _lock, _mine, was_closed in results if was_closed)
        detail = ', '.join(f'lock {lock} mine {mine} {"CLOSED" if was_closed else "open"}'
                           for lock, mine, was_closed in results)
        print(f'{called}: my file closed from under me in {closed} of {ROUNDS} rounds ({detail})',
              flush=True)


if __name__ == '__main__':
    main()
