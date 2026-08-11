"""A run that refused something must not sign off with a tick.

When nothing reached the book, the summary ends `✓ Nothing to import` — which
is the right thing to say about a ledger the book already holds. It was said
about a refusal too: a file whose every transaction was rejected printed its
errors, then a tick, then exited 1. The exit code is right and the last line a
reader sees says the opposite.

"Nothing to import" and "nothing could be imported" are different answers, and
the tick belongs only to the first.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
WHOLE = str(FIXTURES / 'a_transaction_to_be_cut_short.txt')
CUT = str(FIXTURES / 'a_transaction_block_cut_short.txt')


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(path), WHOLE])
    assert result.exit_code == 0, result.output
    return path


class TestARunThatRefused:
    def _refused(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), CUT, '--strategy', 'update'])
        assert result.exit_code != 0, result.output
        return result

    def test_it_does_not_tick(self, book):
        result = self._refused(book)

        assert '✓ Nothing to import' not in result.output, result.output

    def test_it_says_nothing_could_be_imported(self, book):
        result = self._refused(book)

        assert 'Nothing was imported' in result.output, result.output


class TestADryRunThatRefused:
    """The same contradiction one branch over.

    A dry run reports what would happen, and what would happen here is a
    refusal — so it printed its errors, ticked, and exited 1.
    """

    def _refused(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), CUT, '--strategy', 'update', '--dry-run'])
        assert result.exit_code != 0, result.output
        return result

    def test_it_does_not_tick(self, book):
        result = self._refused(book)

        assert '✓ Dry run complete' not in result.output, result.output

    def test_it_says_what_it_would_have_refused(self, book):
        result = self._refused(book)

        assert 'no splits in this file' in result.output, result.output


class TestADryRunWithNothingWrong:
    def test_it_still_ticks(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), WHOLE, '--dry-run'])

        assert result.exit_code == 0, result.output
        assert '✓ Dry run complete' in result.output, result.output


class TestARunWithNothingToDo:
    def test_it_still_ticks(self, book):
        """The ordinary case: a ledger the book already holds."""
        result = CliRunner().invoke(cli, ['import', str(book), WHOLE])

        assert result.exit_code == 0, result.output
        assert '✓ Nothing to import' in result.output, result.output
