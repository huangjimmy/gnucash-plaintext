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

    def test_an_amount_written_as_a_number_is_rounded_to_the_cent(self, temp_gnucash_file):
        """A number rather than text, and a figure finer than the currency."""
        from fractions import Fraction

        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        plaintext_tx = {
            'date': '2024-02-11',
            'description': 'Written as numbers',
            'splits': [
                {'account': 'Expenses:Groceries', 'amount': 12.345},
                {'account': 'Assets:Bank:Checking', 'amount': -12.345},
            ],
            'currency': 'CAD',
        }

        with GnuCashRepository(temp_gnucash_file) as repo:
            tx = ImportTransactionsUseCase(repo)._create_transaction_from_plaintext(plaintext_tx)

            values = sorted(Fraction(split.GetValue().num(), split.GetValue().denom())
                            for split in tx.GetSplitList())
            assert values == [Fraction(-1235, 100), Fraction(1235, 100)]

    def test_a_transaction_with_no_splits_is_refused_before_it_is_built(self, temp_gnucash_file):
        """GnuCash destroys a transaction left with no splits when its edit
        commits, and reading it afterwards ended the process: measured by
        `tests/research/what_execute_does_with_no_splits_or_an_unknown_currency_probe.py`,
        which runs it where a segfault ends only a child."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        plaintext_tx = {'date': '2024-02-10', 'description': 'Nothing moved',
                        'splits': [], 'currency': 'CAD'}

        with GnuCashRepository(temp_gnucash_file) as repo:
            result = ImportTransactionsUseCase(repo).execute([plaintext_tx])

            assert result.imported_count == 0
            assert result.errors[-1]['error'] == 'a transaction needs at least one split'

    def test_a_currency_gnucash_does_not_know_is_refused_by_its_code(self, temp_gnucash_file):
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.import_transactions import ImportTransactionsUseCase

        plaintext_tx = {
            'date': '2024-02-10', 'description': 'Unknown currency', 'currency': 'XYZ',
            'splits': [{'account': 'Expenses:Groceries', 'amount': '5.00'},
                       {'account': 'Assets:Bank:Checking', 'amount': '-5.00'}],
        }

        with GnuCashRepository(temp_gnucash_file) as repo:
            result = ImportTransactionsUseCase(repo).execute([plaintext_tx])

            assert result.imported_count == 0
            assert result.errors[-1]['error'] == 'XYZ is not a currency GnuCash knows'
