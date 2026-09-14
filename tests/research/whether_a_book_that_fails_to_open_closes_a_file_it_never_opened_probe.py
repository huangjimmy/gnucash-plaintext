"""Whether a book that fails to open closes a file the process opened, on the descriptor a locked book used before it.

GnuCash's Python `Session.__init__` ends and destroys a session whose open
failed. If the backend then closes a lock descriptor it never took, holding the
value the previous backend left at that address, it closes a file of the
process's own.

Each case, five times over: open a book for writing and close it, open a file
(taking the lock's freed number), try the failing open through
`GnuCashRepository`, and ask whether the file is still open.

- a missing file, read-only;
- a missing file, for writing;
- a book another session holds the lock of, for writing;
- a file that is not a book, read-only;
- a file that is not a book, for writing;
- a book in a directory the process cannot write, for writing;
- a directory, read-only and for writing;
- a new book where a book already is, in a directory that does not exist, and
  in a directory the process cannot write.

Measured on 3.4, 3.8 and 4.4, 2026-09-14, as an unprivileged user, before
`GnuCashRepository.open` refused these cases itself:

| case | 3.4 | 3.8 | 4.4 |
|---|---|---|---|
| a missing file, read-only or for writing | the file closed 5 of 5 | 4 or 5 of 5 | 0 |
| a locked book, for writing | 0 | 4 or 5 of 5 | 0 |
| a new book where a book already is | 5 of 5 | 5 of 5 | 0 |
| a new book in a directory that does not exist | 5 of 5 | 4 of 5 | 0 |
| a file that is not a book; a directory; an unwritable directory | 0 | 0 | 0 |

Run now, it measures the repository with those refusals, and the file stays
open (CLAUDE.md finding 27).

Run:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
        -e PYTHONPATH=/workspace -v "$PWD:/workspace" -w /workspace \
        gnucash-dev:<tag> python3 tests/research/whether_a_book_that_fails_to_open_closes_a_file_it_never_opened_probe.py
"""

import os
import tempfile

import gnucash

from repositories.gnucash_repository import BookUnavailableError, GnuCashRepository, SessionMode

ROUNDS = 5


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


def one(book, work, target, mode, holder=None):
    writer = GnuCashRepository(book)
    writer.open(SessionMode.NORMAL)
    writer.close()
    mine = os.open(os.path.join(work, 'a-file-of-mine.txt'), os.O_CREAT | os.O_RDWR)
    if holder is not None:
        holder.open(SessionMode.NORMAL)
    try:
        failing = GnuCashRepository(target)
        try:
            failing.open(mode)
            opened = 'opened'
            failing.close()
        except BookUnavailableError as refusal:
            opened = f'refused: {str(refusal)[:60]}'
    finally:
        if holder is not None:
            holder.close()
    try:
        os.fstat(mine)
        os.close(mine)
        return opened, False
    except OSError:
        return opened, True


def main():
    work = tempfile.mkdtemp()
    book = os.path.join(work, 'book.gnucash')
    build(book)
    other = os.path.join(work, 'other.gnucash')
    build(other)
    missing = os.path.join(work, 'no-such-book.gnucash')
    not_a_book = os.path.join(work, 'not-a-book.gnucash')
    with open(not_a_book, 'w', encoding='utf-8') as junk:
        junk.write('this is not a GnuCash book\n')

    shut = os.path.join(work, 'shut')
    os.mkdir(shut)
    in_shut = os.path.join(shut, 'book.gnucash')
    build(in_shut)
    os.chmod(shut, 0o555)
    if os.access(shut, os.W_OK):
        print('this process writes whatever the mode says; the unwritable directory case is not measured')

    cases = [
        ('a new book where a book already is', other, SessionMode.NEW, None),
        ('a new book in a directory that does not exist',
         os.path.join(work, 'no-such-directory', 'book.gnucash'), SessionMode.NEW, None),
        ('a new book in a directory this process cannot write',
         os.path.join(shut, 'new.gnucash'), SessionMode.NEW, None),
        ('a book in a directory this process cannot write, for writing', in_shut,
         SessionMode.NORMAL, None),
        ('a directory, read-only', work, SessionMode.READ_ONLY, None),
        ('a directory, for writing', work, SessionMode.NORMAL, None),
        ('a missing file, read-only', missing, SessionMode.READ_ONLY, None),
        ('a missing file, for writing', missing, SessionMode.NORMAL, None),
        ('a book whose lock another session holds, for writing', other, SessionMode.NORMAL,
         GnuCashRepository(other)),
        ('a file that is not a book, read-only', not_a_book, SessionMode.READ_ONLY, None),
        ('a file that is not a book, for writing', not_a_book, SessionMode.NORMAL, None),
    ]
    for called, target, mode, holder in cases:
        results = []
        for _ in range(ROUNDS):
            if holder is not None:
                holder = GnuCashRepository(target)
            results.append(one(book, work, target, mode, holder))
        closed = sum(1 for _opened, was_closed in results if was_closed)
        print(f'{called}: {results[0][0]}; my file closed from under me in {closed} of {ROUNDS}',
              flush=True)


if __name__ == '__main__':
    main()
