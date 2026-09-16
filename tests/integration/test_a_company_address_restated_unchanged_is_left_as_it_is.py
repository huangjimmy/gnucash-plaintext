"""A `company` block restating the address the book holds changes only what it changes.

The address is written to the Company Address option only where the block's
lines differ from what the option holds. A block that restates the same two
lines beside a new phone number updates the phone, and the address reads back
exactly as it was.
"""

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_book_string_option
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIRST = 'tests/fixtures/a_company_with_an_address_and_a_phone.txt'
AGAIN = 'tests/fixtures/a_company_with_the_same_address_and_a_new_phone.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def test_the_phone_changes_and_the_address_stays(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run('import', '--new', book, FIRST, '--include-business-objects')
    assert made.exit_code == 0, made.output

    result = _run('import', book, AGAIN, '--include-business-objects')

    assert result.exit_code == 0, result.output
    assert 'updated' in result.output, result.output
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        assert get_book_string_option(repo.book, 'Business', 'Company Address') == \
            '1 Main Street\nSpringfield ON'
        assert get_book_string_option(repo.book, 'Business', 'Company Phone Number') == \
            '555-0199'
    finally:
        repo.close()
