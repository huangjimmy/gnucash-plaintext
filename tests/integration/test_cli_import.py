"""
Integration tests for import CLI command

These tests verify the CLI command works end-to-end.
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from cli.import_cmd import import_transactions


class TestImportCLI:
    """Test import CLI command"""

    def test_import_basic(self, temp_gnucash_file):
        """Test basic import command with full GnuCash format"""
        runner = CliRunner()

        # Create plaintext file to import with full format
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            # Commodity declaration
            f.write("2024-02-15 commodity CAD\n")
            f.write('\tmnemonic: "CAD"\n')
            f.write('\tfullname: "Canadian Dollar"\n')
            f.write('\tnamespace: "CURRENCY"\n')
            f.write('\tfraction: 100\n')
            # Transaction
            f.write('2024-02-15 * "Test transaction"\n')
            f.write('\tExpenses:Groceries 50.00 CAD\n')
            f.write('\tAssets:Bank:Checking -50.00 CAD\n')
            input_path = f.name

        try:
            result = runner.invoke(import_transactions, [
                temp_gnucash_file,
                input_path
            ])

            assert result.exit_code == 0
            assert "Transactions: 1" in result.output
            assert "Changes saved" in result.output

        finally:
            if os.path.exists(input_path):
                os.unlink(input_path)

    def test_import_dry_run(self, temp_gnucash_file):
        """Test import with dry run"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            # Full format with commodity
            f.write("2024-02-15 commodity CAD\n")
            f.write('\tmnemonic: "CAD"\n')
            f.write('\tfullname: "Canadian Dollar"\n')
            f.write('\tnamespace: "CURRENCY"\n')
            f.write('\tfraction: 100\n')
            f.write('2024-02-15 * "Test"\n')
            f.write('\tExpenses:Groceries 50.00 CAD\n')
            f.write('\tAssets:Bank:Checking -50.00 CAD\n')
            input_path = f.name

        try:
            result = runner.invoke(import_transactions, [
                temp_gnucash_file,
                input_path,
                '--dry-run'
            ])

            assert result.exit_code == 0
            assert "Dry run" in result.output
            assert "no changes made" in result.output

        finally:
            if os.path.exists(input_path):
                os.unlink(input_path)

    def test_import_with_strategy(self, temp_gnucash_file):
        """Test import with resolution strategy"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            # Full format with commodity
            f.write("2024-02-15 commodity CAD\n")
            f.write('\tmnemonic: "CAD"\n')
            f.write('\tfullname: "Canadian Dollar"\n')
            f.write('\tnamespace: "CURRENCY"\n')
            f.write('\tfraction: 100\n')
            f.write('2024-02-15 * "Test"\n')
            f.write('\tExpenses:Groceries 50.00 CAD\n')
            f.write('\tAssets:Bank:Checking -50.00 CAD\n')
            input_path = f.name

        try:
            result = runner.invoke(import_transactions, [
                temp_gnucash_file,
                input_path,
                '--strategy', 'skip'
            ])

            assert result.exit_code == 0

        finally:
            if os.path.exists(input_path):
                os.unlink(input_path)

    def test_import_nonexistent_file(self):
        """Test import with nonexistent file"""
        runner = CliRunner()

        result = runner.invoke(import_transactions, [
            '/nonexistent/file.gnucash',
            '/nonexistent/input.txt'
        ])

        assert result.exit_code != 0

    def test_import_with_flags(self, temp_gnucash_file):
        """Test import using -i/-f flags instead of positional arguments"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            # Full format with commodity
            f.write("2024-02-15 commodity CAD\n")
            f.write('\tmnemonic: "CAD"\n')
            f.write('\tfullname: "Canadian Dollar"\n')
            f.write('\tnamespace: "CURRENCY"\n')
            f.write('\tfraction: 100\n')
            f.write('2024-02-15 * "Test transaction"\n')
            f.write('\tExpenses:Groceries 50.00 CAD\n')
            f.write('\tAssets:Bank:Checking -50.00 CAD\n')
            input_path = f.name

        try:
            result = runner.invoke(import_transactions, [
                '-i', temp_gnucash_file,
                '-f', input_path
            ])

            assert result.exit_code == 0
            assert "Transactions: 1" in result.output
            assert "Changes saved" in result.output

        finally:
            if os.path.exists(input_path):
                os.unlink(input_path)

    def test_import_with_flags_and_options(self, temp_gnucash_file):
        """Test import using flags with strategy and dry-run"""
        runner = CliRunner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("2024-02-15 commodity CAD\n")
            f.write('\tmnemonic: "CAD"\n')
            f.write('\tfullname: "Canadian Dollar"\n')
            f.write('\tnamespace: "CURRENCY"\n')
            f.write('\tfraction: 100\n')
            f.write('2024-02-15 * "Test"\n')
            f.write('\tExpenses:Groceries 50.00 CAD\n')
            f.write('\tAssets:Bank:Checking -50.00 CAD\n')
            input_path = f.name

        try:
            result = runner.invoke(import_transactions, [
                '--input', temp_gnucash_file,
                '--file', input_path,
                '--strategy', 'keep-existing',
                '--dry-run'
            ])

            assert result.exit_code == 0
            assert "Dry run" in result.output

        finally:
            if os.path.exists(input_path):
                os.unlink(input_path)

    def test_import_missing_gnucash_file(self):
        """Test import with missing GnuCash file"""
        runner = CliRunner()

        # Create a temp file that exists (so we only test missing gnucash file)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("test")
            input_path = f.name

        try:
            result = runner.invoke(import_transactions, [
                '-f', input_path
            ])

            assert result.exit_code != 0
            assert "Missing GnuCash file" in result.output

        finally:
            if os.path.exists(input_path):
                os.unlink(input_path)

    def test_import_missing_plaintext_file(self, temp_gnucash_file):
        """Test import with missing plaintext file"""
        runner = CliRunner()

        result = runner.invoke(import_transactions, [
            '-i', temp_gnucash_file
        ])

        assert result.exit_code != 0
        assert "Missing plaintext file" in result.output
