"""
Tests for execute_accounts_only / format_accounts_only in ExportTransactionsUseCase.

These tests confirm that:
- execute_accounts_only never loads transactions
- All accounts and commodities are present in the result
- as_of_date is stamped correctly on every open/commodity line
- file mtime is used when as_of_date is omitted
"""

import pytest


class TestExecuteAccountsOnly:
    """execute_accounts_only returns accounts without touching transactions."""

    def test_returns_all_accounts(self, temp_gnucash_file):
        """All accounts in the book appear in the result."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()

        account_names = [
            acct.GetName() for acct, _ in result.accounts
        ]
        assert "Checking" in account_names
        assert "Groceries" in account_names
        assert "Dining" in account_names

    def test_result_has_no_transactions(self, temp_gnucash_file):
        """Result contains zero transactions — transaction log is never loaded."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()

        assert result.transactions == []

    def test_result_has_no_transactions_even_when_file_has_transactions(
        self, temp_gnucash_with_transactions
    ):
        """execute_accounts_only ignores transactions even when the book has some."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()

        assert result.transactions == []

    def test_commodities_not_duplicated(self, temp_gnucash_file):
        """Each commodity appears exactly once in the result."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()

        tickers = [c.get_mnemonic() for c, _ in result.commodities]
        assert len(tickers) == len(set(tickers))

    def test_accounts_not_duplicated(self, temp_gnucash_file):
        """Each account GUID appears exactly once in the result."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()

        guids = [acct.GetGUID().to_string() for acct, _ in result.accounts]
        assert len(guids) == len(set(guids))

    def test_accounts_without_transactions_are_included(self, temp_gnucash_file):
        """Accounts that have no transactions still appear (unlike transaction-driven export)."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_file) as repo:
            # Baseline: transaction-driven export finds nothing (no transactions)
            use_case = ExportTransactionsUseCase(repo)
            tx_driven = use_case.execute()
            assert tx_driven.accounts == [], "fixture should have no transactions"

            # execute_accounts_only must still find all accounts
            result = use_case.execute_accounts_only()

        assert len(result.accounts) > 0


class TestFormatAccountsOnly:
    """format_accounts_only stamps dates correctly and omits transactions."""

    def test_no_transaction_lines_in_output(self, temp_gnucash_file):
        """Output contains no transaction header lines (lines with ' * ')."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()
            output = use_case.format_accounts_only(result)

        assert " * " not in output

    def test_output_contains_open_declarations(self, temp_gnucash_file):
        """Output contains account open declarations for all accounts."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()
            output = use_case.format_accounts_only(result)

        assert "open Assets:Bank:Checking" in output
        assert "open Expenses:Groceries" in output
        assert "open Expenses:Dining" in output

    def test_output_contains_commodity_declarations(self, temp_gnucash_file):
        """Output contains commodity declarations."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()
            output = use_case.format_accounts_only(result)

        assert "commodity" in output
        assert "CAD" in output

    def test_as_of_date_stamped_on_open_lines(self, temp_gnucash_file):
        """When as_of_date is provided, every open line starts with that date."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        as_of = "2020-06-15"
        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()
            output = use_case.format_accounts_only(result, as_of_date=as_of)

        open_lines = [line for line in output.splitlines() if " open " in line]
        assert len(open_lines) > 0
        for line in open_lines:
            assert line.startswith(as_of), f"Expected {as_of} prefix, got: {line}"

    def test_as_of_date_stamped_on_commodity_lines(self, temp_gnucash_file):
        """When as_of_date is provided, every commodity line starts with that date."""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        as_of = "2020-06-15"
        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()
            output = use_case.format_accounts_only(result, as_of_date=as_of)

        commodity_lines = [line for line in output.splitlines() if " commodity " in line]
        assert len(commodity_lines) > 0
        for line in commodity_lines:
            assert line.startswith(as_of), f"Expected {as_of} prefix, got: {line}"

    def test_file_mtime_used_when_no_as_of_date(self, temp_gnucash_file):
        """When as_of_date is omitted, the date on open lines matches file mtime."""
        import datetime
        import os

        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_file) as repo:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()
            output = use_case.format_accounts_only(result)

        mtime = os.path.getmtime(temp_gnucash_file)
        expected_date = datetime.date.fromtimestamp(mtime).strftime("%Y-%m-%d")

        open_lines = [line for line in output.splitlines() if " open " in line]
        assert len(open_lines) > 0
        for line in open_lines:
            assert line.startswith(expected_date), f"Expected {expected_date} prefix, got: {line}"
