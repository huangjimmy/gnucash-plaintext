"""`validate` exists for books this tool did not write, and has to say so.

GnuCash balances every transaction it stores, so the checks that matter most —
a transaction whose splits do not sum to zero, one with no splits at all —
cannot be produced by importing anything. What produces them is what the
command is for: a book edited by hand, or written by another tool, or left
behind by a version of something that had a bug.

So these tests make one. A GnuCash book is gzipped XML; dropping a `<trn:split>`
from it is a plain text edit, and what comes back is a real book with a real
transaction that does not balance. Nothing is mocked and no code is bypassed —
the file is simply not one this tool wrote, which is the case in hand.
"""

import gzip
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = str(Path('tests/fixtures/account_balance_test_data.txt'))


@pytest.fixture
def book(tmp_path):
    """A book as this tool writes it: balanced, with a few empty descriptions."""
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER])
    assert result.exit_code == 0, result.output
    return path


@pytest.fixture
def broken(book):
    """The same book with one split taken out of one transaction."""
    text = gzip.decompress(book.read_bytes()).decode()
    text, count = re.subn(r'\s*<trn:split>.*?</trn:split>', '', text, count=1,
                          flags=re.DOTALL)
    assert count == 1, 'the book held no split to remove'
    book.write_bytes(gzip.compress(text.encode()))
    return book


class TestABookThatDoesNotBalance:
    def test_the_full_report_names_the_error(self, broken):
        result = CliRunner().invoke(cli, ['validate', str(broken)])

        assert result.exit_code != 0, result.output
        assert 'UNBALANCED' in result.output, result.output
        assert 'Ledger has errors' in result.output, result.output

    def test_the_quick_check_agrees(self, broken):
        result = CliRunner().invoke(cli, ['validate', str(broken), '--quick'])

        assert result.exit_code != 0, result.output
        assert 'Ledger has errors' in result.output, result.output

    def test_the_statistics_count_it(self, broken):
        result = CliRunner().invoke(cli, ['validate', str(broken), '--stats'])

        assert result.exit_code == 0, result.output
        assert '1 error(s)' in result.output, result.output
        assert 'warning(s)' in result.output, result.output

    def test_the_report_can_be_written_to_a_file(self, broken, tmp_path):
        report = tmp_path / 'report.txt'
        result = CliRunner().invoke(
            cli, ['validate', str(broken), '--report', str(report)])

        assert f'Report saved to {report}' in result.output, result.output
        assert 'UNBALANCED' in report.read_text(), report.read_text()


class TestABookThatIsMerelyUntidy:
    """Warnings are not errors: a book with empty descriptions is still valid."""

    def test_it_is_called_valid_and_the_warnings_are_said(self, book):
        result = CliRunner().invoke(cli, ['validate', str(book)])

        assert result.exit_code == 0, result.output
        assert 'valid but has warnings' in result.output, result.output

    def test_the_quick_check_calls_it_valid(self, book):
        result = CliRunner().invoke(cli, ['validate', str(book), '--quick'])

        assert result.exit_code == 0, result.output
        assert 'Ledger is valid' in result.output, result.output

    def test_the_statistics_call_it_valid(self, book):
        result = CliRunner().invoke(cli, ['validate', str(book), '--stats'])

        assert result.exit_code == 0, result.output
        assert 'Valid (no errors)' in result.output, result.output
        assert 'warning(s)' in result.output, result.output
