"""
Tests for ValidateLedgerUseCase

These tests use real GnuCash files created in Docker (no mocks).
"""

import os
import tempfile

import pytest


class TestValidateLedger:
    """Test ledger validation use case"""

    def test_validate_valid_ledger(self, temp_gnucash_with_transactions):
        """Test validating a valid ledger"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.validate_ledger import ValidateLedgerUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ValidateLedgerUseCase(repo)
            result = use_case.execute()

            # Should be valid
            assert result.is_valid()

    def test_quick_check(self, temp_gnucash_with_transactions):
        """Test quick validation check"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.validate_ledger import ValidateLedgerUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ValidateLedgerUseCase(repo)
            is_valid = use_case.quick_check()

            assert is_valid is True

    def test_validate_with_duplicates(self, temp_gnucash_with_transactions):
        """Test validation detects duplicates"""
        from gnucash import GncNumeric, Split, Transaction

        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.validate_ledger import ValidateLedgerUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            # Add duplicate transaction
            commod_table = repo.book.get_table()
            cad = commod_table.lookup('CURRENCY', 'CAD')

            dup_tx = Transaction(repo.book)
            dup_tx.BeginEdit()
            dup_tx.SetCurrency(cad)
            dup_tx.SetDate(15, 1, 2024)
            dup_tx.SetDescription("Duplicate")

            checking = repo.get_account("Assets:Bank:Checking")
            groceries = repo.get_account("Expenses:Groceries")

            split1 = Split(repo.book)
            split1.SetParent(dup_tx)
            split1.SetAccount(groceries)
            split1.SetValue(GncNumeric(5000, 100))

            split2 = Split(repo.book)
            split2.SetParent(dup_tx)
            split2.SetAccount(checking)
            split2.SetValue(GncNumeric(-5000, 100))

            dup_tx.CommitEdit()

            # Validate
            use_case = ValidateLedgerUseCase(repo)
            result = use_case.execute(check_duplicates=True)

            # Should have warning about duplicates
            assert result.has_warnings()
            assert any(w.code == "DUPLICATES_DETECTED" for w in result.warnings)

    def test_get_statistics(self, temp_gnucash_with_transactions):
        """Test getting statistics with validation"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.validate_ledger import ValidateLedgerUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ValidateLedgerUseCase(repo)
            stats = use_case.get_statistics()

            # Should have stats
            assert 'total_accounts' in stats
            assert 'total_transactions' in stats
            assert 'validation' in stats

            # Validation info
            validation = stats['validation']
            assert 'is_valid' in validation
            assert 'error_count' in validation
            assert validation['is_valid'] is True

    def test_validate_and_report_to_file(self, temp_gnucash_with_transactions):
        """Test validation with report output"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.validate_ledger import ValidateLedgerUseCase

        fd, report_path = tempfile.mkstemp(suffix='.txt')
        os.close(fd)

        try:
            with GnuCashRepository(temp_gnucash_with_transactions) as repo:
                use_case = ValidateLedgerUseCase(repo)
                use_case.validate_and_report(output_path=report_path)

                # Should create report file
                assert os.path.exists(report_path)

                with open(report_path) as f:
                    content = f.read()
                    assert "VALIDATION REPORT" in content

        finally:
            if os.path.exists(report_path):
                os.unlink(report_path)

    def test_validate_with_options(self, temp_gnucash_with_transactions):
        """Test validation with different options"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.validate_ledger import ValidateLedgerUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ValidateLedgerUseCase(repo)

            # Validate without optional checks
            result = use_case.execute(
                check_duplicates=False,
                check_date_order=False,
                check_future_dates=False
            )

            assert result.is_valid()
