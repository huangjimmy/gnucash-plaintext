"""A company block is exported when the slot for its custom keys holds no JSON.

A company block's own keys live in the book's Business options, and any other
key a block gave is kept as one JSON object in one slot. A book whose slot holds
something else, from a hand edit or another tool, has no custom keys to read
there, so the export writes the company block from the options and goes on.
"""

from click.testing import CliRunner

from infrastructure.gnucash.kvp import (
    COMPANY_CUSTOM_SECTION,
    COMPANY_CUSTOM_SLOT,
    write_book_string_option,
)
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from tests.conftest import _run

FIXTURE = 'tests/fixtures/a_company_with_a_six_line_address.txt'


def test_the_company_block_is_written(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), FIXTURE, '--include-business-objects')
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        write_book_string_option(repo.book, COMPANY_CUSTOM_SECTION, COMPANY_CUSTOM_SLOT,
                                 'not json')
        repo.save()
    finally:
        repo.close()

    out = tmp_path / 'out.txt'
    exported = _run(runner, 'export', str(book), str(out), '--include-business-objects')

    assert exported.exit_code == 0, exported.output
    text = out.read_text()
    assert 'name: "Example Co"' in text, text
    assert 'addr[5]: "Attn: Accounts Payable"' in text, text
