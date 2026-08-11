"""A failure after the save must not take the saved book with it.

`import --new` sweeps up the book it made when a run fails, so a half-written
file does not sit where the next attempt cannot write. That is right up to the
moment the book is saved — and `--output-new`, the optional listing of the
transactions just created, is written *after* `repo.save()` has already
reported `✓ Changes saved`.

So an unwritable path for that side file deleted the book the run had just
imported into: the ledger reported success, said it had saved, and then
removed the file. The listing is a convenience; the book is the work.
"""

from click.testing import CliRunner

from cli.main import cli

LEDGER = 'tests/fixtures/account_with_finer_scu.txt'


class TestWhenTheListingCannotBeWritten:
    def _run(self, tmp_path):
        """A target whose directory exists and which cannot be written.

        The command checks the directory up front, so a missing one never
        reaches the save. A path that *is* a directory passes that check and
        fails at `open()`, which is where the post-save failure lives.
        """
        book = tmp_path / 'book.gnucash'
        blocked = tmp_path / 'listing'
        blocked.mkdir()
        result = CliRunner().invoke(cli, [
            'import', '--new', str(book), LEDGER,
            '--output-new', str(blocked)])
        return book, result

    def test_the_failure_is_reported(self, tmp_path):
        _book, result = self._run(tmp_path)

        assert result.exit_code != 0, result.output
        assert 'Could not write --output-new file' in result.output, \
            result.output

    def test_the_book_it_saved_is_still_there(self, tmp_path):
        """What it did instead: deleted the book it had just written."""
        book, result = self._run(tmp_path)

        assert 'Changes saved' in result.output, result.output
        assert book.exists(), 'the saved book was deleted over a side file'

    def test_the_book_still_holds_what_was_imported(self, tmp_path):
        book, _ = self._run(tmp_path)

        out = tmp_path / 'out.txt'
        exported = CliRunner().invoke(cli, ['export', str(book), str(out)])
        assert exported.exit_code == 0, exported.output
        assert 'Expenses:Fuel 18.190 CAD' in out.read_text(), out.read_text()


class TestWhenTheImportItselfFails:
    """The case the sweep is for, which has to keep working."""

    def test_a_book_from_a_failed_run_is_taken_away(self, tmp_path):
        book = tmp_path / 'broken.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(book),
            'tests/fixtures/commodity_beside_a_line_that_will_not_parse.txt'])

        assert result.exit_code != 0, result.output
        assert not book.exists(), 'a failed run left a book behind'
