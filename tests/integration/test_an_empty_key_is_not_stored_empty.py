"""`key: ""` removes a custom key, on a new transaction as on an old one.

README states one rule for every block: `key: "value"` sets, `key: ""` clears,
and a line that is absent says nothing. Clearing a custom key means the key is
gone — there is no such thing as a custom key whose value is the empty string,
because nothing could tell it from one that was never written.

Owners, invoices and bills have always kept that rule: they merge through one
function that pops an empty value whichever path they arrive on. Transactions
and splits read it as "not None", so an empty value was stored on a book that
did not yet hold the transaction, and removed on a book that did. The two
answers are the visible cost: the export writes back a line nobody typed, and
the same ledger builds a different book depending on which book it meets — so a
create, export and re-import never settles.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = str(Path('tests/fixtures/a_transaction_naming_a_key_empty.txt'))


def _import_new(tmp_path, name='book.gnucash'):
    book = tmp_path / name
    result = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    assert result.exit_code == 0, result.output
    return book


def _export(book, tmp_path, name='out.txt'):
    out = tmp_path / name
    result = CliRunner().invoke(cli, ['export', str(book), str(out)])
    assert result.exit_code == 0, result.output
    return out.read_text()


class TestOnABookThatDidNotHaveIt:
    def test_the_cleared_key_is_not_written_back(self, tmp_path):
        text = _export(_import_new(tmp_path), tmp_path)

        assert 'department:' not in text, text

    def test_the_cleared_split_key_is_not_written_back(self, tmp_path):
        text = _export(_import_new(tmp_path), tmp_path)

        assert 'project:' not in text, text

    def test_the_key_that_was_given_a_value_is_kept(self, tmp_path):
        """Clearing one key says nothing about the others."""
        text = _export(_import_new(tmp_path), tmp_path)

        assert 'region: "west"' in text, text


class TestTheCycleSettles:
    def test_exporting_and_re_importing_gives_the_same_file(self, tmp_path):
        """The export is a ledger; reading it back must produce the book it
        was written from, or the file and the book drift apart for good."""
        first = _export(_import_new(tmp_path), tmp_path, 'first.txt')

        again = tmp_path / 'again.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(again), str(tmp_path / 'first.txt')])
        assert result.exit_code == 0, result.output
        second = _export(again, tmp_path, 'second.txt')

        assert first == second, f'--- first ---\n{first}\n--- second ---\n{second}'

    def test_importing_the_same_ledger_twice_changes_nothing(self, tmp_path):
        """The create path and the update path have to answer `key: ""` the
        same way, or the second import of an unchanged file edits the book.

        One book, imported into twice — a fresh book and a re-imported one
        cannot be compared directly, since their guids differ by construction
        and every `guid:` line in the export would differ with them.
        """
        book = _import_new(tmp_path, 'twice.gnucash')
        first = _export(book, tmp_path, 'first-of-two.txt')

        result = CliRunner().invoke(cli, ['import', str(book), LEDGER])
        assert result.exit_code == 0, result.output

        second = _export(book, tmp_path, 'second-of-two.txt')
        assert first == second, f'--- first ---\n{first}\n--- second ---\n{second}'
