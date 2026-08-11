"""Importing a ledger the book already holds must change nothing, and say so.

`import` is meant to be run again — against a file that grew a few
transactions, or one that did not. What the summary counts is what the book
gained: transactions matched by GUID are skipped, commodities already there
are neither created nor updated, and accounts already there are not created
either.

Counted per `open` directive instead, the last of those reported every account
in the file on every run. The number was wrong, and `has_changes` reads it —
so an unchanged re-import printed `✓ Changes saved` and wrote the book out
again, and `✓ Nothing to import` could not be reached by any ledger that opens
an account. With `--include-business-objects` it happened on every run, since
the pre-pass creates the accounts before the pass that counts them.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = str(Path('tests/fixtures/account_balance_test_data.txt'))


@pytest.fixture
def book(tmp_path):
    """A book built from the ledger, so the ledger describes it exactly."""
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER])
    assert result.exit_code == 0, result.output
    return path


class TestTheSecondRun:
    def _again(self, book):
        result = CliRunner().invoke(cli, ['import', str(book), LEDGER])
        assert result.exit_code == 0, result.output
        return result

    def test_it_creates_no_accounts(self, book):
        result = self._again(book)

        assert 'Accounts:     0' in result.output, result.output

    def test_it_creates_no_commodities(self, book):
        result = self._again(book)

        assert 'Commodities:  0 created, 0 updated' in result.output, \
            result.output

    def test_it_says_there_was_nothing_to_import(self, book):
        result = self._again(book)

        assert 'Nothing to import' in result.output, result.output
        assert 'Changes saved' not in result.output, result.output

    def test_the_first_run_still_counts_what_it_created(self, tmp_path):
        """The count is of accounts gained, and a new book gains them all."""
        fresh = tmp_path / 'fresh.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(fresh), LEDGER])

        assert result.exit_code == 0, result.output
        assert 'Accounts:     0' not in result.output, result.output


class TestWithBusinessObjects:
    """Accounts are opened before the business objects that reference them.

    That step is what makes them, so the transaction pass finds them all
    present and answers "created nothing" — truthfully. Left there, the
    summary said no accounts on a run that made a book of them, and
    `has_changes` read the same and saved nothing, so the accounts were lost
    on session end.
    """

    BUSINESS = str(Path('tests/fixtures/business_objects.txt'))

    def test_the_accounts_it_made_are_counted_and_kept(self, tmp_path):
        book = tmp_path / 'biz.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(book), self.BUSINESS,
            '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'Accounts:     0' not in result.output, result.output
        assert 'Changes saved' in result.output, result.output

        out = tmp_path / 'check.txt'
        after = CliRunner().invoke(cli, ['export', str(book), str(out)])
        assert after.exit_code == 0, after.output
        assert 'open Assets' in out.read_text(), out.read_text()

    def test_the_second_run_saves_nothing(self, tmp_path):
        """The whole point of the counters, on the path that has documents.

        `has_changes` read `biz_objects_imported`, which counts the
        *directives* a file carries rather than what the book did about them —
        so a ledger with one customer and one invoice, unchanged, reported
        `customer "C1": unchanged`, `invoice "INV-001": unchanged`, and then
        saved the book anyway. Every run, with a fresh timestamped backup, and
        two runs in one second meet `ERR_FILEIO_BACKUP_ERROR`.
        """
        runner = CliRunner()
        book = tmp_path / 'biz.gnucash'
        first = runner.invoke(cli, [
            'import', '--new', str(book), self.BUSINESS,
            '--include-business-objects'])
        assert first.exit_code == 0, first.output

        again = runner.invoke(cli, ['import', str(book), self.BUSINESS,
                                    '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'Changes saved' not in again.output, again.output

    def test_it_says_the_objects_were_unchanged(self, tmp_path):
        """Which is what makes the run above a run with nothing to save."""
        runner = CliRunner()
        book = tmp_path / 'biz.gnucash'
        assert runner.invoke(cli, [
            'import', '--new', str(book), self.BUSINESS,
            '--include-business-objects']).exit_code == 0

        again = runner.invoke(cli, ['import', str(book), self.BUSINESS,
                                    '--include-business-objects'])

        assert 'unchanged' in again.output, again.output
