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


class TestExportByGuid:
    """Test execute_by_guid — single-transaction export"""

    def test_export_known_guid_returns_one_transaction(self, temp_gnucash_with_transactions):
        """execute_by_guid returns exactly one transaction matching the given GUID"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            all_result = use_case.execute()
            target_guid = all_result.transactions[0].GetGUID().to_string()

            result = use_case.execute_by_guid(target_guid)

            assert len(result.transactions) == 1
            assert result.transactions[0].GetGUID().to_string() == target_guid

    def test_export_by_guid_includes_commodities_and_accounts(self, temp_gnucash_with_transactions):
        """execute_by_guid result includes commodity and account declarations"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            all_result = use_case.execute()
            guid = all_result.transactions[0].GetGUID().to_string()

            result = use_case.execute_by_guid(guid)

            assert len(result.commodities) > 0
            assert len(result.accounts) > 0

    def test_export_by_guid_plaintext_is_self_contained(self, temp_gnucash_with_transactions):
        """format_as_plaintext on a single-transaction result is self-contained"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            all_result = use_case.execute()
            guid = all_result.transactions[0].GetGUID().to_string()

            result = use_case.execute_by_guid(guid)
            plaintext = use_case.format_as_plaintext(result)

            assert "commodity" in plaintext
            assert "open " in plaintext
            assert f'guid: "{guid}"' in plaintext

    def test_export_by_guid_invalid_guid_raises_value_error(self, temp_gnucash_with_transactions):
        """execute_by_guid raises ValueError for a malformed GUID string"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            with pytest.raises(ValueError, match="Invalid GUID format"):
                use_case.execute_by_guid("not-a-valid-guid")

    def test_export_by_guid_nonexistent_guid_raises_value_error(self, temp_gnucash_with_transactions):
        """execute_by_guid raises ValueError when no transaction has the given GUID"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            with pytest.raises(ValueError, match="No transaction found"):
                use_case.execute_by_guid("deadbeefdeadbeefdeadbeefdeadbeef")


class TestExportByGuids:
    """Test execute_by_guids — multi-transaction export"""

    def test_export_two_guids_returns_both_transactions(self, temp_gnucash_with_transactions):
        """execute_by_guids returns all requested transactions"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            all_result = use_case.execute()
            assert len(all_result.transactions) >= 2, "fixture needs at least 2 transactions"
            guid0 = all_result.transactions[0].GetGUID().to_string()
            guid1 = all_result.transactions[1].GetGUID().to_string()

            result = use_case.execute_by_guids([guid0, guid1])

            assert len(result.transactions) == 2
            result_guids = {tx.GetGUID().to_string() for tx in result.transactions}
            assert guid0 in result_guids
            assert guid1 in result_guids

    def test_export_by_guids_shared_commodities_emitted_once(self, temp_gnucash_with_transactions):
        """Commodities shared across multiple transactions appear only once in the result"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            all_result = use_case.execute()
            guids = [tx.GetGUID().to_string() for tx in all_result.transactions[:2]]

            result = use_case.execute_by_guids(guids)

            # Commodity tickers must be unique in the result
            tickers = [c.get_mnemonic() for c, _ in result.commodities]
            assert len(tickers) == len(set(tickers)), "duplicate commodity in result"

    def test_export_by_guids_duplicate_guid_ignored(self, temp_gnucash_with_transactions):
        """Passing the same GUID twice produces exactly one transaction in the result"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            all_result = use_case.execute()
            guid = all_result.transactions[0].GetGUID().to_string()

            result = use_case.execute_by_guids([guid, guid])

            assert len(result.transactions) == 1

    def test_export_by_guids_invalid_guid_raises(self, temp_gnucash_with_transactions):
        """execute_by_guids raises ValueError for a malformed GUID"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            with pytest.raises(ValueError, match="Invalid GUID format"):
                use_case.execute_by_guids(["not-a-guid"])

    def test_export_by_guids_nonexistent_guid_raises(self, temp_gnucash_with_transactions):
        """execute_by_guids raises ValueError when a GUID is not found"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            with pytest.raises(ValueError, match="No transaction found"):
                use_case.execute_by_guids(["deadbeefdeadbeefdeadbeefdeadbeef"])

    def test_execute_by_guid_delegates_to_execute_by_guids(self, temp_gnucash_with_transactions):
        """execute_by_guid (singular) returns same result as execute_by_guids with one element"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)

            all_result = use_case.execute()
            guid = all_result.transactions[0].GetGUID().to_string()

            single = use_case.execute_by_guid(guid)
            multi  = use_case.execute_by_guids([guid])

            assert len(single.transactions) == len(multi.transactions) == 1
            assert single.transactions[0].GetGUID().to_string() == guid
