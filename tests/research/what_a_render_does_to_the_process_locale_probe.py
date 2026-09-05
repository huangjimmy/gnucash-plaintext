"""Probe: does drawing a page change the locale the process is left in?

The render sets `C.UTF-8` in Guile, because GnuCash 3.4 otherwise turns a book
option's characters into `?`. A locale is process-wide, so the question is
what the next thing in the process sees — and whether Python can even observe
what Guile set, which decides whether a test can assert on it at all.

    ./scripts/test.sh debian10 tests/research/what_a_render_does_to_the_process_locale_probe.py
    ./scripts/test.sh latest   tests/research/what_a_render_does_to_the_process_locale_probe.py
"""

import ctypes
import locale

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_a_printed_page_keeps_its_characters import (
    _book_with_both_pages,
)


def _what_c_says():
    """`setlocale(LC_ALL, NULL)` straight from libc, not through Python."""
    libc = ctypes.CDLL(None)
    libc.setlocale.restype = ctypes.c_char_p
    libc.setlocale.argtypes = [ctypes.c_int, ctypes.c_char_p]
    answer = libc.setlocale(6, None)          # 6 == LC_ALL on glibc
    return answer.decode() if answer else None


def test_what_the_process_is_left_with(tmp_path, capsys):
    book = _book_with_both_pages(tmp_path)

    python_before = locale.setlocale(locale.LC_ALL)
    c_before = _what_c_says()

    out = tmp_path / 'inv.html'
    drawn = CliRunner().invoke(cli, [
        'print-invoice', str(book), 'INV-UNICODE-001', '--format', 'html',
        '--output', str(out)])

    python_after = locale.setlocale(locale.LC_ALL)
    c_after = _what_c_says()

    with capsys.disabled():
        print()
        print(f'exit code       {drawn.exit_code}')
        print(f'python before   {python_before}')
        print(f'python after    {python_after}')
        print(f'libc before     {c_before}')
        print(f'libc after      {c_after}')
        print(f'python changed  {python_before != python_after}')
        print(f'libc changed    {c_before != c_after}')
