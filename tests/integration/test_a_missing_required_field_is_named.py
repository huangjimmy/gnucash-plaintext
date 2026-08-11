"""A required field a block leaves out is named, not echoed as a key.

Every key in a `posted:` block is required — the writer and the comparison
both read them outright — so a hand-written block that omits one has to be
told which. Read outright, the omission surfaced as the key's own name and
nothing else: `Error: invoice "INV-NODUE": 'due'`, which says neither that the
field is required nor what to write.

This is the plaintext counterpart of the guards the beancount reader has for
the same shape: a `ValueError` or a `KeyError` reaching the reader as its own
repr is a message with no file, no field and nothing to look for.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

LEDGER = str(Path('tests/fixtures/an_invoice_posted_block_missing_a_field.txt'))


class TestAPostedBlockMissingDue:
    def _run(self, tmp_path):
        book = tmp_path / 'book.gnucash'
        return CliRunner().invoke(cli, [
            'import', '--new', str(book), LEDGER,
            '--include-business-objects'])

    def test_it_is_refused(self, tmp_path):
        result = self._run(tmp_path)

        assert result.exit_code != 0, result.output

    def test_it_names_the_field(self, tmp_path):
        result = self._run(tmp_path)

        assert 'due' in result.output, result.output
        assert 'required' in result.output.lower(), result.output

    def test_it_names_the_block_that_wanted_it(self, tmp_path):
        result = self._run(tmp_path)

        assert 'INV-NODUE' in result.output, result.output
