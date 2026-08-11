"""A transaction refused part-way through leaves nothing of itself behind.

The importer builds a transaction between a `BeginEdit` and a `CommitEdit`,
attaching each split as it goes, and the amount on each split is judged as it
is reached. So a figure refused on the *second* line is refused with the first
line already attached — the interesting case, and the one a fixture that puts
the bad figure first never reaches, because nothing had been attached yet.

What the book is left holding is asserted both ways: in the session that did
the import, and in the file it saved. The saved file is what a reader gets;
the open session is what the rest of the same run sees, and a half-built entry
there could be matched against as a duplicate or counted in a balance.

Every failure is collected per transaction so a bad one does not cost the good
ones beside it — which is what makes the question worth asking at all. If the
refusal simply ended the run there would be nothing left to protect.
"""

import os

import pytest
from click.testing import CliRunner
from gnucash import Query, Transaction

from cli.main import cli
from repositories.gnucash_repository import (
    GnuCashRepository,
    SessionMode,
)

LEDGER = 'tests/fixtures/amount_refused_on_a_later_split.txt'


def _transactions(book):
    query = Query()
    query.search_for('Trans')
    query.set_book(book)
    found = sorted(
        (Transaction(instance=raw).GetDescription(),
         len(Transaction(instance=raw).GetSplitList()))
        for raw in query.run())
    query.destroy()
    return found


@pytest.fixture
def imported(tmp_path):
    """The ledger imported through the CLI, and what it reported."""
    book = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    return book, result


class TestWhatItReports:
    def test_the_refusal_names_the_figure_and_the_split(self, imported):
        _book, result = imported

        assert 'Errors:       1' in result.output, result.output
        assert '18.191' in result.output, result.output
        assert "'Assets:Bank'" in result.output, result.output

    def test_the_good_transaction_beside_it_still_counts(self, imported):
        _book, result = imported

        assert 'Transactions: 1' in result.output, result.output


class TestWhatTheSavedFileHolds:
    def test_only_the_good_transaction(self, imported):
        book, _ = imported
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            assert _transactions(repo.book) == [('An ordinary lunch', 2)]
        finally:
            repo.close()

    def test_no_entry_carrying_the_first_split_alone(self, imported):
        """What a transaction abandoned mid-build would look like."""
        book, _ = imported
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            assert not [name for name, _n in _transactions(repo.book)
                        if 'tenth of a cent' in name]
        finally:
            repo.close()

    def test_the_book_is_valid(self, imported):
        book, _ = imported

        checked = CliRunner().invoke(cli, ['validate', str(book)])
        assert checked.exit_code == 0, checked.output
        assert 'Imbalance' not in checked.output, checked.output


class TestALotTheBuildHadAlreadyMade:
    """`lot_owner:` makes a lot mid-build, and the destroy has to take it too.

    A split carrying `lot_owner:` attaches to (or opens) that owner's lot
    while the transaction is still being built. If the build is then refused,
    an empty owner-attached lot left behind is indistinguishable from a
    parked credit — CLAUDE.md's own finding — so the customer would appear to
    be holding money nobody deposited.

    Measured: it does not happen. The lot goes with the transaction, and the
    good transaction beside it still lands. Pinned so a change to the guard
    cannot quietly reintroduce it, on every supported build.
    """

    LEDGER = 'tests/fixtures/lot_owner_on_a_transaction_that_is_refused.txt'

    def _imported(self, tmp_path):
        book = tmp_path / 'lot.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(book), self.LEDGER,
            '--include-business-objects'])
        assert '25.001' in result.output, result.output
        assert book.exists(), result.output
        return book, result

    def test_the_good_transaction_beside_it_still_lands(self, tmp_path):
        """Otherwise the run saves nothing and the question never arises."""
        book, _ = self._imported(tmp_path)

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            assert _transactions(repo.book) == [('An ordinary sale', 2)]
        finally:
            repo.close()

    def test_no_lot_is_left_behind(self, tmp_path):
        from gnucash import GncLot

        book, _ = self._imported(tmp_path)
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            def walk(account):
                yield account
                for child in account.get_children():
                    yield from walk(child)

            found = [(account.get_full_name(),
                      len(GncLot(instance=raw).get_split_list()))
                     for account in walk(repo.book.get_root_account())
                     for raw in account.GetLotList()]
            assert found == [], found
        finally:
            repo.close()

    def test_the_customer_is_not_holding_a_credit_nobody_paid(self, tmp_path):
        book, _ = self._imported(tmp_path)

        found = CliRunner().invoke(cli, ['find-prepayments', str(book)])
        assert found.exit_code == 0, found.output
        assert 'No pre-payment credits found' in found.output, found.output


class TestWhatTheOpenSessionHolds:
    """The same question before anything is written to disk.

    A saved file cannot show an entry whose edit was never committed, so the
    file alone would not tell whether one was built and abandoned in memory.
    The rest of the run sees the session, not the file.
    """

    def test_only_the_good_transaction_is_in_the_session(self, tmp_path):
        from use_cases.import_transactions import ImportTransactionsUseCase

        book = tmp_path / 'session.gnucash'
        # Created empty first, because the use case imports into an open book.
        assert CliRunner().invoke(cli, [
            'import', '--new', str(book),
            'tests/fixtures/account_with_finer_scu.txt']).exit_code == 0

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.NORMAL)
        try:
            result = ImportTransactionsUseCase(repo).import_from_file(LEDGER)
            assert result.error_count == 1, result.errors

            names = [name for name, _n in _transactions(repo.book)]
            assert not [name for name in names if 'tenth of a cent' in name], (
                names)
        finally:
            repo.close()
            if os.path.exists(str(book)):
                os.unlink(str(book))
