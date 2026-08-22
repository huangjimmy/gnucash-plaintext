"""A payment block whose `txn_guid:` is mistyped must not pay the same money twice.

A guid that resolves to nothing has two readings, and the block cannot tell
them apart on its own: an invoice being rebuilt into a fresh book, where the
bank transaction genuinely is not there yet, and a retarget against the book
that holds it, where the guid is simply wrong. The first must be allowed —
`print-invoice` names the transactions so the same book relinks rather than
paying twice, and a printed file has to be readable elsewhere. The second is a
typo, and creating a payment for it enters money that already moved.

What separates them is the book: if the block's own date, amount and account
describe a transaction the book already has, the money is there and the guid
is wrong. Reconstruction into a fresh book matches nothing, so it is
unaffected.

The cost of getting this wrong is quiet: a second payment for one movement,
the invoice over-settled, the bank double-counted, and a run that exits 0.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')


def _transaction_count(book):
    """Every transaction in the book, however it was written."""
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
def book_holding_the_bank_transaction(tmp_path):
    """A book with the credit, and the bank transaction a retarget names."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    setup = tmp_path / 'setup.txt'
    setup.write_text(
        (FIXTURES / 'credit_on_an_account_kept_finer_than_the_cent.txt').read_text())
    assert runner.invoke(cli, ['import', '--new', str(book), str(setup),
                              '--include-business-objects']).exit_code == 0

    bank = tmp_path / 'bank.txt'
    bank.write_text((FIXTURES / 'finer_account_retarget_bank.txt').read_text())
    assert runner.invoke(cli, ['import', str(book), str(bank)]).exit_code == 0
    return book


def _retarget_text_with_guid(guid: str) -> str:
    """The retarget block, naming `guid` and declaring its residual."""
    text = (FIXTURES / 'finer_account_retarget_invoice.txt').read_text()
    return (text.replace('TXN_GUID', guid)
                .replace('PREPAY_LINE', '\t\tprepayment: 20.000'))


class TestAGuidThatNamesNothingAgainstABookThatHasTheMoney:
    """The typo case. The money is in the book; the guid is one character out."""

    def _import_with_a_wrong_guid(self, book, tmp_path):
        ledger = tmp_path / 'mistyped.txt'
        ledger.write_text(
            _retarget_text_with_guid('deadbeefdeadbeefdeadbeefdeadbeef'))
        return CliRunner().invoke(cli, [
            'import', str(book), str(ledger), '--include-business-objects'])

    def test_the_run_does_not_report_success(
            self, book_holding_the_bank_transaction, tmp_path):
        """A run that entered money twice must not exit 0."""
        result = self._import_with_a_wrong_guid(
            book_holding_the_bank_transaction, tmp_path)

        assert result.exit_code != 0, result.output

    def test_the_bank_transaction_is_not_duplicated(
            self, book_holding_the_bank_transaction, tmp_path):
        """One movement of money, one transaction — whatever the file says."""
        book = book_holding_the_bank_transaction
        before = _transaction_count(book)

        self._import_with_a_wrong_guid(book, tmp_path)

        assert _transaction_count(book) == before
