"""
Unit tests for GnuCashImporter.update_transaction()

These tests use real GnuCash files (no mocks), created in Docker.
Each test verifies that update_transaction() modifies the existing transaction
in-place and — critically — leaves the GUID unchanged.
"""

import os
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(path):
    """Open a new GnuCash session at *path* (SESSION_NEW_STORE)."""
    from gnucash import Session
    try:
        from gnucash import SessionOpenMode
        return Session(f'xml://{path}', SessionOpenMode.SESSION_NEW_STORE)
    except ImportError:
        return Session(f'xml://{path}', is_new=True)


def _open_session(path):
    """Open an existing GnuCash session at *path*."""
    from gnucash import Session
    try:
        from gnucash import SessionOpenMode
        return Session(f'xml://{path}', SessionOpenMode.SESSION_NORMAL_OPEN)
    except ImportError:
        return Session(f'xml://{path}')


def _build_directive(date_str, tx_desc, splits, metadata=None):
    """
    Construct a minimal PlaintextDirective for a TRANSACTION with the given splits.

    *splits* is a list of dicts: {'account': str, 'amount': str, ...optional metadata...}
    """
    from services.plaintext_parser import DirectiveType, PlaintextDirective

    tx_dir = PlaintextDirective(DirectiveType.TRANSACTION, level=0, line='')
    tx_dir.props = {'date': date_str, 'tx_num': None, 'tx_desc': tx_desc}
    tx_dir.metadata = metadata or {}

    for s in splits:
        split_dir = PlaintextDirective(DirectiveType.SPLIT, level=1, line='')
        split_dir.props = {'account': s['account'], 'amount': s['amount']}
        split_dir.metadata = {k: v for k, v in s.items() if k not in ('account', 'amount')}
        tx_dir.children.append(split_dir)

    return tx_dir


@pytest.fixture
def gnucash_with_one_transaction():
    """
    Temp GnuCash file with one CAD transaction:
      2024-03-01  Grocery shopping
        Expenses:Groceries   50.00 CAD
        Assets:Bank:Checking -50.00 CAD

    Yields (path, guid_string).
    """
    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)

    try:
        import gnucash
        from gnucash import Account, GncNumeric, Split, Transaction

        session = _make_session(path)
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
        tx.SetDate(1, 3, 2024)
        tx.SetDescription("Grocery shopping")

        s1 = Split(book)
        s1.SetParent(tx)
        s1.SetAccount(groceries)
        s1.SetValue(GncNumeric(5000, 100))

        s2 = Split(book)
        s2.SetParent(tx)
        s2.SetAccount(checking)
        s2.SetValue(GncNumeric(-5000, 100))

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestUpdateTransactionDescription:
    def test_description_changes(self, gnucash_with_one_transaction):
        """update_transaction changes the description."""
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-03-01', 'Updated description', [
            {'account': 'Expenses:Groceries', 'amount': '50.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-50.00'},
        ])

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        # Re-open and verify
        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        updated = next(t for t in txs2 if t.GetGUID().to_string() == guid)
        assert updated.GetDescription() == 'Updated description'
        session2.end()

    def test_guid_preserved_after_description_update(self, gnucash_with_one_transaction):
        """GUID must not change when description is updated."""
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-03-01', 'New description', [
            {'account': 'Expenses:Groceries', 'amount': '50.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-50.00'},
        ])

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        assert existing_tx.GetGUID().to_string() == guid
        session.save()
        session.end()

        # GUID must still be found after reload
        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        guids = [t.GetGUID().to_string() for t in txs2]
        assert guid in guids
        session2.end()


class TestUpdateTransactionAmounts:
    def test_split_amounts_change(self, gnucash_with_one_transaction):
        """update_transaction changes split amounts."""
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-03-01', 'Grocery shopping', [
            {'account': 'Expenses:Groceries', 'amount': '75.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-75.00'},
        ])

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        updated = next(t for t in txs2 if t.GetGUID().to_string() == guid)

        amounts = {
            split.GetAccount().GetName(): split.GetValue()
            for split in updated.GetSplitList()
        }
        assert amounts['Groceries'].num() == 7500
        assert amounts['Groceries'].denom() == 100
        assert amounts['Checking'].num() == -7500
        session2.end()

    def test_guid_preserved_after_amount_update(self, gnucash_with_one_transaction):
        """GUID must not change when amounts are updated."""
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-03-01', 'Grocery shopping', [
            {'account': 'Expenses:Groceries', 'amount': '99.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-99.00'},
        ])

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        assert existing_tx.GetGUID().to_string() == guid
        session.save()
        session.end()


class TestUpdateTransactionDate:
    def test_date_changes(self, gnucash_with_one_transaction):
        """update_transaction changes the posted date."""
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-04-15', 'Grocery shopping', [
            {'account': 'Expenses:Groceries', 'amount': '50.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-50.00'},
        ])

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        updated = next(t for t in txs2 if t.GetGUID().to_string() == guid)
        d = updated.GetDate()
        assert d.year == 2024
        assert d.month == 4
        assert d.day == 15
        session2.end()


class TestUpdateTransactionSplitStructure:
    def test_add_new_split(self, gnucash_with_one_transaction):
        """update_transaction can add a new split (2→3 splits)."""
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        # Change from 2-split to 3-split: split Groceries into Groceries + Dining
        directive = _build_directive('2024-03-01', 'Mixed shopping', [
            {'account': 'Expenses:Groceries', 'amount': '30.00'},
            {'account': 'Expenses:Dining', 'amount': '20.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-50.00'},
        ])

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        updated = next(t for t in txs2 if t.GetGUID().to_string() == guid)
        account_names = {s.GetAccount().GetName() for s in updated.GetSplitList()}
        assert 'Groceries' in account_names
        assert 'Dining' in account_names
        assert 'Checking' in account_names
        session2.end()

    def test_remove_split(self, gnucash_with_one_transaction):
        """update_transaction can remove a split (2→1 splits, partial update scenario)."""
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction

        # Add a third Dining split first
        session = _open_session(path)
        book = session.book
        import gnucash as gnc
        from gnucash import GncNumeric, Split

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        # Find Dining account
        root = book.get_root_account()
        from infrastructure.gnucash.utils import find_account
        dining = find_account(root, 'Expenses:Dining')

        existing_tx.BeginEdit()
        extra = Split(book)
        extra.SetParent(existing_tx)
        extra.SetAccount(dining)
        extra.SetValue(GncNumeric(2000, 100))
        existing_tx.CommitEdit()
        session.save()
        session.end()

        import time
        time.sleep(1)  # GnuCash backup filenames include a timestamp; avoid collision

        # Now update: remove Dining split
        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        existing_tx2 = next(t for t in txs2 if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-03-01', 'Grocery shopping', [
            {'account': 'Expenses:Groceries', 'amount': '50.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-50.00'},
        ])

        from services.gnucash_importer import GnuCashImporter
        GnuCashImporter.update_transaction(existing_tx2, directive, book2)
        session2.save()
        session2.end()

        session3 = _open_session(path)
        book3 = session3.book
        q3 = Query()
        q3.search_for('Trans')
        q3.set_book(book3)
        txs3 = [Transaction(instance=t) for t in q3.run()]
        updated = next(t for t in txs3 if t.GetGUID().to_string() == guid)
        account_names = {s.GetAccount().GetName() for s in updated.GetSplitList()}
        assert 'Dining' not in account_names
        assert 'Groceries' in account_names
        session3.end()


class TestUpdateTransactionMetadata:
    def test_notes_updated(self, gnucash_with_one_transaction):
        """update_transaction sets notes metadata."""
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-03-01', 'Grocery shopping', [
            {'account': 'Expenses:Groceries', 'amount': '50.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-50.00'},
        ], metadata={'notes': 'receipt #1234'})

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        updated = next(t for t in txs2 if t.GetGUID().to_string() == guid)
        assert updated.GetNotes() == 'receipt #1234'
        session2.end()

    def test_split_memo_updated(self, gnucash_with_one_transaction):
        """update_transaction sets split-level memo."""
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-03-01', 'Grocery shopping', [
            {'account': 'Expenses:Groceries', 'amount': '50.00', 'memo': 'organic section'},
            {'account': 'Assets:Bank:Checking', 'amount': '-50.00'},
        ])

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        updated = next(t for t in txs2 if t.GetGUID().to_string() == guid)

        groceries_split = next(
            s for s in updated.GetSplitList()
            if s.GetAccount().GetName() == 'Groceries'
        )
        assert groceries_split.GetMemo() == 'organic section'
        session2.end()


class TestUpdateTransactionErrorHandling:
    def test_invalid_account_raises_and_does_not_corrupt(self, gnucash_with_one_transaction):
        """update_transaction raises ValueError for unknown account and leaves transaction intact."""
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-03-01', 'Bad transaction', [
            {'account': 'Expenses:DoesNotExist', 'amount': '50.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-50.00'},
        ])

        with pytest.raises(ValueError, match="Account not found"):
            GnuCashImporter.update_transaction(existing_tx, directive, book)

        # Original description must be intact
        assert existing_tx.GetDescription() == 'Grocery shopping'
        session.end()
