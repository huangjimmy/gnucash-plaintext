"""Integration tests for the print-bill CLI command (Q-019).

Mirrors test_cli_print_invoice.py for the vendor-bill side: argument
validation, error-path exit codes, error-message format.
"""
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')


class TestPrintBillErrors:

    def _book_with_accounts(self, tmp_path):
        runner = CliRunner()
        gnc = tmp_path / 'book.gnucash'
        r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
        assert r.exit_code == 0, f'accounts: {r.output}'
        return gnc

    def test_no_selectors_exits_2(self, tmp_path):
        """Calling print-bill with no selectors of any kind exits with
        Click UsageError exit code 2."""
        gnc = self._book_with_accounts(tmp_path)
        runner = CliRunner()
        r = runner.invoke(cli, [
            'print-bill', str(gnc),
            '-o', str(tmp_path / 'out.txt'),
            '--format', 'plaintext',
        ])
        assert r.exit_code == 2

    def test_nonexistent_bill_id_exits_nonzero(self, tmp_path):
        """A bill ID that does not exist in the book exits non-zero."""
        gnc = self._book_with_accounts(tmp_path)
        runner = CliRunner()
        r = runner.invoke(cli, [
            'print-bill', str(gnc), 'BILL-DOES-NOT-EXIST',
            '-o', str(tmp_path / 'out.txt'),
            '--format', 'plaintext',
        ])
        assert r.exit_code != 0

    def test_no_match_error_message_has_balanced_parens(self, tmp_path):
        """The "no bills matched the selection (…)" message must have
        balanced parentheses. The original pattern
        `'(' + ', '.join(c) if c else 'none' + ')'` parses as
        `('(' + ', '.join(c)) if c else ('none' + ')')` — when criteria
        are present (always, given upfront validation) the closing
        paren is dropped from the message."""
        gnc = self._book_with_accounts(tmp_path)
        runner = CliRunner()
        r = runner.invoke(cli, [
            'print-bill', str(gnc), 'BILL-DOES-NOT-EXIST',
            '-o', str(tmp_path / 'out.txt'),
            '--format', 'plaintext',
        ])
        assert r.exit_code != 0
        assert 'no bills matched the selection (' in r.output, (
            f'unexpected message:\n{r.output}'
        )
        assert r.output.count('(') == r.output.count(')'), (
            f'unbalanced parentheses in error message:\n{r.output}'
        )
