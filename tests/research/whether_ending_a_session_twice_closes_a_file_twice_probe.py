"""Whether `session.end()` then `session.destroy()` closes the book's lock file twice.

A book opened for writing holds `<book>.LCK` open. If `destroy()` ends the
session again and the backend closes that file descriptor a second time, the
second close lands on whatever the process opened in between under the same
number — a file of the caller's, closed from under it.

Three rounds, each on a book opened through `GnuCashRepository`:

- `end()`, then a file opened (it takes the lowest free number, which is the
  lock file's), then `destroy()`: is that file still open afterwards?
- `destroy()` alone: is the lock file closed and `.LCK` removed, and can the
  book be opened again at once?
- `end()` alone, for comparison: the same questions.

Measured on all eleven builds, 2026-09-14:

| GnuCash | `end()`, a file opened, `destroy()` | `destroy()` alone |
|---|---|---|
| 3.4, 3.8, 4.4 | the file is closed from under the process: `[Errno 9] Bad file descriptor` | lock file closed, `.LCK` removed, the book opens again at once |
| 4.8, 4.13, 5.5, 5.10, 5.13, 5.14, 5.15, 5.16 | the file stays open | the same |

Traced with `strace -f` on 3.8: `end()` closes the lock file once, and
`destroy()` alone closes it once; `end()` then `destroy()` closes it twice, the
second close refused with EBADF when nothing took the number in between.

Run:

    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp/home \
        -e PYTHONPATH=/workspace -v "$PWD:/workspace" -w /workspace \
        gnucash-dev:<tag> python3 tests/research/whether_ending_a_session_twice_closes_a_file_twice_probe.py
"""

import contextlib
import os
import sys
import tempfile

import gnucash

from repositories.gnucash_repository import GnuCashRepository, SessionMode


def open_fds():
    held = {}
    for entry in os.listdir('/proc/self/fd'):
        with contextlib.suppress(OSError):
            held[int(entry)] = os.readlink(f'/proc/self/fd/{entry}')
    return held


def lock_fd(book):
    for fd, target in open_fds().items():
        if target.endswith(os.path.basename(book) + '.LCK'):
            return fd
    return None


def opened(book):
    repo = GnuCashRepository(book)
    repo.open(SessionMode.NORMAL)
    return repo, repo.session


def say(text):
    print(text)
    sys.stdout.flush()


def main():
    say(f'GnuCash {gnucash.gnucash_core_c.gnc_version() if hasattr(gnucash.gnucash_core_c, "gnc_version") else "?"}')
    work = tempfile.mkdtemp()
    book = os.path.join(work, 'book.gnucash')
    repo = GnuCashRepository(book)
    repo.open(SessionMode.NEW)
    # A book holding nothing is not written at all (Q-041, table 1).
    account = gnucash.Account(repo.book)
    account.BeginEdit()
    account.SetName('Bank')
    account.SetType(2)
    account.SetCommodity(repo.book.get_table().lookup('CURRENCY', 'CAD'))
    repo.book.get_root_account().append_child(account)
    account.CommitEdit()
    repo.save()
    repo.close()
    lck = book + '.LCK'

    say('round 1: end(), a file opened, destroy()')
    repo, session = opened(book)
    fd = lock_fd(book)
    say(f'  lock fd while open: {fd}')
    session.end()
    say(f'  after end(): lock fd still open: {lock_fd(book) is not None}, .LCK exists: {os.path.exists(lck)}')
    mine = os.open(os.path.join(work, 'a-file-of-mine.txt'), os.O_CREAT | os.O_RDWR)
    say(f'  a file of mine opened as fd {mine} (the lock file\'s number: {mine == fd})')
    sys.stderr.flush()
    session.destroy()
    sys.stderr.flush()
    try:
        os.fstat(mine)
        say('  after destroy(): my file is still open')
        os.close(mine)
    except OSError as err:
        say(f'  after destroy(): my file was closed from under me: {err}')
    repo.session = None

    say('round 2: destroy() alone')
    repo, session = opened(book)
    fd = lock_fd(book)
    say(f'  lock fd while open: {fd}')
    session.destroy()
    say(f'  after destroy(): lock fd still open: {lock_fd(book) is not None}, .LCK exists: {os.path.exists(lck)}')
    repo.session = None
    try:
        again, _ = opened(book)
        say('  opened again at once: yes')
        again.close()
    except Exception as err:  # noqa: BLE001 — the probe prints whatever the open raises
        say(f'  opened again at once: no — {err}')

    say('round 3: end() alone')
    repo, session = opened(book)
    session.end()
    say(f'  after end(): lock fd still open: {lock_fd(book) is not None}, .LCK exists: {os.path.exists(lck)}')
    session.destroy()
    repo.session = None


if __name__ == '__main__':
    main()
