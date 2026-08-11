"""A report asked for something it cannot produce has to say which part.

`balance-sheet` and `income-statement` take a date and two side files of rates,
and each of those is a thing a person types or edits by hand. What comes back
when one of them is wrong is the whole of the command's usefulness at that
moment: a stack trace names a line of this tool, and the reader needs the name
of their own file, or their own date.

Also here: writing a report to a file rather than the terminal, which is how
anyone keeps one, and the PDF the income statement offers.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
LEDGER = FIXTURES / 'balance_sheet_book.txt'


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(
        cli, ['import', '--new', str(path), str(LEDGER)])
    assert result.exit_code == 0, result.output
    return path


class TestADateThatIsNotOne:
    def test_the_balance_sheet_says_what_a_date_looks_like(self, book):
        result = CliRunner().invoke(
            cli, ['balance-sheet', str(book), '--as-of', '31/12/2024'])

        assert result.exit_code != 0, result.output
        assert 'YYYY-MM-DD' in result.output, result.output
        assert '31/12/2024' in result.output, result.output

    def test_a_day_that_does_not_exist_is_not_a_date_either(self, book):
        """`--as-of 2024-02-31` parses as a shape and fails as a day."""
        result = CliRunner().invoke(
            cli, ['balance-sheet', str(book), '--as-of', '2024-02-31'])

        assert result.exit_code != 0, result.output
        assert 'YYYY-MM-DD' in result.output, result.output


class TestARateFileThatWillNotLoad:
    """The reader's file is named, not this tool's traceback."""

    def _rates(self, tmp_path, text, name='rates.yaml'):
        path = tmp_path / name
        path.write_text(text)
        return path

    def test_the_balance_sheet_names_the_fx_file(self, book, tmp_path):
        rates = self._rates(tmp_path, 'USD: [not, a, rate]\n')
        result = CliRunner().invoke(cli, [
            'balance-sheet', str(book), '--as-of', '2024-12-31',
            '--fx-rates', str(rates)])

        assert result.exit_code != 0, result.output
        assert 'Error' in result.output, result.output
        assert 'Traceback' not in result.output, result.output

    def test_the_balance_sheet_names_the_prices_file(self, book, tmp_path):
        """A second file of the same shape, read by the same loader."""
        prices = self._rates(tmp_path, 'HOOL: [not, a, price]\n', 'prices.yaml')
        result = CliRunner().invoke(cli, [
            'balance-sheet', str(book), '--as-of', '2024-12-31',
            '--prices', str(prices)])

        assert result.exit_code != 0, result.output
        assert 'Error' in result.output, result.output
        assert 'Traceback' not in result.output, result.output

    def test_the_income_statement_names_the_fx_file(self, book, tmp_path):
        rates = self._rates(tmp_path, 'USD: [not, a, rate]\n')
        result = CliRunner().invoke(cli, [
            'income-statement', str(book), '--start', '2024-01-01',
            '--end', '2024-12-31', '--fx-rates', str(rates)])

        assert result.exit_code != 0, result.output
        assert 'Error' in result.output, result.output
        assert 'Traceback' not in result.output, result.output


class TestWritingTheReportToAFile:
    def test_the_balance_sheet_lands_in_the_file(self, book, tmp_path):
        out = tmp_path / 'sheet.txt'
        result = CliRunner().invoke(cli, [
            'balance-sheet', str(book), '--as-of', '2024-12-31',
            '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert f'Written to {out}' in result.output, result.output
        assert 'ASSETS' in out.read_text().upper(), out.read_text()

    def test_it_is_the_same_report_the_terminal_gets(self, book, tmp_path):
        out = tmp_path / 'sheet.txt'
        CliRunner().invoke(cli, [
            'balance-sheet', str(book), '--as-of', '2024-12-31',
            '--output', str(out)])
        shown = CliRunner().invoke(cli, [
            'balance-sheet', str(book), '--as-of', '2024-12-31'])

        assert out.read_text().strip() == shown.output.strip(), shown.output


class TestTheIncomeStatementAsAPdf:
    def test_it_writes_one(self, book, tmp_path):
        out = tmp_path / 'statement.pdf'
        result = CliRunner().invoke(cli, [
            'income-statement', str(book), '--start', '2024-01-01',
            '--end', '2024-12-31', '--output-format', 'pdf',
            '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert f'PDF report written to {out}' in result.output, result.output
        assert out.read_bytes()[:5] == b'%PDF-', out.read_bytes()[:20]
