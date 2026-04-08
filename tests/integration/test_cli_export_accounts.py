"""
Integration tests for the export-accounts CLI command.

Verifies end-to-end behaviour of:
    gnucash-plaintext export-accounts <file> <output> [--as-of DATE]
"""

import os
import tempfile

from click.testing import CliRunner

from cli.export_accounts_cmd import export_accounts


class TestExportAccountsCLI:
    """Integration tests for the export-accounts command."""

    def test_basic_export(self, temp_gnucash_file):
        """Command exits 0 and writes account declarations to the output file."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(export_accounts, [temp_gnucash_file, output_path])

            assert result.exit_code == 0, result.output
            assert os.path.exists(output_path)

            with open(output_path) as f:
                content = f.read()

            assert "open Assets:Bank:Checking" in content
            assert "open Expenses:Groceries" in content
            assert "open Expenses:Dining" in content
            assert "commodity" in content

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_no_transaction_lines_in_output(self, temp_gnucash_with_transactions):
        """Output never contains transaction header lines even when the book has transactions."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(
                export_accounts, [temp_gnucash_with_transactions, output_path]
            )

            assert result.exit_code == 0, result.output

            with open(output_path) as f:
                content = f.read()

            assert " * " not in content

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_as_of_date_applied(self, temp_gnucash_file):
        """--as-of DATE stamps every open and commodity line with the given date."""
        runner = CliRunner()
        as_of = "2019-03-01"
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(
                export_accounts, [temp_gnucash_file, output_path, '--as-of', as_of]
            )

            assert result.exit_code == 0, result.output

            with open(output_path) as f:
                content = f.read()

            open_lines = [line for line in content.splitlines() if " open " in line]
            commodity_lines = [line for line in content.splitlines() if " commodity " in line]

            assert len(open_lines) > 0
            assert len(commodity_lines) > 0

            for line in open_lines + commodity_lines:
                assert line.startswith(as_of), f"Expected {as_of} prefix, got: {line}"

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_all_accounts_exported_but_no_transactions(self, temp_gnucash_with_transactions):
        """All accounts are present in output but transaction lines are absent."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(
                export_accounts, [temp_gnucash_with_transactions, output_path]
            )

            assert result.exit_code == 0, result.output

            with open(output_path) as f:
                content = f.read()

            # All accounts must be present
            assert "open Assets:Bank:Checking" in content
            assert "open Expenses:Groceries" in content
            assert "open Expenses:Dining" in content

            # Transaction content must not appear
            assert " * " not in content
            assert "Grocery shopping" not in content
            assert "Restaurant" not in content

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_success_message_shows_counts(self, temp_gnucash_file):
        """Success output reports account and commodity counts."""
        runner = CliRunner()
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            output_path = f.name

        try:
            result = runner.invoke(export_accounts, [temp_gnucash_file, output_path])

            assert result.exit_code == 0, result.output
            assert "account" in result.output
            assert "commodity" in result.output

        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_nonexistent_input_file_errors(self):
        """Command fails with a clear error when the input file does not exist."""
        runner = CliRunner()
        result = runner.invoke(
            export_accounts, ['/nonexistent/file.gnucash', '/tmp/out.txt']
        )

        assert result.exit_code != 0
