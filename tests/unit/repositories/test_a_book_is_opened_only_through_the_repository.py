"""A GnuCash session is created only by `GnuCashRepository`, so every book opened is freed.

`GnuCashRepository.close` destroys the session, which ends it and frees the
book. A session that is only ended keeps its whole book in memory until the process exits, and one
pytest process runs the whole suite: a test that created `Session(...)` itself
and only ended it kept that book for the rest of the run. About 680 books a run
were kept that way after the repository itself was fixed (CLAUDE.md finding 26;
docs/issues/Q-041-a-price-cannot-be-recorded-for-a-past-date-or-kept-through-export-and-import.md).

Searched over the application and every file pytest collects. Files in
tests/research whose names do not start with `test_` are left out: each is a
probe run as a script of its own, measuring GnuCash itself, and exits when it
is done.
"""

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

THE_REPOSITORY = 'repositories/gnucash_repository.py'

SEARCHED = ['cli', 'services', 'use_cases', 'infrastructure', 'repositories', 'tests']


def _searched_files():
    for root in SEARCHED:
        for path in sorted((REPO_ROOT / root).rglob('*.py')):
            relative = path.relative_to(REPO_ROOT).as_posix()
            if relative.startswith('tests/research/') and not path.name.startswith('test_'):
                continue
            yield relative, path


def test_no_session_is_created_outside_the_repository():
    calls = []
    for relative, path in _searched_files():
        if relative == THE_REPOSITORY:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            creates_a_session = ((isinstance(node.func, ast.Name) and node.func.id == 'Session')
                                 or (isinstance(node.func, ast.Attribute)
                                     and node.func.attr == 'Session'))
            if creates_a_session:
                calls.append(f'{relative}:{node.lineno}')
    assert calls == [], (
        f'{len(calls)} GnuCash session(s) created outside GnuCashRepository — open '
        f'the book with GnuCashRepository(path).open(...) and close it with '
        f'close(), which frees the book:\n  ' + '\n  '.join(calls))
