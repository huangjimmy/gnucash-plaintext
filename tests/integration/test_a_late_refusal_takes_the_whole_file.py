"""A document refused late discards the transactions that imported before it.

`--include-business-objects` reads the file in one pass and saves the book
once, at the end. The invoice and bill pass runs after the standalone
transactions have been built in memory, so a document refused there takes them
with it — the save is never reached.

That is the documented all-or-nothing guarantee working: a file lands in full
or not at all, and half a ledger on disk is the outcome it exists to prevent.
It is worth pinning because it is not what the error message says. The run
reports one invoice's problem, and the reader is not told that the fifty
transactions above it are also not in the book.

Pinned rather than changed: a partial save has to be a decision, and the notes
record this one. What a test adds is that the day somebody reorders the save,
they find out here rather than from a book that quietly kept half a file.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'payment_roundtrip_accounts.txt')
LEDGER = str(FIXTURES / 'a_transaction_then_a_refused_invoice.txt')


def _has_the_transaction(book) -> bool:
    from gnucash import Query, Transaction

    from repositories.gnucash_repository import GnuCashRepository, SessionMode

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        found = any(Transaction(instance=raw).GetDescription() == 'Stationery'
                    for raw in query.run())
        query.destroy()
        return found
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    gnc = tmp_path / 'book.gnucash'
    assert CliRunner().invoke(cli, ['import', '--new', str(gnc),
                                    ACCOUNTS]).exit_code == 0
    return gnc


class TestTheTransactionAboveIt:
    def test_the_run_is_refused(self, book):
        result = CliRunner().invoke(cli, ['import', str(book), LEDGER,
                                          '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'A Table This Book Has Never Heard Of' in result.output, \
            result.output

    def test_the_transaction_is_not_in_the_book_either(self, book):
        """All or nothing: the file did not land, so none of it did."""
        CliRunner().invoke(cli, ['import', str(book), LEDGER,
                                 '--include-business-objects'])

        assert not _has_the_transaction(book)

    def test_without_the_flag_the_transaction_lands(self, book):
        """The document is not read at all, so nothing refuses it."""
        result = CliRunner().invoke(cli, ['import', str(book), LEDGER])

        assert result.exit_code == 0, result.output
        assert _has_the_transaction(book)
