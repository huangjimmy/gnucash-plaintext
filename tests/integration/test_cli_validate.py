"""
Integration tests for validate CLI command

These tests verify the CLI command works end-to-end.
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from cli.validate_cmd import validate_ledger


class TestValidateCLI:
    """Test validate CLI command"""

    def test_validate_basic(self, temp_gnucash_with_transactions):
        """Test basic validate command"""
        runner = CliRunner()

        result = runner.invoke(validate_ledger, [
            temp_gnucash_with_transactions
        ])

        assert result.exit_code == 0
        assert "Ledger is valid" in result.output

    def test_validate_quick(self, temp_gnucash_with_transactions):
        """Test quick validation"""
        runner = CliRunner()

        result = runner.invoke(validate_ledger, [
            temp_gnucash_with_transactions,
            '--quick'
        ])

        assert result.exit_code == 0
        assert "Ledger is valid" in result.output

    def test_validate_with_stats(self, temp_gnucash_with_transactions):
        """Test validation with statistics"""
        runner = CliRunner()

        result = runner.invoke(validate_ledger, [
            temp_gnucash_with_transactions,
            '--stats'
        ])

        assert result.exit_code == 0
        assert "Ledger Statistics" in result.output
        assert "Accounts:" in result.output
        assert "Transactions:" in result.output

    def test_validate_with_report(self, temp_gnucash_with_transactions):
        """Test validation with report output"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            report_path = f.name

        try:
            result = runner.invoke(validate_ledger, [
                temp_gnucash_with_transactions,
                '--report', report_path
            ])

            assert result.exit_code == 0
            assert os.path.exists(report_path)
            assert "Report saved" in result.output

            # Verify report content
            with open(report_path) as f:
                content = f.read()
                assert "VALIDATION REPORT" in content

        finally:
            if os.path.exists(report_path):
                os.unlink(report_path)

    def test_validate_nonexistent_file(self):
        """Test validate with nonexistent file"""
        runner = CliRunner()

        result = runner.invoke(validate_ledger, [
            '/nonexistent/file.gnucash'
        ])

        assert result.exit_code != 0

    def test_validate_with_flag(self, temp_gnucash_with_transactions):
        """Test validate using -i flag instead of positional argument"""
        runner = CliRunner()

        result = runner.invoke(validate_ledger, [
            '-i', temp_gnucash_with_transactions
        ])

        assert result.exit_code == 0
        assert "Ledger is valid" in result.output

    def test_validate_with_flag_quick(self, temp_gnucash_with_transactions):
        """Test validate using --input flag with --quick option"""
        runner = CliRunner()

        result = runner.invoke(validate_ledger, [
            '--input', temp_gnucash_with_transactions,
            '--quick'
        ])

        assert result.exit_code == 0
        assert "Ledger is valid" in result.output

    def test_validate_with_flag_stats(self, temp_gnucash_with_transactions):
        """Test validate using -i flag with --stats option"""
        runner = CliRunner()

        result = runner.invoke(validate_ledger, [
            '-i', temp_gnucash_with_transactions,
            '--stats'
        ])

        assert result.exit_code == 0
        assert "Ledger Statistics" in result.output
        assert "Accounts:" in result.output
        assert "Transactions:" in result.output

    def test_validate_missing_file(self):
        """Test validate with missing file"""
        runner = CliRunner()

        result = runner.invoke(validate_ledger, [])

        assert result.exit_code != 0
        assert "Missing GnuCash file" in result.output
