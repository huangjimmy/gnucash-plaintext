"""
Tests for ImportTransactionsUseCase with ResolutionStrategy.UPDATE

Verifies the full import_from_file() flow when UPDATE strategy is used:
- Transactions matched by GUID are updated in-place (GUID preserved)
- Transactions without a GUID in the plaintext raise ValueError immediately
- Transactions with a GUID not present in the book raise ValueError immediately
- Stable roundtrip: export → re-import with UPDATE → no phantom duplicates

These tests use real GnuCash files (no mocks), running in Docker.
"""

import os
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _open_session(path):
    from gnucash import Session
    try:
        from gnucash import SessionOpenMode
        return Session(f'xml://{path}', SessionOpenMode.SESSION_NORMAL_OPEN)
    except ImportError:
        return Session(f'xml://{path}')


@pytest.fixture
def gnucash_with_exportable_transaction():
    """
    GnuCash file with one CAD transaction.  Returns (gnucash_path, guid).

    The transaction is:
      2024-05-10  Lunch
        Expenses:Dining      25.00 CAD
        Assets:Bank:Checking -25.00 CAD
    """
    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)

    try:
        import gnucash
        from gnucash import Account, GncNumeric, Session, Split, Transaction

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
        except ImportError:
            session = Session(f'xml://{path}', is_new=True)

        book = session.book
        root = book.get_root_account()
        commod_table = book.get_table()
        cad = commod_table.lookup('CURRENCY', 'CAD')

        assets = Account(book)
        assets.SetName('Assets')
        assets.SetType(gnucash.ACCT_TYPE_ASSET)
        assets.SetCommodity(cad)
        root.append_child(assets)

        bank = Account(book)
        bank.SetName('Bank')
        bank.SetType(gnucash.ACCT_TYPE_BANK)
        bank.SetCommodity(cad)
        assets.append_child(bank)

        checking = Account(book)
        checking.SetName('Checking')
        checking.SetType(gnucash.ACCT_TYPE_BANK)
        checking.SetCommodity(cad)
        bank.append_child(checking)

        expenses = Account(book)
        expenses.SetName('Expenses')
        expenses.SetType(gnucash.ACCT_TYPE_EXPENSE)
        expenses.SetCommodity(cad)
        root.append_child(expenses)

        groceries = Account(book)
        groceries.SetName('Groceries')
        groceries.SetType(gnucash.ACCT_TYPE_EXPENSE)
        groceries.SetCommodity(cad)
        expenses.append_child(groceries)

        dining = Account(book)
        dining.SetName('Dining')
        dining.SetType(gnucash.ACCT_TYPE_EXPENSE)
        dining.SetCommodity(cad)
        expenses.append_child(dining)

        tx = Transaction(book)
        tx.BeginEdit()
        tx.SetCurrency(cad)
        tx.SetDate(10, 5, 2024)
        tx.SetDescription('Lunch')

        s1 = Split(book)
        s1.SetParent(tx)
        s1.SetAccount(dining)
        s1.SetValue(GncNumeric(2500, 100))

        s2 = Split(book)
        s2.SetParent(tx)
        s2.SetAccount(checking)
        s2.SetValue(GncNumeric(-2500, 100))

        tx.CommitEdit()
        guid = tx.GetGUID().to_string()
        session.save()
        session.end()

        yield path, guid

    finally:
        if os.path.exists(path):
            os.unlink(path)
        lock = path + '.LCK'
        if os.path.exists(lock):
            os.unlink(lock)


def _write_plaintext_file(content: str) -> str:
    """Write *content* to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix='.txt')
    with os.fdopen(fd, 'w') as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestImportUpdateByGuid:
    def test_update_changes_description(self, gnucash_with_exportable_transaction):
        """
        Plaintext with GUID + changed description → description updated, GUID preserved.
        """
        from gnucash import Query, Transaction

        from repositories.gnucash_repository import GnuCashRepository
        from services.conflict_resolver import ResolutionStrategy
        from use_cases.import_transactions import ImportTransactionsUseCase

        path, guid = gnucash_with_exportable_transaction

        plaintext = (
            '2024-05-10 commodity CAD\n'
            '\tmnemonic: "CAD"\n'
            '\tfullname: "Canadian Dollar"\n'
            '\tnamespace: "CURRENCY"\n'
            '\tfraction: 100\n'
            f'2024-05-10 * "Updated lunch description"\n'
            f'\tguid: "{guid}"\n'
            '\tExpenses:Dining 25.00 CAD\n'
            '\tAssets:Bank:Checking -25.00 CAD\n'
        )
        pt_path = _write_plaintext_file(plaintext)
        try:
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = ImportTransactionsUseCase(repo)
                result = uc.import_from_file(pt_path, ResolutionStrategy.UPDATE)
                repo.save()
            finally:
                repo.close()
        finally:
            os.unlink(pt_path)

        assert result.updated_count == 1
        assert result.imported_count == 0
        assert result.skipped_count == 0
        assert result.error_count == 0

        # Verify description changed and GUID still present
        session = _open_session(path)
        book = session.book
        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        guids = [t.GetGUID().to_string() for t in txs]
        assert guid in guids, "GUID must be preserved after update"
        updated_tx = next(t for t in txs if t.GetGUID().to_string() == guid)
        assert updated_tx.GetDescription() == 'Updated lunch description'
        session.end()

    def test_update_changes_amount(self, gnucash_with_exportable_transaction):
        """
        Plaintext with GUID + changed amount → split amounts updated, GUID preserved.
        """
        from gnucash import Query, Transaction

        from repositories.gnucash_repository import GnuCashRepository
        from services.conflict_resolver import ResolutionStrategy
        from use_cases.import_transactions import ImportTransactionsUseCase

        path, guid = gnucash_with_exportable_transaction

        plaintext = (
            '2024-05-10 commodity CAD\n'
            '\tmnemonic: "CAD"\n'
            '\tfullname: "Canadian Dollar"\n'
            '\tnamespace: "CURRENCY"\n'
            '\tfraction: 100\n'
            f'2024-05-10 * "Lunch"\n'
            f'\tguid: "{guid}"\n'
            '\tExpenses:Dining 40.00 CAD\n'
            '\tAssets:Bank:Checking -40.00 CAD\n'
        )
        pt_path = _write_plaintext_file(plaintext)
        try:
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = ImportTransactionsUseCase(repo)
                result = uc.import_from_file(pt_path, ResolutionStrategy.UPDATE)
                repo.save()
            finally:
                repo.close()
        finally:
            os.unlink(pt_path)

        assert result.updated_count == 1

        session = _open_session(path)
        book = session.book
        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        updated_tx = next(t for t in txs if t.GetGUID().to_string() == guid)
        amounts = {s.GetAccount().GetName(): s.GetValue() for s in updated_tx.GetSplitList()}
        assert amounts['Dining'].num() == 4000
        assert amounts['Checking'].num() == -4000
        session.end()

    def test_skip_strategy_does_not_update(self, gnucash_with_exportable_transaction):
        """
        With SKIP strategy, a GUID-matched transaction is skipped, not updated.
        """
        from repositories.gnucash_repository import GnuCashRepository
        from services.conflict_resolver import ResolutionStrategy
        from use_cases.import_transactions import ImportTransactionsUseCase

        path, guid = gnucash_with_exportable_transaction

        plaintext = (
            '2024-05-10 commodity CAD\n'
            '\tmnemonic: "CAD"\n'
            '\tfullname: "Canadian Dollar"\n'
            '\tnamespace: "CURRENCY"\n'
            '\tfraction: 100\n'
            f'2024-05-10 * "Should not appear"\n'
            f'\tguid: "{guid}"\n'
            '\tExpenses:Dining 99.00 CAD\n'
            '\tAssets:Bank:Checking -99.00 CAD\n'
        )
        pt_path = _write_plaintext_file(plaintext)
        try:
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = ImportTransactionsUseCase(repo)
                result = uc.import_from_file(pt_path, ResolutionStrategy.SKIP)
            finally:
                repo.close()
        finally:
            os.unlink(pt_path)

        assert result.updated_count == 0
        assert result.skipped_count == 1
        assert result.imported_count == 0

    def test_unknown_guid_raises_error(self, gnucash_with_exportable_transaction):
        """
        A GUID in the plaintext that does not exist in the book raises ValueError.
        --strategy update must not silently create a new transaction.
        """
        from repositories.gnucash_repository import GnuCashRepository
        from services.conflict_resolver import ResolutionStrategy
        from use_cases.import_transactions import ImportTransactionsUseCase

        path, _existing_guid = gnucash_with_exportable_transaction

        fake_guid = 'a' * 32

        plaintext = (
            '2024-06-01 commodity CAD\n'
            '\tmnemonic: "CAD"\n'
            '\tfullname: "Canadian Dollar"\n'
            '\tnamespace: "CURRENCY"\n'
            '\tfraction: 100\n'
            f'2024-06-01 * "New transaction"\n'
            f'\tguid: "{fake_guid}"\n'
            '\tExpenses:Groceries 30.00 CAD\n'
            '\tAssets:Bank:Checking -30.00 CAD\n'
        )
        pt_path = _write_plaintext_file(plaintext)
        try:
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = ImportTransactionsUseCase(repo)
                with pytest.raises(ValueError, match="not found in book"):
                    uc.import_from_file(pt_path, ResolutionStrategy.UPDATE)
            finally:
                repo.close()
        finally:
            os.unlink(pt_path)

    def test_no_guid_in_plaintext_raises_error(self, gnucash_with_exportable_transaction):
        """
        --strategy update requires a guid: field on every transaction.
        Omitting it raises ValueError immediately.
        """
        from repositories.gnucash_repository import GnuCashRepository
        from services.conflict_resolver import ResolutionStrategy
        from use_cases.import_transactions import ImportTransactionsUseCase

        path, _guid = gnucash_with_exportable_transaction

        plaintext = (
            '2024-05-10 commodity CAD\n'
            '\tmnemonic: "CAD"\n'
            '\tfullname: "Canadian Dollar"\n'
            '\tnamespace: "CURRENCY"\n'
            '\tfraction: 100\n'
            '2024-05-10 * "Lunch"\n'
            '\tExpenses:Dining 25.00 CAD\n'
            '\tAssets:Bank:Checking -25.00 CAD\n'
        )
        pt_path = _write_plaintext_file(plaintext)
        try:
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = ImportTransactionsUseCase(repo)
                with pytest.raises(ValueError, match="guid:"):
                    uc.import_from_file(pt_path, ResolutionStrategy.UPDATE)
            finally:
                repo.close()
        finally:
            os.unlink(pt_path)


class TestStableRoundtrip:
    def test_import_update_import_no_duplicates(self, gnucash_with_exportable_transaction):
        """
        Stable roundtrip: update once, then re-import the same plaintext again.
        The second import must not create new transactions (GUID still matches → skip or update).
        """
        from gnucash import Query, Transaction

        from repositories.gnucash_repository import GnuCashRepository
        from services.conflict_resolver import ResolutionStrategy
        from use_cases.import_transactions import ImportTransactionsUseCase

        path, guid = gnucash_with_exportable_transaction

        plaintext = (
            '2024-05-10 commodity CAD\n'
            '\tmnemonic: "CAD"\n'
            '\tfullname: "Canadian Dollar"\n'
            '\tnamespace: "CURRENCY"\n'
            '\tfraction: 100\n'
            f'2024-05-10 * "Lunch v2"\n'
            f'\tguid: "{guid}"\n'
            '\tExpenses:Dining 25.00 CAD\n'
            '\tAssets:Bank:Checking -25.00 CAD\n'
        )
        pt_path = _write_plaintext_file(plaintext)
        try:
            # First import (update)
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = ImportTransactionsUseCase(repo)
                r1 = uc.import_from_file(pt_path, ResolutionStrategy.UPDATE)
                repo.save()
            finally:
                repo.close()

            assert r1.updated_count == 1
            assert r1.imported_count == 0

            # Second import of the same file (GUID still matches → skip, not duplicate creation)
            repo2 = GnuCashRepository(path)
            repo2.open()
            try:
                uc2 = ImportTransactionsUseCase(repo2)
                r2 = uc2.import_from_file(pt_path, ResolutionStrategy.UPDATE)
            finally:
                repo2.close()

            assert r2.imported_count == 0
            assert r2.updated_count == 1  # updates again (idempotent)
            assert r2.error_count == 0

        finally:
            os.unlink(pt_path)

        # Exactly one transaction must exist (no duplicates)
        session = _open_session(path)
        book = session.book
        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        assert len(txs) == 1
        assert txs[0].GetGUID().to_string() == guid
        session.end()


class TestImportResultSummary:
    def test_summary_includes_updated_count(self, gnucash_with_exportable_transaction):
        """get_summary() must include the Updated line."""
        from repositories.gnucash_repository import GnuCashRepository
        from services.conflict_resolver import ResolutionStrategy
        from use_cases.import_transactions import ImportTransactionsUseCase

        path, guid = gnucash_with_exportable_transaction

        plaintext = (
            '2024-05-10 commodity CAD\n'
            '\tmnemonic: "CAD"\n'
            '\tfullname: "Canadian Dollar"\n'
            '\tnamespace: "CURRENCY"\n'
            '\tfraction: 100\n'
            f'2024-05-10 * "Changed"\n'
            f'\tguid: "{guid}"\n'
            '\tExpenses:Dining 25.00 CAD\n'
            '\tAssets:Bank:Checking -25.00 CAD\n'
        )
        pt_path = _write_plaintext_file(plaintext)
        try:
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = ImportTransactionsUseCase(repo)
                result = uc.import_from_file(pt_path, ResolutionStrategy.UPDATE)
            finally:
                repo.close()
        finally:
            os.unlink(pt_path)

        summary = result.get_summary()
        assert 'Updated: 1' in summary
