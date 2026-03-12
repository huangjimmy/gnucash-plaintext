"""
Tests for ImportTransactionsUseCase

These tests use real GnuCash files created in Docker (no mocks).
"""

import os
import tempfile

import pytest


class TestImportTransactions:
    """Test importing transactions use case"""

    def test_import_new_transaction(self, temp_gnucash_file):
        """Test importing new transaction"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        plaintext_tx = {
            'date': '2024-02-15',
            'description': 'Test transaction',
            'splits': [
                {'account': 'Expenses:Groceries', 'amount': '50.00'},
                {'account': 'Assets:Bank:Checking', 'amount': '-50.00'}
            ],
            'currency': 'CAD'
        }

        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ImportTransactionsUseCase(repo)
            result = use_case.execute([plaintext_tx])

            assert result.imported_count == 1
            assert result.error_count == 0
            assert result.skipped_count == 0

    def test_import_duplicate_transaction(self, temp_gnucash_with_transactions):
        """Test importing duplicate transaction"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        # Create duplicate of first transaction
        plaintext_tx = {
            'date': '2024-01-15',
            'description': 'Duplicate groceries',
            'splits': [
                {'account': 'Expenses:Groceries', 'amount': '50.00'},
                {'account': 'Assets:Bank:Checking', 'amount': '-50.00'}
            ],
            'currency': 'CAD'
        }

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ImportTransactionsUseCase(repo)
            result = use_case.execute([plaintext_tx])

            # Should be skipped as duplicate
            assert result.imported_count == 0
            assert result.skipped_count == 1

    def test_import_with_invalid_account(self, temp_gnucash_file):
        """Test importing with invalid account"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        plaintext_tx = {
            'date': '2024-02-15',
            'description': 'Test transaction',
            'splits': [
                {'account': 'Assets:DoesNotExist', 'amount': '50.00'},
                {'account': 'Assets:Bank:Checking', 'amount': '-50.00'}
            ],
            'currency': 'CAD'
        }

        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ImportTransactionsUseCase(repo)
            result = use_case.execute([plaintext_tx])

            # Should have error
            assert result.error_count == 1
            assert result.imported_count == 0

    def test_parse_full_format_file(self, temp_gnucash_file):
        """Test parsing full GnuCash plaintext format file"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        # Create test plaintext file with full format
        fd, path = tempfile.mkstemp(suffix='.txt')
        with os.fdopen(fd, 'w') as f:
            # Write commodity declaration
            f.write("2024-02-15 commodity CAD\n")
            f.write('\tmnemonic: "CAD"\n')
            f.write('\tfullname: "Canadian Dollar"\n')
            f.write('\tnamespace: "CURRENCY"\n')
            f.write('\tfraction: 100\n')
            # Write transaction
            f.write('2024-02-15 * "Test transaction 1"\n')
            f.write('\tExpenses:Groceries 50.00 CAD\n')
            f.write('\tAssets:Bank:Checking -50.00 CAD\n')

        try:
            with GnuCashRepository(temp_gnucash_file) as repo:
                use_case = ImportTransactionsUseCase(repo)
                result = use_case.import_from_file(path)

                # Should import 1 transaction (accounts already exist in fixture)
                assert result.imported_count == 1
                assert result.error_count == 0

        finally:
            os.unlink(path)

    def test_import_from_file(self, temp_gnucash_file):
        """Test importing from file with full format"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        # Create test plaintext file with full GnuCash format
        fd, path = tempfile.mkstemp(suffix='.txt')
        with os.fdopen(fd, 'w') as f:
            # Commodity declaration
            f.write("2024-02-15 commodity CAD\n")
            f.write('\tmnemonic: "CAD"\n')
            f.write('\tfullname: "Canadian Dollar"\n')
            f.write('\tnamespace: "CURRENCY"\n')
            f.write('\tfraction: 100\n')
            # Transaction
            f.write('2024-02-15 * "Test import"\n')
            f.write('\tExpenses:Groceries 50.00 CAD\n')
            f.write('\tAssets:Bank:Checking -50.00 CAD\n')

        try:
            with GnuCashRepository(temp_gnucash_file) as repo:
                use_case = ImportTransactionsUseCase(repo)
                result = use_case.import_from_file(path)

                assert result.imported_count == 1
                assert result.error_count == 0

        finally:
            os.unlink(path)

    def test_import_result_summary(self, temp_gnucash_file):
        """Test import result summary"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        plaintext_tx = {
            'date': '2024-02-15',
            'description': 'Test',
            'splits': [
                {'account': 'Expenses:Groceries', 'amount': '50.00'},
                {'account': 'Assets:Bank:Checking', 'amount': '-50.00'}
            ],
            'currency': 'CAD'
        }

        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ImportTransactionsUseCase(repo)
            result = use_case.execute([plaintext_tx])

            summary = result.get_summary()

            assert "Imported: 1" in summary
            assert "Skipped: 0" in summary
            assert "Errors: 0" in summary

    def test_import_with_conflict(self, temp_gnucash_with_transactions):
        """Test importing transaction with conflict"""
        from repositories.gnucash_repository import GnuCashRepository
        from services.conflict_resolver import ResolutionStrategy
        from use_cases.import_transactions import ImportTransactionsUseCase

        # Create transaction with same date/accounts but different amount
        plaintext_tx = {
            'date': '2024-01-15',
            'description': 'Conflict transaction',
            'splits': [
                {'account': 'Expenses:Groceries', 'amount': '75.00'},  # Different amount
                {'account': 'Assets:Bank:Checking', 'amount': '-75.00'}
            ],
            'currency': 'CAD'
        }

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ImportTransactionsUseCase(repo)
            result = use_case.execute([plaintext_tx], resolution_strategy=ResolutionStrategy.SKIP)

            # Should detect conflict
            assert len(result.conflicts) == 1
            assert result.imported_count == 0
