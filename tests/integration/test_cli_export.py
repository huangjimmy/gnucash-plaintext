"""
Integration tests for export CLI command

These tests verify the CLI command works end-to-end.
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from cli.export_cmd import export_transactions


class TestExportCLI:
    """Test export CLI command"""

    def test_export_basic(self, temp_gnucash_with_transactions):
        """Test basic export command"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(export_transactions, [
                temp_gnucash_with_transactions,
                output_path
            ])

            assert result.exit_code == 0
            assert "Exported 3 transaction(s)" in result.output
            assert os.path.exists(output_path)

            # Verify file content
            with open(output_path) as f:
                content = f.read()
                assert "2024-01-15" in content
                assert "Grocery shopping" in content

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_export_with_date_range(self, temp_gnucash_with_transactions):
        """Test export with date range still exports all commodities and accounts"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(export_transactions, [
                temp_gnucash_with_transactions,
                output_path,
                '--start-date', '2024-01-15',
                '--end-date', '2024-01-20'
            ])

            assert result.exit_code == 0
            assert "Exported 2 transaction(s)" in result.output

            # CRITICAL: Even with date filter, should export ALL commodities and accounts
            with open(output_path) as f:
                content = f.read()
                # Should have commodity declarations
                assert "commodity" in content
                # Should have ALL account declarations (not just those in the 2 transactions)
                assert "open Assets:Bank:Checking" in content
                assert "open Expenses:Groceries" in content
                assert "open Expenses:Dining" in content  # Even though not in filtered transactions!

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_export_with_account_filter(self, temp_gnucash_with_transactions):
        """Test export with account filter still exports all commodities and accounts"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(export_transactions, [
                temp_gnucash_with_transactions,
                output_path,
                '--account', 'Expenses:Groceries'
            ])

            assert result.exit_code == 0
            assert "Exported 2 transaction(s)" in result.output

            # CRITICAL: Even with account filter, should export ALL commodities and accounts
            with open(output_path) as f:
                content = f.read()
                # Should have commodity declarations
                assert "commodity" in content
                # Should have ALL account declarations (not just Groceries!)
                assert "open Assets:Bank:Checking" in content
                assert "open Expenses:Groceries" in content
                assert "open Expenses:Dining" in content  # Even though not in filtered transactions!

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_export_nonexistent_file(self):
        """Test export with nonexistent file"""
        runner = CliRunner()

        result = runner.invoke(export_transactions, [
            '/nonexistent/file.gnucash',
            '/tmp/output.txt'
        ])

        assert result.exit_code != 0

    def test_export_with_flags(self, temp_gnucash_with_transactions):
        """Test export using -i/-o flags instead of positional arguments"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(export_transactions, [
                '-i', temp_gnucash_with_transactions,
                '-o', output_path
            ])

            assert result.exit_code == 0
            assert "Exported 3 transaction(s)" in result.output
            assert os.path.exists(output_path)

            # Verify file content
            with open(output_path) as f:
                content = f.read()
                assert "2024-01-15" in content
                assert "Grocery shopping" in content

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_export_with_flags_and_filters(self, temp_gnucash_with_transactions):
        """Test export using flags with date range filter"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(export_transactions, [
                '--input', temp_gnucash_with_transactions,
                '--output', output_path,
                '--start-date', '2024-01-15',
                '--end-date', '2024-01-20'
            ])

            assert result.exit_code == 0
            assert "Exported 2 transaction(s)" in result.output

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_export_missing_input(self):
        """Test export with missing input file"""
        runner = CliRunner()

        result = runner.invoke(export_transactions, [
            '-o', '/tmp/output.txt'
        ])

        assert result.exit_code != 0
        assert "Missing input file" in result.output

    def test_export_missing_output(self, temp_gnucash_with_transactions):
        """Test export with missing output file"""
        runner = CliRunner()

        result = runner.invoke(export_transactions, [
            '-i', temp_gnucash_with_transactions
        ])

        assert result.exit_code != 0
        assert "Missing output file" in result.output

    def test_export_all_accounts_no_transactions(self, temp_gnucash_file):
        """With --all-accounts, accounts-only file produces all account declarations"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(export_transactions, [
                '--all-accounts',
                temp_gnucash_file,
                output_path
            ])

            assert result.exit_code == 0
            assert "Exported 0 transaction(s)" in result.output

            with open(output_path) as f:
                content = f.read()

            assert "open Assets" in content
            assert "open Assets:Bank" in content
            assert "open Assets:Bank:Checking" in content
            assert "open Expenses" in content
            assert "open Expenses:Groceries" in content
            assert "open Expenses:Dining" in content
            assert "commodity" in content

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_export_all_accounts_with_transactions(self, temp_gnucash_with_transactions):
        """With --all-accounts, all accounts and all transactions are exported"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(export_transactions, [
                '--all-accounts',
                temp_gnucash_with_transactions,
                output_path
            ])

            assert result.exit_code == 0
            assert "Exported 3 transaction(s)" in result.output

            with open(output_path) as f:
                content = f.read()

            assert "open Assets:Bank:Checking" in content
            assert "open Expenses:Groceries" in content
            assert "open Expenses:Dining" in content
            assert "Grocery shopping" in content

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_export_default_still_transaction_driven(self, temp_gnucash_file):
        """Without --all-accounts, accounts-only file produces empty output"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(export_transactions, [
                temp_gnucash_file,
                output_path
            ])

            assert result.exit_code == 0
            assert "Exported 0 transaction(s)" in result.output

            with open(output_path) as f:
                content = f.read()

            assert content == ""

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)
