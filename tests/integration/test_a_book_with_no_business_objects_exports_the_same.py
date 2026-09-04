"""`--include-business-objects` over a book that has none writes a usable file.

The flag decides which sections are assembled, and a book with no customers,
vendors, invoices, bills or tax tables has an empty middle section. Both paths
carry the same content — the accounts section emits the commodities either way
— but they are assembled differently now, so the one that used to be taken only
by business-object books is now taken by every book run with the flag.

What matters is that the file still reads back. Blank lines between sections
are not nothing to a format that indents by tab and separates by them.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.conftest import a_ledger_without_the_day_it_was_written

LEDGER = 'tests/fixtures/a_plain_transaction_to_edit.txt'
ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


@pytest.fixture
def book_with_only_transactions(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'plain.gnucash'
    assert runner.invoke(cli, ['import', '--new', str(book),
                               ACCOUNTS]).exit_code == 0
    result = runner.invoke(cli, ['import', str(book), LEDGER])
    assert result.exit_code == 0, result.output
    return book


class TestWithTheFlag:
    def test_it_exports(self, book_with_only_transactions, tmp_path):
        out = tmp_path / 'with.txt'
        result = CliRunner().invoke(cli, [
            'export', str(book_with_only_transactions), str(out),
            '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'Expenses:Supplies 40.00 CAD' in out.read_text()

    def test_what_it_writes_reads_back(self, book_with_only_transactions,
                                       tmp_path):
        """The blank line where the business objects would have gone."""
        runner = CliRunner()
        out = tmp_path / 'with.txt'
        assert runner.invoke(cli, [
            'export', str(book_with_only_transactions), str(out),
            '--include-business-objects']).exit_code == 0

        rebuilt = tmp_path / 'rebuilt.gnucash'
        result = runner.invoke(cli, ['import', '--new', str(rebuilt), str(out),
                                     '--include-business-objects'])
        assert result.exit_code == 0, result.output

        again = tmp_path / 'again.txt'
        assert runner.invoke(cli, [
            'export', str(rebuilt), str(again),
            '--include-business-objects']).exit_code == 0
        # Without the day each was written on: an account and a commodity
        # have no date of their own, so the export stamps the day it runs,
        # and two exports either side of midnight differ over that alone.
        assert a_ledger_without_the_day_it_was_written(again.read_text()) == \
            a_ledger_without_the_day_it_was_written(out.read_text())

    def test_it_says_what_the_bare_export_says(self, book_with_only_transactions,
                                               tmp_path):
        """Every directive of the one, in the other — the flag adds no content
        to a book that has no business objects, so nothing may go missing
        between the two ways of assembling it."""
        runner = CliRunner()
        bare = tmp_path / 'bare.txt'
        withflag = tmp_path / 'with.txt'
        assert runner.invoke(cli, [
            'export', str(book_with_only_transactions), str(bare),
            '--all-accounts']).exit_code == 0
        assert runner.invoke(cli, [
            'export', str(book_with_only_transactions), str(withflag),
            '--include-business-objects']).exit_code == 0

        def _directives(path: Path):
            return [line for line in path.read_text().splitlines() if line.strip()]

        assert _directives(withflag) == _directives(bare)
