"""
Test that export filtering works correctly for commodities, accounts, and transactions.

CRITICAL: When filtering transactions (by date or account), we must still export
ALL commodities and ALL accounts. They are declarations that must exist before
transactions can reference them.
"""

import pytest

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.export_transactions import ExportTransactionsUseCase


class TestExportFiltering:
    """Verify export filtering behavior for commodities, accounts, and transactions"""

    def test_date_filter_exports_all_commodities_and_accounts(self, temp_gnucash_with_transactions):
        """
        When filtering by date, export ALL commodities and ALL accounts,
        but only filtered transactions.

        This is critical - without all declarations, import will fail.
        """
        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            # Export ALL transactions first
            all_result = use_case.execute()
            all_commodity_count = len(all_result.commodities)
            all_account_count = len(all_result.accounts)
            all_transaction_count = len(all_result.transactions)

            # Now filter to only first 2 transactions (Jan 15 and Jan 20)
            filtered_result = use_case.execute(
                start_date="2024-01-15",
                end_date="2024-01-20"
            )

            # CRITICAL: Commodities and accounts should be THE SAME
            # Only transactions should be filtered
            assert len(filtered_result.commodities) == all_commodity_count, \
                "Date filter should NOT reduce commodity count"
            assert len(filtered_result.accounts) == all_account_count, \
                "Date filter should NOT reduce account count"
            assert len(filtered_result.transactions) < all_transaction_count, \
                "Date filter SHOULD reduce transaction count"
            assert len(filtered_result.transactions) == 2, \
                "Should have exactly 2 filtered transactions"

    def test_account_filter_exports_all_commodities_and_accounts(self, temp_gnucash_with_transactions):
        """
        When filtering by account, export ALL commodities and ALL accounts,
        but only filtered transactions.
        """
        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            # Export ALL transactions first
            all_result = use_case.execute()
            all_commodity_count = len(all_result.commodities)
            all_account_count = len(all_result.accounts)
            all_transaction_count = len(all_result.transactions)

            # Now filter to only Groceries transactions
            filtered_result = use_case.execute(
                account_filter="Expenses:Groceries"
            )

            # CRITICAL: Commodities and accounts should be THE SAME
            assert len(filtered_result.commodities) == all_commodity_count, \
                "Account filter should NOT reduce commodity count"
            assert len(filtered_result.accounts) == all_account_count, \
                "Account filter should NOT reduce account count"
            assert len(filtered_result.transactions) < all_transaction_count, \
                "Account filter SHOULD reduce transaction count"
            assert len(filtered_result.transactions) == 2, \
                "Should have 2 grocery transactions"

    def test_filtered_export_can_be_imported(self, temp_gnucash_with_transactions):
        """
        Verify that filtered export includes all necessary declarations
        for successful import.
        """
        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            # Filter to date range
            result = use_case.execute(
                start_date="2024-01-15",
                end_date="2024-01-20"
            )

            # Generate plaintext
            plaintext = use_case.format_as_plaintext(result)

            # Verify it has ALL necessary declarations
            # Even though we only exported 2 transactions, we should have
            # all commodities and accounts

            # Should have commodity declarations
            assert "commodity" in plaintext

            # Should have account declarations for ALL accounts
            # (not just those in the 2 filtered transactions)
            assert "open Assets:Bank:Checking" in plaintext
            assert "open Expenses:Groceries" in plaintext
            assert "open Expenses:Dining" in plaintext

            # Should only have 2 transactions (filtered)
            import re
            tx_count = len(re.findall(r'^\d{4}-\d{2}-\d{2} \*', plaintext, re.MULTILINE))
            assert tx_count == 2, "Should only have 2 filtered transactions"

    def test_no_filter_exports_everything(self, temp_gnucash_with_transactions):
        """
        When no filter is applied, export everything.
        """
        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            result = use_case.execute()

            # Should have commodities, accounts, and all transactions
            assert len(result.commodities) > 0
            assert len(result.accounts) > 0
            assert len(result.transactions) == 3  # All 3 transactions from fixture
