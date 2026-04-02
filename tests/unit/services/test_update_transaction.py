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


def _make_book():
    """
    Create a minimal CAD GnuCash book suitable for update_transaction tests.

    Accounts created:
      Assets:Bank:Checking  (BANK)
      Expenses:Groceries    (EXPENSE)
      Expenses:Dining       (EXPENSE)

    Returns (session, book, path). Caller owns session.end() and path cleanup.
    """
    import gnucash
    from gnucash import Account

    fd, path = tempfile.mkstemp(suffix='.gnucash')
    os.close(fd)
    os.unlink(path)

    session = _make_session(path)
    book = session.book
    root = book.get_root_account()
    cad = book.get_table().lookup('CURRENCY', 'CAD')

    def _acct(name, acct_type, parent):
        a = Account(book)
        a.SetName(name)
        a.SetType(acct_type)
        a.SetCommodity(cad)
        parent.append_child(a)
        return a

    assets   = _acct('Assets',   gnucash.ACCT_TYPE_ASSET,   root)
    bank     = _acct('Bank',     gnucash.ACCT_TYPE_BANK,    assets)
    _acct('Checking',  gnucash.ACCT_TYPE_BANK,    bank)
    expenses = _acct('Expenses', gnucash.ACCT_TYPE_EXPENSE, root)
    _acct('Groceries', gnucash.ACCT_TYPE_EXPENSE, expenses)
    _acct('Dining',    gnucash.ACCT_TYPE_EXPENSE, expenses)

    return session, book, path


def _get_tx(book, guid):
    """Return the Transaction with the given GUID from *book*."""
    from gnucash import Query, Transaction
    q = Query()
    q.search_for('Trans')
    q.set_book(book)
    txs = [Transaction(instance=t) for t in q.run()]
    return next(t for t in txs if t.GetGUID().to_string() == guid)


@pytest.fixture
def gnucash_with_one_transaction():
    """
    Temp GnuCash file with one CAD transaction:
      2024-03-01  Grocery shopping
        Expenses:Groceries   50.00 CAD
        Assets:Bank:Checking -50.00 CAD

    Yields (path, guid_string).
    """
    from services.gnucash_importer import GnuCashImporter

    session, book, path = _make_book()
    try:
        directive = _build_directive('2024-03-01', 'Grocery shopping', [
            {'account': 'Expenses:Groceries',    'amount': '50.00'},
            {'account': 'Assets:Bank:Checking',  'amount': '-50.00'},
        ])
        result = GnuCashImporter.create_transaction(directive, book)
        guid = result.GetGUID().to_string()
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


@pytest.fixture
def gnucash_with_meal_and_tip_transaction():
    """
    Temp GnuCash file with one CAD transaction that has two splits for the same
    Dining account (meal + tip):

      2024-03-07  Restaurant meal with tip
        Expenses:Dining  30.45 CAD  (meal)
        Expenses:Dining   5.00 CAD  (tip)
        Assets:Bank:Checking  -35.45 CAD

    Yields (path, guid_string).
    """
    from services.gnucash_importer import GnuCashImporter

    session, book, path = _make_book()
    try:
        directive = _build_directive('2024-03-07', 'Restaurant meal with tip', [
            {'account': 'Expenses:Dining',       'amount': '30.45'},
            {'account': 'Expenses:Dining',       'amount': '5.00'},
            {'account': 'Assets:Bank:Checking',  'amount': '-35.45'},
        ])
        result = GnuCashImporter.create_transaction(directive, book)
        guid = result.GetGUID().to_string()
        session.save()
        session.end()

        yield path, guid

    finally:
        if os.path.exists(path):
            os.unlink(path)
        lock = path + '.LCK'
        if os.path.exists(lock):
            os.unlink(lock)


class TestUpdateTransactionDuplicateAccountSplits:
    """Tests for update_transaction when multiple splits share the same account."""

    def test_two_splits_same_account_both_amounts_updated(self, gnucash_with_meal_and_tip_transaction):
        """
        Regression: updating a transaction with two splits for the same account
        must update both splits — not silently drop one and create an imbalance.
        """
        from gnucash import Query, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_meal_and_tip_transaction
        session = _open_session(path)
        book = session.book

        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-03-07', 'Restaurant meal with tip', [
            {'account': 'Expenses:Dining', 'amount': '40.00'},
            {'account': 'Expenses:Dining', 'amount': '8.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-48.00'},
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

        dining_splits = [
            s for s in updated.GetSplitList()
            if s.GetAccount().GetName() == 'Dining'
        ]
        assert len(dining_splits) == 2, (
            f"Expected 2 Dining splits, got {len(dining_splits)}"
        )

        dining_amounts = sorted(s.GetValue().num() for s in dining_splits)
        assert dining_amounts == [800, 4000], (
            f"Expected Dining splits of 8.00 and 40.00, got {dining_amounts}"
        )

        account_names = [s.GetAccount().GetName() for s in updated.GetSplitList()]
        imbalance_splits = [n for n in account_names if 'Imbalance' in n or 'imbalance' in n]
        assert imbalance_splits == [], f"Unexpected imbalance splits: {imbalance_splits}"

        session2.end()

    def test_update_from_one_to_two_splits_same_account(self, gnucash_with_one_transaction):
        """
        Regression: updating from a single dining split to two dining splits
        (adding a tip) must create both splits without imbalance.
        """
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
            {'account': 'Expenses:Dining', 'amount': '45.00'},
            {'account': 'Expenses:Dining', 'amount': '5.00'},
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

        dining_splits = [
            s for s in updated.GetSplitList()
            if s.GetAccount().GetName() == 'Dining'
        ]
        assert len(dining_splits) == 2, (
            f"Expected 2 Dining splits after update, got {len(dining_splits)}"
        )

        dining_amounts = sorted(s.GetValue().num() for s in dining_splits)
        assert dining_amounts == [500, 4500], (
            f"Expected Dining 45.00 and 5.00, got {dining_amounts}"
        )

        account_names = [s.GetAccount().GetName() for s in updated.GetSplitList()]
        imbalance_splits = [n for n in account_names if 'Imbalance' in n or 'imbalance' in n]
        assert imbalance_splits == [], f"Unexpected imbalance splits: {imbalance_splits}"

        session2.end()

    def test_three_splits_same_account_reduced_to_two(self, gnucash_with_meal_and_tip_transaction):
        """
        Regression: when directive has fewer splits for an account than currently
        exist, the excess existing splits must be destroyed (not left as orphans).
        Here we add a third Dining split to the fixture then update with only two.
        """
        import gnucash as gnc
        from gnucash import GncNumeric, Query, Split, Transaction

        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_meal_and_tip_transaction

        # Add a third Dining split so the transaction has 3
        session = _open_session(path)
        book = session.book
        q = Query()
        q.search_for('Trans')
        q.set_book(book)
        txs = [Transaction(instance=t) for t in q.run()]
        existing_tx = next(t for t in txs if t.GetGUID().to_string() == guid)

        from infrastructure.gnucash.utils import find_account
        dining = find_account(book.get_root_account(), 'Expenses:Dining')
        existing_tx.BeginEdit()
        extra = Split(book)
        extra.SetParent(existing_tx)
        extra.SetAccount(dining)
        extra.SetValue(GncNumeric(200, 100))
        existing_tx.CommitEdit()
        session.save()
        session.end()

        import time
        time.sleep(1)

        # Now update with only 2 Dining splits — the third must be destroyed
        session2 = _open_session(path)
        book2 = session2.book
        q2 = Query()
        q2.search_for('Trans')
        q2.set_book(book2)
        txs2 = [Transaction(instance=t) for t in q2.run()]
        existing_tx2 = next(t for t in txs2 if t.GetGUID().to_string() == guid)

        directive = _build_directive('2024-03-07', 'Restaurant meal with tip', [
            {'account': 'Expenses:Dining', 'amount': '30.45'},
            {'account': 'Expenses:Dining', 'amount': '5.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-35.45'},
        ])

        GnuCashImporter.update_transaction(existing_tx2, directive, book2)
        session2.save()
        session2.end()

        time.sleep(1)

        session3 = _open_session(path)
        book3 = session3.book
        q3 = Query()
        q3.search_for('Trans')
        q3.set_book(book3)
        txs3 = [Transaction(instance=t) for t in q3.run()]
        updated = next(t for t in txs3 if t.GetGUID().to_string() == guid)

        dining_splits = [
            s for s in updated.GetSplitList()
            if s.GetAccount().GetName() == 'Dining'
        ]
        assert len(dining_splits) == 2, (
            f"Expected 2 Dining splits after removing excess, got {len(dining_splits)}"
        )

        account_names = [s.GetAccount().GetName() for s in updated.GetSplitList()]
        imbalance_splits = [n for n in account_names if 'Imbalance' in n or 'imbalance' in n]
        assert imbalance_splits == [], f"Unexpected imbalance splits: {imbalance_splits}"

        session3.end()


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

    def test_invalid_account_leaves_split_count_intact(self, gnucash_with_one_transaction):
        """
        Rollback on ValueError must leave the split list unchanged.
        The validation guard fires before any splits are touched, so both
        count and account names must match the pre-update state.
        """
        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book
        existing_tx = _get_tx(book, guid)

        pre_accounts = {s.GetAccount().GetName() for s in existing_tx.GetSplitList()}
        pre_count = len(existing_tx.GetSplitList())

        # One valid, one invalid — validation should reject before any mutation
        directive = _build_directive('2024-03-01', 'Bad transaction', [
            {'account': 'Expenses:Groceries',    'amount': '50.00'},
            {'account': 'Expenses:DoesNotExist', 'amount': '-50.00'},
        ])

        with pytest.raises(ValueError, match="Account not found"):
            GnuCashImporter.update_transaction(existing_tx, directive, book)

        post_accounts = {s.GetAccount().GetName() for s in existing_tx.GetSplitList()}
        post_count = len(existing_tx.GetSplitList())
        assert post_count == pre_count, f"Split count changed: {pre_count} → {post_count}"
        assert post_accounts == pre_accounts, f"Accounts changed: {pre_accounts} → {post_accounts}"
        session.end()

    def test_wrong_directive_type_raises(self, gnucash_with_one_transaction):
        """update_transaction raises ValueError if passed a non-TRANSACTION directive."""
        from services.gnucash_importer import GnuCashImporter
        from services.plaintext_parser import DirectiveType, PlaintextDirective

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book
        existing_tx = _get_tx(book, guid)

        bad_directive = PlaintextDirective(DirectiveType.SPLIT, level=0, line='')
        bad_directive.props = {}
        bad_directive.metadata = {}

        with pytest.raises(ValueError, match="Expected TRANSACTION"):
            GnuCashImporter.update_transaction(existing_tx, bad_directive, book)
        session.end()


# ---------------------------------------------------------------------------
# Fixture: two accounts each with two splits
# ---------------------------------------------------------------------------

@pytest.fixture
def gnucash_with_multi_duplicate_accounts():
    """
    Temp GnuCash file with a transaction having two splits each for
    Expenses:Dining AND Expenses:Groceries:

      2024-04-10  Shopping and dining
        Expenses:Dining      20.00 CAD
        Expenses:Dining       4.00 CAD  (tip)
        Expenses:Groceries   30.00 CAD
        Expenses:Groceries    6.00 CAD  (tax)
        Assets:Bank:Checking -60.00 CAD

    Yields (path, guid_string).
    """
    from services.gnucash_importer import GnuCashImporter

    session, book, path = _make_book()
    try:
        directive = _build_directive('2024-04-10', 'Shopping and dining', [
            {'account': 'Expenses:Dining',      'amount': '20.00'},
            {'account': 'Expenses:Dining',      'amount': '4.00'},
            {'account': 'Expenses:Groceries',   'amount': '30.00'},
            {'account': 'Expenses:Groceries',   'amount': '6.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-60.00'},
        ])
        result = GnuCashImporter.create_transaction(directive, book)
        guid = result.GetGUID().to_string()
        session.save()
        session.end()

        yield path, guid

    finally:
        if os.path.exists(path):
            os.unlink(path)
        lock = path + '.LCK'
        if os.path.exists(lock):
            os.unlink(lock)


class TestUpdateTransactionDuplicateAccountSplitsExtra:
    """Additional duplicate-account scenarios beyond the original regression tests."""

    def test_two_splits_same_account_reduced_to_one(self, gnucash_with_meal_and_tip_transaction):
        """
        Reducing two same-account splits to one must destroy the surplus second split.
        Tests the `existing_splits[len(split_directives):]` path with len == 1.
        """
        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_meal_and_tip_transaction
        session = _open_session(path)
        book = session.book
        existing_tx = _get_tx(book, guid)

        directive = _build_directive('2024-03-07', 'Restaurant meal', [
            {'account': 'Expenses:Dining',      'amount': '35.45'},
            {'account': 'Assets:Bank:Checking', 'amount': '-35.45'},
        ])

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        updated = _get_tx(book2, guid)

        dining_splits = [s for s in updated.GetSplitList() if s.GetAccount().GetName() == 'Dining']
        assert len(dining_splits) == 1, f"Expected 1 Dining split, got {len(dining_splits)}"
        assert dining_splits[0].GetValue().num() == 3545
        assert [s for s in updated.GetSplitList() if 'Imbalance' in s.GetAccount().GetName()] == []
        session2.end()

    def test_per_split_memo_independent_on_duplicate_pair(self, gnucash_with_meal_and_tip_transaction):
        """
        Each split in a same-account pair must receive its own memo independently —
        the first split's memo must not bleed into the second.
        """
        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_meal_and_tip_transaction
        session = _open_session(path)
        book = session.book
        existing_tx = _get_tx(book, guid)

        directive = _build_directive('2024-03-07', 'Restaurant meal with tip', [
            {'account': 'Expenses:Dining',      'amount': '30.45', 'memo': 'meal'},
            {'account': 'Expenses:Dining',      'amount': '5.00',  'memo': 'tip'},
            {'account': 'Assets:Bank:Checking', 'amount': '-35.45'},
        ])

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        updated = _get_tx(book2, guid)

        # Sort by amount so we reliably identify meal vs tip
        dining_splits = sorted(
            [s for s in updated.GetSplitList() if s.GetAccount().GetName() == 'Dining'],
            key=lambda s: s.GetValue().num(),
        )
        assert len(dining_splits) == 2
        assert dining_splits[0].GetMemo() == 'tip',  f"tip split memo: {dining_splits[0].GetMemo()!r}"
        assert dining_splits[1].GetMemo() == 'meal', f"meal split memo: {dining_splits[1].GetMemo()!r}"
        session2.end()

    def test_two_accounts_each_with_two_splits_all_updated(self, gnucash_with_multi_duplicate_accounts):
        """
        When multiple accounts each have duplicate splits, positional matching must
        work independently per account — no cross-contamination between groups.
        """
        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_multi_duplicate_accounts
        session = _open_session(path)
        book = session.book
        existing_tx = _get_tx(book, guid)

        directive = _build_directive('2024-04-10', 'Shopping and dining', [
            {'account': 'Expenses:Dining',      'amount': '25.00'},
            {'account': 'Expenses:Dining',      'amount': '5.00'},
            {'account': 'Expenses:Groceries',   'amount': '40.00'},
            {'account': 'Expenses:Groceries',   'amount': '8.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-78.00'},
        ])

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        updated = _get_tx(book2, guid)

        dining_amounts = sorted(
            s.GetValue().num()
            for s in updated.GetSplitList()
            if s.GetAccount().GetName() == 'Dining'
        )
        groceries_amounts = sorted(
            s.GetValue().num()
            for s in updated.GetSplitList()
            if s.GetAccount().GetName() == 'Groceries'
        )
        assert dining_amounts == [500, 2500], f"Dining amounts: {dining_amounts}"
        assert groceries_amounts == [800, 4000], f"Groceries amounts: {groceries_amounts}"
        assert [s for s in updated.GetSplitList() if 'Imbalance' in s.GetAccount().GetName()] == []
        session2.end()

    def test_explicit_value_metadata_applied_to_split(self, gnucash_with_one_transaction):
        """
        When a split directive carries a 'value' metadata key, update_transaction
        must use it rather than copying props['amount'].
        This exercises the `if 'value' in split_directive.metadata` branch.

        In a single-currency split GnuCash normalises Amount = Value, so both
        Checking and Groceries use the same currency (CAD). The bank split is set
        to -55.00 to keep the transaction balanced after value overrides 50→55 on
        the Groceries split.
        """
        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book
        existing_tx = _get_tx(book, guid)

        directive = _build_directive('2024-03-01', 'Grocery shopping', [
            {'account': 'Expenses:Groceries',   'amount': '50.00', 'value': '55.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-55.00'},
        ])

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        updated = _get_tx(book2, guid)

        groceries_split = next(
            s for s in updated.GetSplitList()
            if s.GetAccount().GetName() == 'Groceries'
        )
        assert groceries_split.GetValue().num() == 5500, (
            f"value should be 55.00 (5500/100), got {groceries_split.GetValue().num()}"
        )
        assert [s for s in updated.GetSplitList() if 'Imbalance' in s.GetAccount().GetName()] == []
        session2.end()

    def test_tx_num_updated(self, gnucash_with_one_transaction):
        """update_transaction sets the transaction number when tx_num is non-None."""
        from services.gnucash_importer import GnuCashImporter

        path, guid = gnucash_with_one_transaction
        session = _open_session(path)
        book = session.book
        existing_tx = _get_tx(book, guid)

        directive = _build_directive('2024-03-01', 'Grocery shopping', [
            {'account': 'Expenses:Groceries',   'amount': '50.00'},
            {'account': 'Assets:Bank:Checking', 'amount': '-50.00'},
        ])
        directive.props['tx_num'] = '42'

        GnuCashImporter.update_transaction(existing_tx, directive, book)
        session.save()
        session.end()

        session2 = _open_session(path)
        book2 = session2.book
        updated = _get_tx(book2, guid)
        assert updated.GetNum() == '42'
        session2.end()
