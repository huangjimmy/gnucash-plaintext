"""
Tests for TransactionMatcher service

These tests use real GnuCash files created in Docker (no mocks).
"""

import sys

import pytest


class TestTransactionMatcherSignature:
    """Test transaction signature generation"""

    def test_get_signature_simple(self, temp_gnucash_with_transactions):
        """Test signature generation for a simple transaction"""
        from gnucash import Session

        from services.transaction_matcher import TransactionMatcher

        # Open temp file
        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            ignore_lock=True)

        try:
            book = session.book

            # Get first transaction
            from gnucash import Query, Transaction
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()

            assert len(result) >= 1, "Should have at least one transaction"

            # Wrap SwigPyObject in Transaction object
            matcher = TransactionMatcher()
            tx = Transaction(instance=result[0])
            signature = matcher.get_signature(tx)

            # Signature should be (date_str, tuple_of_accounts)
            assert isinstance(signature, tuple)
            assert len(signature) == 2
            date_str, accounts = signature

            # Date should be YYYY-MM-DD format
            assert isinstance(date_str, str)
            assert len(date_str) == 10
            assert date_str[4] == '-' and date_str[7] == '-'

            # Accounts should be tuple of strings
            assert isinstance(accounts, tuple)
            assert len(accounts) == 2  # Two splits
            assert all(isinstance(acc, str) for acc in accounts)

            # Accounts should be sorted
            assert accounts == tuple(sorted(accounts))

        finally:
            session.end()

    def test_get_signature_for_plaintext(self):
        """Test creating signature from plaintext data"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()
        sig = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"]
        )

        assert sig == ("2024-01-15", ("Assets:Bank:Checking", "Expenses:Groceries"))

    def test_signature_account_order_doesnt_matter(self):
        """Test that account order doesn't affect signature"""
        from services.transaction_matcher import TransactionMatcher

        matcher = TransactionMatcher()

        sig1 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Assets:Bank:Checking", "Expenses:Groceries"]
        )

        sig2 = matcher.get_signature_for_plaintext(
            "2024-01-15",
            ["Expenses:Groceries", "Assets:Bank:Checking"]
        )

        # Should be identical (accounts are sorted)
        assert sig1 == sig2


class TestTransactionMatcherDuplicates:
    """Test duplicate detection"""

    def test_find_duplicates_no_duplicates(self, temp_gnucash_with_transactions):
        """Test when there are no duplicates"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.transaction_matcher import TransactionMatcher

        # Open temp file
        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            # Get existing transactions
            from gnucash import Query, Transaction
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing = [Transaction(instance=tx) for tx in result]

            # Create new transaction with different date
            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            new_tx = Transaction(book)
            new_tx.BeginEdit()
            new_tx.SetCurrency(cad)
            new_tx.SetDate(30, 1, 2024)  # Different date
            new_tx.SetDescription("New transaction")

            # Get accounts
            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(new_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(6000, 100))

            split2 = Split(book)
            split2.SetParent(new_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-6000, 100))

            new_tx.CommitEdit()

            # Find duplicates
            matcher = TransactionMatcher()
            new, duplicates, conflicts = matcher.find_duplicates(
                existing,
                [new_tx]
            )

            # Should be identified as new
            assert len(new) == 1
            assert len(duplicates) == 0
            assert len(conflicts) == 0

        finally:
            session.end()

    def test_find_duplicates_exact_duplicate(self, temp_gnucash_with_transactions):
        """Test detecting exact duplicate transaction"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.transaction_matcher import TransactionMatcher

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            # Get existing transactions
            from gnucash import Query, Transaction
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing = [Transaction(instance=tx) for tx in result]

            # Create duplicate of first transaction (same date, accounts, amounts)
            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            dup_tx = Transaction(book)
            dup_tx.BeginEdit()
            dup_tx.SetCurrency(cad)
            dup_tx.SetDate(15, 1, 2024)  # Same as first transaction
            dup_tx.SetDescription("Duplicate groceries")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(dup_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(5000, 100))  # Same amount as first

            split2 = Split(book)
            split2.SetParent(dup_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-5000, 100))

            dup_tx.CommitEdit()

            # Find duplicates
            matcher = TransactionMatcher()
            new, duplicates, conflicts = matcher.find_duplicates(
                existing,
                [dup_tx]
            )

            # Should be identified as duplicate
            assert len(new) == 0
            assert len(duplicates) == 1
            assert len(conflicts) == 0

        finally:
            session.end()

    def test_find_duplicates_conflict(self, temp_gnucash_with_transactions):
        """Test detecting conflict (same signature, different amounts)"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.transaction_matcher import TransactionMatcher

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            # Get existing transactions
            from gnucash import Query, Transaction
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing = [Transaction(instance=tx) for tx in result]

            # Create transaction with same date/accounts but different amount
            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            conflict_tx = Transaction(book)
            conflict_tx.BeginEdit()
            conflict_tx.SetCurrency(cad)
            conflict_tx.SetDate(15, 1, 2024)  # Same date as first
            conflict_tx.SetDescription("Conflict transaction")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(conflict_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(7500, 100))  # Different amount!

            split2 = Split(book)
            split2.SetParent(conflict_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-7500, 100))

            conflict_tx.CommitEdit()

            # Find duplicates
            matcher = TransactionMatcher()
            new, duplicates, conflicts = matcher.find_duplicates(
                existing,
                [conflict_tx]
            )

            # Should be identified as conflict
            assert len(new) == 0
            assert len(duplicates) == 0
            assert len(conflicts) == 1

        finally:
            session.end()


class TestTransactionMatcherHelpers:
    """Test helper methods"""

    def test_has_duplicate_signature(self, temp_gnucash_with_transactions):
        """Test checking for duplicate signature"""
        from gnucash import Session

        from services.transaction_matcher import TransactionMatcher

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            ignore_lock=True)

        try:
            book = session.book

            # Get transactions
            from gnucash import Query, Transaction
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            transactions = [Transaction(instance=tx) for tx in result]

            matcher = TransactionMatcher()

            # Should find existing signature
            has_dup = matcher.has_duplicate_signature(
                transactions,
                "2024-01-15",
                ["Assets:Bank:Checking", "Expenses:Groceries"]
            )
            assert has_dup is True

            # Should not find non-existent signature
            has_dup = matcher.has_duplicate_signature(
                transactions,
                "2024-12-31",
                ["Assets:Bank:Checking", "Expenses:Groceries"]
            )
            assert has_dup is False

        finally:
            session.end()

    def test_get_duplicate_count(self, temp_gnucash_with_transactions):
        """Test counting duplicates"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.transaction_matcher import TransactionMatcher

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            # Get existing transactions (should be 3, no duplicates)
            from gnucash import Query, Transaction
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            transactions = [Transaction(instance=tx) for tx in result]

            matcher = TransactionMatcher()
            dup_count = matcher.get_duplicate_count(transactions)
            assert dup_count == 0

            # Add a duplicate
            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            dup_tx = Transaction(book)
            dup_tx.BeginEdit()
            dup_tx.SetCurrency(cad)
            dup_tx.SetDate(15, 1, 2024)  # Same as first
            dup_tx.SetDescription("Duplicate")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(dup_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(5000, 100))

            split2 = Split(book)
            split2.SetParent(dup_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-5000, 100))

            dup_tx.CommitEdit()

            # Re-query to include new transaction
            query2 = Query()
            query2.search_for('Trans')
            query2.set_book(book)
            result2 = query2.run()
            all_transactions = [Transaction(instance=tx) for tx in result2]

            dup_count = matcher.get_duplicate_count(all_transactions)
            assert dup_count == 1

        finally:
            session.end()


class TestTransactionMatcherGUID:
    """Test GUID-based matching"""

    def test_find_by_guid(self, temp_gnucash_with_transactions):
        """Test finding transaction by GUID"""
        from gnucash import Session

        from services.transaction_matcher import TransactionMatcher

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            ignore_lock=True)

        try:
            book = session.book

            # Get transactions
            from gnucash import Query, Transaction
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            transactions = [Transaction(instance=tx) for tx in result]

            assert len(transactions) > 0

            # Get GUID of first transaction
            first_tx = transactions[0]
            guid = first_tx.GetGUID().to_string()

            # Find by GUID
            matcher = TransactionMatcher()
            found = matcher.find_by_guid(transactions, guid)

            assert found is not None
            assert found.GetGUID().to_string() == guid

            # Try non-existent GUID
            fake_guid = "00000000000000000000000000000000"
            found = matcher.find_by_guid(transactions, fake_guid)
            assert found is None

        finally:
            session.end()
