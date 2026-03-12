"""
Tests for ConflictResolver service

These tests use real GnuCash files created in Docker (no mocks).
"""

import sys

import pytest


class TestConflictInfo:
    """Test ConflictInfo class"""

    def test_create_conflict_info(self, temp_gnucash_with_transactions):
        """Test creating ConflictInfo from two transactions"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.conflict_resolver import ConflictResolver

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            # Get existing transaction
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing_tx = Transaction(instance=result[0])

            # Create conflicting transaction (same date/accounts, different amount)
            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            conflict_tx = Transaction(book)
            conflict_tx.BeginEdit()
            conflict_tx.SetCurrency(cad)
            conflict_tx.SetDate(15, 1, 2024)  # Same as first transaction
            conflict_tx.SetDescription("Different amount groceries")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(conflict_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(7500, 100))  # Different amount

            split2 = Split(book)
            split2.SetParent(conflict_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-7500, 100))

            conflict_tx.CommitEdit()

            # Create conflict info
            resolver = ConflictResolver()
            conflict_info = resolver.create_conflict_info(existing_tx, conflict_tx)

            # Verify conflict info
            assert conflict_info.existing_date == "2024-01-15"
            assert conflict_info.incoming_date == "2024-01-15"
            assert len(conflict_info.existing_splits) == 2
            assert len(conflict_info.incoming_splits) == 2

        finally:
            session.end()

    def test_amounts_differ_true(self, temp_gnucash_with_transactions):
        """Test detecting when amounts differ"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.conflict_resolver import ConflictInfo

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            # Get existing
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing_tx = Transaction(instance=result[0])

            # Create with different amount
            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            conflict_tx = Transaction(book)
            conflict_tx.BeginEdit()
            conflict_tx.SetCurrency(cad)
            conflict_tx.SetDate(15, 1, 2024)
            conflict_tx.SetDescription("Different")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(conflict_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(9999, 100))  # Different

            split2 = Split(book)
            split2.SetParent(conflict_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-9999, 100))

            conflict_tx.CommitEdit()

            conflict_info = ConflictInfo(existing_tx, conflict_tx)
            assert conflict_info.amounts_differ() is True

        finally:
            session.end()

    def test_amounts_differ_false(self, temp_gnucash_with_transactions):
        """Test detecting when amounts are the same"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.conflict_resolver import ConflictInfo

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            # Get existing
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing_tx = Transaction(instance=result[0])

            # Create with same amount (true duplicate)
            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            dup_tx = Transaction(book)
            dup_tx.BeginEdit()
            dup_tx.SetCurrency(cad)
            dup_tx.SetDate(15, 1, 2024)
            dup_tx.SetDescription("Exact duplicate")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(dup_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(5000, 100))  # Same as original

            split2 = Split(book)
            split2.SetParent(dup_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-5000, 100))

            dup_tx.CommitEdit()

            conflict_info = ConflictInfo(existing_tx, dup_tx)
            assert conflict_info.amounts_differ() is False

        finally:
            session.end()

    def test_get_summary(self, temp_gnucash_with_transactions):
        """Test getting conflict summary"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.conflict_resolver import ConflictInfo

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            # Get existing
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing_tx = Transaction(instance=result[0])

            # Create conflicting
            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            conflict_tx = Transaction(book)
            conflict_tx.BeginEdit()
            conflict_tx.SetCurrency(cad)
            conflict_tx.SetDate(15, 1, 2024)
            conflict_tx.SetDescription("Conflict")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(conflict_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(7500, 100))

            split2 = Split(book)
            split2.SetParent(conflict_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-7500, 100))

            conflict_tx.CommitEdit()

            conflict_info = ConflictInfo(existing_tx, conflict_tx)
            summary = conflict_info.get_summary()

            # Summary should contain key information
            assert "2024-01-15" in summary
            assert "Existing:" in summary
            assert "Incoming:" in summary
            assert "Grocery shopping" in summary  # Original description
            assert "Conflict" in summary  # New description

        finally:
            session.end()


class TestConflictResolver:
    """Test ConflictResolver service"""

    def test_resolve_skip_strategy(self, temp_gnucash_with_transactions):
        """Test resolving conflicts with SKIP strategy"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.conflict_resolver import ConflictResolver, ResolutionStrategy

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            # Get existing
            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing_tx = Transaction(instance=result[0])

            # Create conflicting
            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            conflict_tx = Transaction(book)
            conflict_tx.BeginEdit()
            conflict_tx.SetCurrency(cad)
            conflict_tx.SetDate(15, 1, 2024)
            conflict_tx.SetDescription("Conflict")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(conflict_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(7500, 100))

            split2 = Split(book)
            split2.SetParent(conflict_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-7500, 100))

            conflict_tx.CommitEdit()

            # Resolve with SKIP strategy
            resolver = ConflictResolver()
            conflicts = [(existing_tx, conflict_tx)]
            to_import, unresolved = resolver.resolve(conflicts, ResolutionStrategy.SKIP)

            # Should not import, should be unresolved
            assert len(to_import) == 0
            assert len(unresolved) == 1

        finally:
            session.end()

    def test_resolve_keep_existing_strategy(self, temp_gnucash_with_transactions):
        """Test resolving conflicts with KEEP_EXISTING strategy"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.conflict_resolver import ConflictResolver, ResolutionStrategy

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing_tx = Transaction(instance=result[0])

            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            conflict_tx = Transaction(book)
            conflict_tx.BeginEdit()
            conflict_tx.SetCurrency(cad)
            conflict_tx.SetDate(15, 1, 2024)
            conflict_tx.SetDescription("Conflict")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(conflict_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(7500, 100))

            split2 = Split(book)
            split2.SetParent(conflict_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-7500, 100))

            conflict_tx.CommitEdit()

            resolver = ConflictResolver()
            conflicts = [(existing_tx, conflict_tx)]
            to_import, unresolved = resolver.resolve(conflicts, ResolutionStrategy.KEEP_EXISTING)

            # Should not import, should not be unresolved
            assert len(to_import) == 0
            assert len(unresolved) == 0

        finally:
            session.end()

    def test_resolve_keep_incoming_strategy(self, temp_gnucash_with_transactions):
        """Test resolving conflicts with KEEP_INCOMING strategy"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.conflict_resolver import ConflictResolver, ResolutionStrategy

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing_tx = Transaction(instance=result[0])

            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            conflict_tx = Transaction(book)
            conflict_tx.BeginEdit()
            conflict_tx.SetCurrency(cad)
            conflict_tx.SetDate(15, 1, 2024)
            conflict_tx.SetDescription("Conflict")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(conflict_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(7500, 100))

            split2 = Split(book)
            split2.SetParent(conflict_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-7500, 100))

            conflict_tx.CommitEdit()

            resolver = ConflictResolver()
            conflicts = [(existing_tx, conflict_tx)]
            to_import, unresolved = resolver.resolve(conflicts, ResolutionStrategy.KEEP_INCOMING)

            # Should import the incoming transaction
            assert len(to_import) == 1
            assert to_import[0] == conflict_tx
            assert len(unresolved) == 0

        finally:
            session.end()

    def test_resolve_single(self, temp_gnucash_with_transactions):
        """Test resolving single conflict"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.conflict_resolver import ConflictResolver, ResolutionStrategy

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing_tx = Transaction(instance=result[0])

            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            conflict_tx = Transaction(book)
            conflict_tx.BeginEdit()
            conflict_tx.SetCurrency(cad)
            conflict_tx.SetDate(15, 1, 2024)
            conflict_tx.SetDescription("Conflict")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(conflict_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(7500, 100))

            split2 = Split(book)
            split2.SetParent(conflict_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-7500, 100))

            conflict_tx.CommitEdit()

            resolver = ConflictResolver()

            # Test KEEP_EXISTING
            result = resolver.resolve_single(existing_tx, conflict_tx, ResolutionStrategy.KEEP_EXISTING)
            assert result is None

            # Test KEEP_INCOMING
            result = resolver.resolve_single(existing_tx, conflict_tx, ResolutionStrategy.KEEP_INCOMING)
            assert result == conflict_tx

            # Test SKIP
            result = resolver.resolve_single(existing_tx, conflict_tx, ResolutionStrategy.SKIP)
            assert result is None

        finally:
            session.end()

    def test_get_resolution_choices(self, temp_gnucash_with_transactions):
        """Test getting resolution choices for a conflict"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.conflict_resolver import ConflictInfo, ConflictResolver, ResolutionStrategy

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing_tx = Transaction(instance=result[0])

            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            conflict_tx = Transaction(book)
            conflict_tx.BeginEdit()
            conflict_tx.SetCurrency(cad)
            conflict_tx.SetDate(15, 1, 2024)
            conflict_tx.SetDescription("Conflict")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(conflict_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(7500, 100))

            split2 = Split(book)
            split2.SetParent(conflict_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-7500, 100))

            conflict_tx.CommitEdit()

            resolver = ConflictResolver()
            conflict_info = ConflictInfo(existing_tx, conflict_tx)
            choices = resolver.get_resolution_choices(conflict_info)

            # Should have 3 choices
            assert len(choices) == 3

            # Verify strategies
            strategies = [c['strategy'] for c in choices]
            assert ResolutionStrategy.KEEP_EXISTING in strategies
            assert ResolutionStrategy.KEEP_INCOMING in strategies
            assert ResolutionStrategy.SKIP in strategies

        finally:
            session.end()

    def test_format_conflict_report(self, temp_gnucash_with_transactions):
        """Test formatting conflict report"""
        from gnucash import GncNumeric, Session, Split, Transaction

        from services.conflict_resolver import ConflictInfo, ConflictResolver

        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{temp_gnucash_with_transactions}',
                            SessionOpenMode.SESSION_NORMAL_OPEN)
        except ImportError:
            # Fall back to older GnuCash API (< 4.0)
            session = Session(f'xml://{temp_gnucash_with_transactions}')

        try:
            book = session.book

            from gnucash import Query
            query = Query()
            query.search_for('Trans')
            query.set_book(book)
            result = query.run()
            existing_tx = Transaction(instance=result[0])

            commod_table = book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            conflict_tx = Transaction(book)
            conflict_tx.BeginEdit()
            conflict_tx.SetCurrency(cad)
            conflict_tx.SetDate(15, 1, 2024)
            conflict_tx.SetDescription("Conflict")

            from tests.conftest import find_account
            root = book.get_root_account()
            checking = find_account(root, "Assets:Bank:Checking")
            groceries = find_account(root, "Expenses:Groceries")

            split1 = Split(book)
            split1.SetParent(conflict_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(7500, 100))

            split2 = Split(book)
            split2.SetParent(conflict_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-7500, 100))

            conflict_tx.CommitEdit()

            resolver = ConflictResolver()
            conflict_info = ConflictInfo(existing_tx, conflict_tx)
            report = resolver.format_conflict_report([conflict_info])

            # Report should contain conflict information
            assert "Found 1 conflict(s):" in report
            assert "Conflict 1:" in report
            assert "2024-01-15" in report

            # Test empty report
            empty_report = resolver.format_conflict_report([])
            assert "No conflicts to report" in empty_report

        finally:
            session.end()
