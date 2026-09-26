"""An empty copy of a company field, left by an earlier release, changes no option and says nothing.

Before `name` was a field of the `company` block it was an ordinary custom
book key, so a book written then can hold `"name": ""` in its custom metadata.
Measured on 5.10, with a `company` block that changes only the phone:

- **beside a Company Name option,** the copy is dropped, because the option
  is the book's answer once it has one. A note is printed where a dropped copy
  held a value. This one held nothing, so nothing is said;
- **with no Company Name option,** the copy has no value to carry to the
  option, so nothing is written to it and nothing is said.
"""

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import (
    get_book_custom_metadata,
    get_book_string_option,
    merge_book_custom_metadata,
)
from repositories.gnucash_repository import GnuCashRepository, SessionMode

NAMED = 'tests/fixtures/a_company_named_acme_with_a_phone.txt'
NEW_PHONE = 'tests/fixtures/a_company_stating_only_a_new_phone.txt'
ONLY_A_PHONE = 'tests/fixtures/a_company_with_only_a_phone.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _a_book_an_earlier_release_left(tmp_path, ledger):
    """The book `ledger` makes, holding `"name": ""` beside another custom key."""
    book = tmp_path / 'book.gnucash'
    made = _run('import', '--new', book, ledger, '--include-business-objects')
    assert made.exit_code == 0, made.output
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.NORMAL)
    try:
        merge_book_custom_metadata(repo.book, {'name': '', 'department': 'east'})
        repo.save()
    finally:
        repo.close()
    return book


def test_it_is_dropped_and_the_option_and_other_keys_stay(tmp_path):
    book = _a_book_an_earlier_release_left(tmp_path, NAMED)

    result = _run('import', book, NEW_PHONE, '--include-business-objects')

    assert result.exit_code == 0, result.output
    assert 'dropped' not in result.output, result.output
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        assert get_book_custom_metadata(repo.book) == {'department': 'east'}
        assert get_book_string_option(repo.book, 'Business', 'Company Name') == 'Acme Ltd'
    finally:
        repo.close()


def test_with_no_company_name_nothing_is_written_to_the_option(tmp_path):
    """An empty copy has no value to carry to an option the book has not got,
    so the option stays unset and nothing is said about it."""
    book = _a_book_an_earlier_release_left(tmp_path, ONLY_A_PHONE)

    result = _run('import', book, NEW_PHONE, '--include-business-objects')

    assert result.exit_code == 0, result.output
    assert 'dropped' not in result.output, result.output
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        assert not get_book_string_option(repo.book, 'Business', 'Company Name')
        assert get_book_string_option(repo.book, 'Business', 'Company Phone Number') == \
            '555-0199'
    finally:
        repo.close()
