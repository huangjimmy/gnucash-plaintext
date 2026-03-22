"""
Unit tests for DeleteTransactionUseCase.

Verifies:
- Transaction is deleted by GUID
- Plaintext backup is included in the result (for undo)
- Unknown GUID raises ValueError
- Deletion is confirmed (transaction no longer in book after execute)
"""

import os
import tempfile

import pytest


def _make_gnucash_with_transaction():
    """Return (path, guid) for a GnuCash file containing one CAD transaction."""
    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)

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

    checking = Account(book)
    checking.SetName('Checking')
    checking.SetType(gnucash.ACCT_TYPE_BANK)
    checking.SetCommodity(cad)
    assets.append_child(checking)

    expenses = Account(book)
    expenses.SetName('Expenses')
    expenses.SetType(gnucash.ACCT_TYPE_EXPENSE)
    expenses.SetCommodity(cad)
    root.append_child(expenses)

    dining = Account(book)
    dining.SetName('Dining')
    dining.SetType(gnucash.ACCT_TYPE_EXPENSE)
    dining.SetCommodity(cad)
    expenses.append_child(dining)

    tx = Transaction(book)
    tx.BeginEdit()
    tx.SetCurrency(cad)
    tx.SetDate(15, 6, 2024)
    tx.SetDescription('Dinner out')

    s1 = Split(book)
    s1.SetParent(tx)
    s1.SetAccount(dining)
    s1.SetValue(GncNumeric(4500, 100))

    s2 = Split(book)
    s2.SetParent(tx)
    s2.SetAccount(checking)
    s2.SetValue(GncNumeric(-4500, 100))

    tx.CommitEdit()
    guid = tx.GetGUID().to_string()
    session.save()
    session.end()

    return path, guid


class TestDeleteTransactionUseCase:

    def test_delete_removes_transaction(self):
        """Transaction is no longer in the book after execute()."""
        from gnucash import Query, Transaction

        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.delete_transaction import DeleteTransactionUseCase

        path, guid = _make_gnucash_with_transaction()
        try:
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = DeleteTransactionUseCase(repo)
                uc.execute(guid)
                repo.save()
            finally:
                repo.close()

            # Verify transaction is gone
            try:
                from gnucash import Session, SessionOpenMode
                session = Session(f'xml://{path}', SessionOpenMode.SESSION_NORMAL_OPEN)
            except ImportError:
                from gnucash import Session
                session = Session(f'xml://{path}')
            book = session.book
            q = Query()
            q.search_for('Trans')
            q.set_book(book)
            txs = [Transaction(instance=t) for t in q.run()]
            guids = [t.GetGUID().to_string() for t in txs]
            assert guid not in guids
            session.end()
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_result_contains_plaintext_backup(self):
        """Result plaintext contains the GUID and account names (usable for re-import)."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.delete_transaction import DeleteTransactionUseCase

        path, guid = _make_gnucash_with_transaction()
        try:
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = DeleteTransactionUseCase(repo)
                result = uc.execute(guid)
            finally:
                repo.close()

            assert guid in result.plaintext
            assert 'Dining' in result.plaintext or 'Expenses' in result.plaintext
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_result_metadata(self):
        """Result carries description and date of the deleted transaction."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.delete_transaction import DeleteTransactionUseCase

        path, guid = _make_gnucash_with_transaction()
        try:
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = DeleteTransactionUseCase(repo)
                result = uc.execute(guid)
            finally:
                repo.close()

            assert result.guid == guid
            assert result.description == 'Dinner out'
            assert result.date == '2024-06-15'
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_unknown_guid_raises_value_error(self):
        """Non-existent GUID raises ValueError with the GUID in the message."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.delete_transaction import DeleteTransactionUseCase

        path, _guid = _make_gnucash_with_transaction()
        try:
            repo = GnuCashRepository(path)
            repo.open()
            try:
                uc = DeleteTransactionUseCase(repo)
                with pytest.raises(ValueError, match="not found in book"):
                    uc.execute('a' * 32)
            finally:
                repo.close()
        finally:
            if os.path.exists(path):
                os.unlink(path)
