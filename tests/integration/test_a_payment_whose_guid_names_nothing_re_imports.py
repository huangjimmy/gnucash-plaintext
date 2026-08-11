"""A file whose payment guid names nothing must read back a second time.

`print-invoice` and `print-bill` write `txn_guid:` / `txn_split_guid:` naming
the *source* book's transactions. Read into a different book those resolve to
nothing by construction, and the payment is created from the block instead —
which is what makes a printed document readable anywhere.

The second import is the one that matters. The payment now in the book carries
a guid GnuCash minted; the file still names the source book's. If the
comparison that decides "unchanged" treats an unresolvable guid as
authoritative, the document reads as out of date on every run: it is unposted,
its posting destroyed and its payment orphaned, and the rebuild then meets the
orphan it just made and refuses — leaving the book untouched and the command
unable to succeed ever again.

So a file like this has to import twice and report the second run as changing
nothing.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = str(Path('tests/fixtures/a_payment_named_with_account.txt'))


def _transaction_count(book):
    from gnucash import Query

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        count = len(list(query.run()))
        query.destroy()
        return count
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), LEDGER, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


class TestTheSecondImport:
    def test_it_succeeds(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), LEDGER, '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_it_does_not_enter_the_payment_again(self, book):
        before = _transaction_count(book)

        CliRunner().invoke(cli, [
            'import', str(book), LEDGER, '--include-business-objects'])

        assert _transaction_count(book) == before


class TestAndAThird:
    def test_the_file_keeps_reading(self, book):
        """A document that can be read once and never again is worse than one
        that cannot be read at all: the failure arrives later, on a book that
        has already been built from it."""
        runner = CliRunner()
        runner.invoke(cli, ['import', str(book), LEDGER,
                            '--include-business-objects'])

        result = runner.invoke(cli, ['import', str(book), LEDGER,
                                     '--include-business-objects'])

        assert result.exit_code == 0, result.output
