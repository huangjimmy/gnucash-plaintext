"""
Integration tests for the export-transaction CLI command.
"""

import pytest
from click.testing import CliRunner

from cli.export_transaction_cmd import export_transaction


class TestExportTransactionCLI:
    """Test export-transaction CLI command"""

    def test_missing_guid_prints_error(self, temp_gnucash_with_transactions):
        """Invoking without --guid must exit non-zero with a helpful message"""
        runner = CliRunner()
        result = runner.invoke(export_transaction, [temp_gnucash_with_transactions])

        assert result.exit_code != 0
        assert "--guid" in result.output

    def test_missing_gnucash_file_prints_error(self):
        """Invoking without a GnuCash file must exit non-zero"""
        runner = CliRunner()
        result = runner.invoke(export_transaction, ['--guid', 'deadbeefdeadbeefdeadbeefdeadbeef'])

        assert result.exit_code != 0
        assert "Missing input file" in result.output

    def test_nonexistent_gnucash_file_prints_error(self):
        """Invoking with a non-existent GnuCash file must exit non-zero"""
        runner = CliRunner()
        result = runner.invoke(export_transaction, [
            '/nonexistent/file.gnucash',
            '--guid', 'deadbeefdeadbeefdeadbeefdeadbeef'
        ])

        assert result.exit_code != 0

    def test_invalid_guid_format_prints_error(self, temp_gnucash_with_transactions):
        """A malformed GUID string must exit non-zero with an error message"""
        runner = CliRunner()
        result = runner.invoke(export_transaction, [
            temp_gnucash_with_transactions,
            '--guid', 'not-a-guid'
        ])

        assert result.exit_code != 0
        assert "Invalid GUID" in result.output

    def test_nonexistent_guid_prints_error(self, temp_gnucash_with_transactions):
        """A well-formed GUID that matches no transaction must exit non-zero"""
        runner = CliRunner()
        result = runner.invoke(export_transaction, [
            temp_gnucash_with_transactions,
            '--guid', 'deadbeefdeadbeefdeadbeefdeadbeef'
        ])

        assert result.exit_code != 0
        assert "No transaction found" in result.output

    def test_valid_guid_outputs_plaintext_to_stdout(self, temp_gnucash_with_transactions):
        """A valid GUID prints self-contained plaintext to stdout"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            all_result = use_case.execute()
            guid = all_result.transactions[0].GetGUID().to_string()

        runner = CliRunner()
        result = runner.invoke(export_transaction, [
            temp_gnucash_with_transactions,
            '--guid', guid
        ])

        assert result.exit_code == 0
        assert f'guid: "{guid}"' in result.output
        assert "commodity" in result.output
        assert "open " in result.output

    def test_valid_guid_with_flag_style_input(self, temp_gnucash_with_transactions):
        """--input flag works the same as positional argument"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            all_result = use_case.execute()
            guid = all_result.transactions[0].GetGUID().to_string()

        runner = CliRunner()
        result = runner.invoke(export_transaction, [
            '-i', temp_gnucash_with_transactions,
            '--guid', guid
        ])

        assert result.exit_code == 0
        assert f'guid: "{guid}"' in result.output

    def test_valid_guid_with_output_file(self, temp_gnucash_with_transactions, tmp_path):
        """When -o is given, output is written to file and confirmation printed"""
        import os

        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            all_result = use_case.execute()
            guid = all_result.transactions[0].GetGUID().to_string()

        output_path = str(tmp_path / "tx.txt")

        runner = CliRunner()
        result = runner.invoke(export_transaction, [
            temp_gnucash_with_transactions,
            '--guid', guid,
            '-o', output_path
        ])

        assert result.exit_code == 0
        assert "exported to" in result.output
        assert os.path.exists(output_path)

        with open(output_path) as f:
            content = f.read()
        assert f'guid: "{guid}"' in content
        assert "commodity" in content

    def test_output_contains_only_one_transaction_block(self, temp_gnucash_with_transactions):
        """Output contains exactly one transaction (not all 3 from the fixture)"""
        from repositories.gnucash_repository import GnuCashRepository
        from use_cases.export_transactions import ExportTransactionsUseCase

        with GnuCashRepository(temp_gnucash_with_transactions) as repo:
            use_case = ExportTransactionsUseCase(repo)
            all_result = use_case.execute()
            guid = all_result.transactions[0].GetGUID().to_string()

        runner = CliRunner()
        result = runner.invoke(export_transaction, [
            temp_gnucash_with_transactions,
            '--guid', guid
        ])

        assert result.exit_code == 0
        tx_headers = [
            line for line in result.output.splitlines()
            if line and not line.startswith('\t') and ' * ' in line
        ]
        assert len(tx_headers) == 1
