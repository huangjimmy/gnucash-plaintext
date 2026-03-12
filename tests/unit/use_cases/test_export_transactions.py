"""
Tests for ExportTransactionsUseCase

These tests use real GnuCash files created in Docker (no mocks).
"""

import os
import tempfile

import pytest


class TestExportTransactions:
    """Test exporting transactions use case"""

    def test_export_all_transactions(self, temp_gnucash_with_transactions):
        """Test exporting all transactions"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute()

            # Should export 3 transactions
            assert len(result.transactions) == 3

            # Should have commodities and accounts
            assert len(result.commodities) > 0
            assert len(result.accounts) > 0

    def test_export_date_range(self, temp_gnucash_with_transactions):
        """Test exporting transactions in date range"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute(
                start_date="2024-01-15",
                end_date="2024-01-20"
            )

            # Should export 2 transactions (Jan 15 and Jan 20)
            assert len(result.transactions) == 2

            # Verify dates
            dates = [tx.GetDate().strftime("%Y-%m-%d") for tx in result.transactions]
            assert "2024-01-15" in dates
            assert "2024-01-20" in dates
            assert "2024-01-25" not in dates

    def test_export_with_account_filter(self, temp_gnucash_with_transactions):
        """Test exporting with account filter"""
        from infrastructure.gnucash.utils import get_account_full_name
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute(
                account_filter="Expenses:Groceries"
            )

            # Should export 2 grocery transactions
            assert len(result.transactions) == 2

            # All should involve Groceries account
            for tx in result.transactions:
                splits = tx.GetSplitList()
                accounts = [get_account_full_name(s.GetAccount()) for s in splits]
                assert any("Groceries" in acc for acc in accounts)

    def test_transaction_structure(self, temp_gnucash_with_transactions):
        """Test transaction structure"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute()

            tx = result.transactions[0]

            # Verify transaction has expected properties
            assert tx.GetGUID() is not None
            assert tx.GetDate() is not None
            assert tx.GetDescription() is not None
            assert tx.GetCurrency() is not None

            # Verify splits
            splits = tx.GetSplitList()
            assert len(splits) == 2

    def test_format_as_plaintext(self, temp_gnucash_with_transactions):
        """Test formatting transactions as plaintext"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute()
            plaintext = use_case.format_as_plaintext(result)

            # Should contain dates and descriptions
            assert "2024-01-15" in plaintext
            assert "Grocery shopping" in plaintext
            assert "More groceries" in plaintext

            # Should contain account names
            assert "Assets:Bank:Checking" in plaintext
            assert "Expenses:Groceries" in plaintext

            # Should contain commodity declarations
            assert "commodity" in plaintext

            # Should contain account declarations
            assert "open" in plaintext

    def test_format_includes_all_metadata(self, temp_gnucash_with_transactions):
        """Test that format includes all required metadata"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute()
            plaintext = use_case.format_as_plaintext(result)

            # Commodity metadata
            assert "mnemonic:" in plaintext
            assert "fullname:" in plaintext
            assert "namespace:" in plaintext
            assert "fraction:" in plaintext

            # Account metadata
            assert "guid:" in plaintext
            assert "type:" in plaintext
            assert "commodity.namespace:" in plaintext
            assert "commodity.mnemonic:" in plaintext

            # Transaction metadata
            assert " * " in plaintext  # Transaction header

    def test_export_to_file(self, temp_gnucash_with_transactions):
        """Test exporting to file"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        fd, output_path = tempfile.mkstemp(suffix='.txt')
        os.close(fd)

        try:
            with GnuCashRepository(temp_gnucash_with_transactions) as repo:
                use_case = ExportTransactionsUseCase(repo)
                count = use_case.export_to_file(output_path)

                # Should export 3 transactions
                assert count == 3

                # Verify file exists and has content
                assert os.path.exists(output_path)
                with open(output_path) as f:
                    content = f.read()
                    assert len(content) > 0
                    assert "2024-01-15" in content
                    assert "commodity" in content
                    assert "open" in content

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_export_sorted_by_date(self, temp_gnucash_with_transactions):
        """Test transactions are sorted by date"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute()

            dates = [tx.GetDate() for tx in result.transactions]

            # Should be sorted
            assert dates == sorted(dates)
