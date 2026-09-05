"""Probe: the company name on a page drawn under an ASCII locale.

The customer's Japanese name reaches the page on GnuCash 3.4 and the company's
`Éditions Cliché Inc.` does not. The two come from different places — the
customer is a business object, the company name is a book option, and on 3.4
that option is written as a plain slot because
`qof_book_set_string_option` cannot reach a nested path there.

This says whether the name arrives mangled or does not arrive at all, and what
the book holds for it either way.

    ./scripts/test.sh debian10 tests/research/what_becomes_of_an_accented_company_name_probe.py
    ./scripts/test.sh latest   tests/research/what_becomes_of_an_accented_company_name_probe.py
"""

import re

from tests.integration.test_a_printed_page_keeps_its_characters import (
    _book_with_both_pages,
    _run_under_an_ascii_locale,
)

WANTED = 'Éditions Cliché Inc.'


def test_what_reaches_the_page(tmp_path, capsys):
    book = _book_with_both_pages(tmp_path)
    out = tmp_path / 'inv.html'
    done = _run_under_an_ascii_locale([
        'print-invoice', str(book), 'INV-UNICODE-001', '--format', 'html',
        '--output', str(out)])

    written = out.read_bytes() if out.exists() else b''

    from infrastructure.gnucash.kvp import get_book_string_option
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(book))
    repo.open()
    try:
        stored = get_book_string_option(repo.book, 'Business', 'Company Name')
    finally:
        repo.close()

    near = [m.group(0) for m in re.finditer(rb'.{0,12}ditions.{0,14}', written)]

    with capsys.disabled():
        print()
        print(f'exit code          {done.returncode}')
        print(f'stored in the book {stored!r}')
        print(f'wanted bytes in    {WANTED.encode() in written}')
        print(f'"ditions" anywhere {b"ditions" in written}')
        print(f'around it          {near[:3]}')
        print(f'page bytes         {len(written)}')
