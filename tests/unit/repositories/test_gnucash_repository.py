"""
Tests for GnuCashRepository

These tests use real GnuCash files created in Docker (no mocks).
"""

import os
import sys
import tempfile

import pytest


class TestSessionManagement:
    """Test session open/close operations"""

    def test_open_close_session(self, temp_gnucash_file):
        """Test opening and closing session"""
        from repositories.gnucash_repository import GnuCashRepository

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open()

        assert repo.session is not None
        assert repo.book is not None

        repo.close()

        assert repo.session is None

    def test_open_readonly(self, temp_gnucash_file):
        """Test opening in read-only mode"""
        from repositories.gnucash_repository import GnuCashRepository, SessionMode

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open(mode=SessionMode.READ_ONLY)

        assert repo.session is not None

        repo.close()

    def test_context_manager(self, temp_gnucash_file):
        """Test using repository as context manager"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            assert repo.session is not None
            root = repo.get_root_account()
            assert root is not None

        # Session should be closed after context
        assert repo.session is None

    def test_open_twice_raises_error(self, temp_gnucash_file):
        """Test opening session twice raises error"""
        from repositories.gnucash_repository import GnuCashRepository

        repo = GnuCashRepository(temp_gnucash_file)
        repo.open()

        with pytest.raises(RuntimeError, match="already open"):
            repo.open()

        repo.close()


class TestAccountOperations:
    """Test account-related operations"""

    def test_get_root_account(self, temp_gnucash_file):
        """Test getting root account"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            root = repo.get_root_account()

            assert root is not None
            assert root.is_root()

    def test_get_account(self, temp_gnucash_file):
        """Test getting account by path"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            checking = repo.get_account("Assets:Bank:Checking")

            assert checking is not None
            assert checking.GetName() == "Checking"

    def test_get_account_not_found(self, temp_gnucash_file):
        """Test getting non-existent account"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            account = repo.get_account("Assets:DoesNotExist")

            assert account is None

    def test_get_all_accounts(self, temp_gnucash_file):
        """Test getting all accounts"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            accounts = repo.get_all_accounts()

            # Should have Assets, Bank, Checking, Expenses, Groceries, Dining
            assert len(accounts) >= 6

            names = [acc.GetName() for acc in accounts]
            assert "Assets" in names
            assert "Checking" in names
            assert "Groceries" in names

    def test_get_accounts_by_type(self, temp_gnucash_file):
        """Test getting accounts by type"""
        import gnucash

        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            expense_accounts = repo.get_accounts_by_type(gnucash.ACCT_TYPE_EXPENSE)

            # Should include Expenses, Groceries, Dining
            assert len(expense_accounts) >= 3

            names = [acc.GetName() for acc in expense_accounts]
            assert "Groceries" in names
            assert "Dining" in names

    def test_create_account(self, temp_gnucash_file):
        """Test creating new account"""
        import gnucash

        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            # Create new account under Expenses
            new_account = repo.create_account(
                name="Entertainment",
                account_type=gnucash.ACCT_TYPE_EXPENSE,
                parent_path="Expenses",
                currency_code="CAD"
            )

            assert new_account is not None
            assert new_account.GetName() == "Entertainment"

            # Verify it was created
            found = repo.get_account("Expenses:Entertainment")
            assert found is not None


class TestTransactionOperations:
    """Test transaction-related operations"""

    def test_get_all_transactions(self, temp_gnucash_with_transactions):
        """Test getting all transactions"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            transactions = repo.get_all_transactions()

            # Should have 3 transactions
            assert len(transactions) == 3

    def test_get_transactions_by_account(self, temp_gnucash_with_transactions):
        """Test getting transactions by account"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            checking = repo.get_account("Assets:Bank:Checking")
            transactions = repo.get_transactions_by_account(checking)

            # All 3 transactions involve checking account
            assert len(transactions) == 3

    def test_get_transactions_by_date_range(self, temp_gnucash_with_transactions):
        """Test getting transactions by date range"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            # Get transactions in January 2024
            transactions = repo.get_transactions_by_date_range(
                "2024-01-15",
                "2024-01-20"
            )

            # Should have 2 transactions (Jan 15 and Jan 20)
            assert len(transactions) == 2

    def test_create_transaction(self, temp_gnucash_file):
        """Test creating new transaction"""
        from gnucash import GncNumeric

        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            splits_data = [
                {
                    'account_path': 'Expenses:Groceries',
                    'value': GncNumeric(5000, 100)
                },
                {
                    'account_path': 'Assets:Bank:Checking',
                    'value': GncNumeric(-5000, 100)
                }
            ]

            tx = repo.create_transaction(
                description="Test groceries",
                date_tuple=(20, 2, 2024),
                splits_data=splits_data,
                currency_code="CAD"
            )

            assert tx is not None
            assert tx.GetDescription() == "Test groceries"
            assert len(tx.GetSplitList()) == 2

    def test_create_transaction_invalid_account(self, temp_gnucash_file):
        """Test creating transaction with invalid account"""
        from gnucash import GncNumeric

        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            splits_data = [
                {
                    'account_path': 'Assets:DoesNotExist',
                    'value': GncNumeric(5000, 100)
                }
            ]

            with pytest.raises(ValueError, match="Account not found"):
                repo.create_transaction(
                    description="Test",
                    date_tuple=(20, 2, 2024),
                    splits_data=splits_data
                )

    def test_delete_transaction(self, temp_gnucash_with_transactions):
        """Test deleting transaction"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            # Get first transaction
            transactions = repo.get_all_transactions()
            initial_count = len(transactions)

            tx_to_delete = transactions[0]
            repo.delete_transaction(tx_to_delete)

            # Verify deletion
            remaining = repo.get_all_transactions()
            assert len(remaining) == initial_count - 1


class TestQueryOperations:
    """Test query and filter operations"""

    def test_find_transactions(self, temp_gnucash_with_transactions):
        """Test finding transactions with predicate"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            # Find transactions with "grocer" in description (matches both "Grocery" and "groceries")
            matching = repo.find_transactions(
                lambda tx: "grocer" in tx.GetDescription().lower()
            )

            # Should find 2 grocery transactions
            assert len(matching) == 2

    def test_find_accounts(self, temp_gnucash_file):
        """Test finding accounts with predicate"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            # Find accounts with "e" in name
            matching = repo.find_accounts(
                lambda acc: "e" in acc.GetName().lower()
            )

            # Should find several (Assets, Checking, Expenses, Groceries)
            assert len(matching) >= 4


class TestCommodityOperations:
    """Test commodity operations"""

    def test_get_commodity(self, temp_gnucash_file):
        """Test getting commodity"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            cad = repo.get_commodity('CURRENCY', 'CAD')

            assert cad is not None
            assert cad.get_mnemonic() == 'CAD'

    def test_get_default_currency(self, temp_gnucash_file):
        """Test getting default currency"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            usd = repo.get_default_currency()

            assert usd is not None
            assert usd.get_mnemonic() == 'USD'


class TestValidationIntegration:
    """Test validation integration"""

    def test_validate(self, temp_gnucash_with_transactions):
        """Test validating repository"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            result = repo.validate()

            # Should be valid
            assert result.is_valid()


class TestStatistics:
    """Test statistics methods"""

    def test_get_statistics(self, temp_gnucash_with_transactions):
        """Test getting repository statistics"""
        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            stats = repo.get_statistics()

            assert 'file_path' in stats
            assert 'total_accounts' in stats
            assert 'total_transactions' in stats
            assert 'accounts_by_category' in stats

            assert stats['total_accounts'] >= 6
            assert stats['total_transactions'] == 3


class TestFileOperations:
    """Test file operations"""

    def test_file_exists(self, temp_gnucash_file):
        """Test checking if file exists"""
        from repositories.gnucash_repository import GnuCashRepository

        assert GnuCashRepository.file_exists(temp_gnucash_file)
        assert not GnuCashRepository.file_exists("/nonexistent/file.gnucash")

    def test_create_new_file(self):
        """Test creating new file"""
        from repositories.gnucash_repository import GnuCashRepository

        fd, path = tempfile.mkstemp(suffix='.gnucash')
        os.close(fd)
        os.unlink(path)  # Delete so we can create new

        try:
            repo = GnuCashRepository.create_new_file(path)

            assert os.path.exists(path)
            assert repo.file_path == path

            # Should be able to open it
            repo.open()
            root = repo.get_root_account()
            assert root is not None
            repo.close()

        finally:
            if os.path.exists(path):
                os.unlink(path)
            lock_path = path + '.LCK'
            if os.path.exists(lock_path):
                os.unlink(lock_path)

    def test_create_new_file_already_exists(self, temp_gnucash_file):
        """Test creating file that already exists"""
        from repositories.gnucash_repository import GnuCashRepository

        with pytest.raises(FileExistsError):
            GnuCashRepository.create_new_file(temp_gnucash_file)


class TestSaveOperation:
    """Test save operations"""

    def test_save_changes(self, temp_gnucash_file):
        """Test saving changes"""
        import gnucash

        from repositories.gnucash_repository import GnuCashRepository

        with GnuCashRepository(temp_gnucash_file) as repo:
            # Create new account
            repo.create_account(
                name="TestAccount",
                account_type=gnucash.ACCT_TYPE_EXPENSE,
                parent_path="Expenses",
                currency_code="CAD"
            )

            # Save changes
            repo.save()

        # Reopen and verify
        with GnuCashRepository(temp_gnucash_file) as repo:
            account = repo.get_account("Expenses:TestAccount")
            assert account is not None
