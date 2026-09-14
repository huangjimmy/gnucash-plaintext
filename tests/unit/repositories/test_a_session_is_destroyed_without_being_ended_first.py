"""A GnuCash session is destroyed without being ended first, so closing a book closes only the book's own files.

`session.destroy()` ends the session itself. On GnuCash 3.4, 3.8 and 4.4,
ending a session that `end()` has already ended closes the book's lock file a
second time, by its number. If anything in the process opened a file between
the two calls, that file took the free number, and the second close closes it.
GnuCash runs threads of its own, such as the one that writes a book, so the
file need not be one Python opened.

Measured on all eleven builds by
`tests/research/whether_ending_a_session_twice_closes_a_file_twice_probe.py`:

- `end()`, a file opened, then `destroy()`: the file was closed from under the
  process on 3.4, 3.8 and 4.4, and stayed open on every later build;
- `destroy()` alone: the lock file closed once, `.LCK` removed, and the book
  free to open again at once, on every build.

Under `strace` on 3.8, every book `GnuCashRepository.close` closed showed
`close(lock) = 0` and then `close(lock) = -1 EBADF`; with `destroy()` alone,
none did. The `[Errno 9] Bad file descriptor` the suite met on Ubuntu 20.04
came from another close, of a lock a session never took (CLAUDE.md finding
27, `test_closing_a_book_closes_no_file_but_its_own.py`).

Searched over the same files as `test_a_book_is_opened_only_through_the_repository.py`.
"""

import ast

from tests.unit.repositories.test_a_book_is_opened_only_through_the_repository import (
    _searched_files,
)


def _spelled(node):
    if isinstance(node, ast.Name):
        return node.id.lower()
    if isinstance(node, ast.Attribute):
        return node.attr.lower()
    return ''


def test_no_session_is_ended_before_it_is_destroyed():
    calls = []
    for relative, path in _searched_files():
        for node in ast.walk(ast.parse(path.read_text())):
            ends_a_session = (isinstance(node, ast.Call)
                              and isinstance(node.func, ast.Attribute)
                              and node.func.attr == 'end'
                              and 'session' in _spelled(node.func.value))
            if ends_a_session:
                calls.append(f'{relative}:{node.lineno}')
    assert calls == [], (
        f'{len(calls)} GnuCash session(s) ended by end() — call destroy() alone, which '
        f'ends the session once; end() then destroy() closes the lock file twice on '
        f'GnuCash 3.4, 3.8 and 4.4:\n  ' + '\n  '.join(calls))
