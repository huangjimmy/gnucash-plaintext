"""A half-finished `open_prepayment:` edit warns, and imports anyway.

The block is a summary of what the book's lots already hold — derived, not
authoritative. The importer rebuilds credits from the per-split `lot_owner:`
KVPs and never from this, so the summary's only job is to be read back and
checked, and the next export rewrites whatever it found wrong.

That makes the shapes a person leaves behind the whole question. A block
naming no owner and a block whose amount is a word are what a half-finished
edit looks like, and neither is a figure: read as one, the import would warn
about a credit nobody declared, and a reader chasing that warning would find
nothing to fix. They are skipped, and the blocks that do name a figure are
still checked — one bad block must not take the rest of the summary with it.

Never fatal, either way. A stale summary is a file that has fallen behind its
book, which is the ordinary state of an exported ledger somebody has been
editing, and refusing to import it would leave no way to bring the two back
together.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = str(Path('tests/fixtures/a_hand_edited_prepayment_summary.txt'))


@pytest.fixture
def imported(tmp_path):
    book = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(book), LEDGER, '--include-business-objects'])
    return book, result


class TestItStillImports:
    def test_the_run_succeeds(self, imported):
        _book, result = imported

        assert result.exit_code == 0, result.output

    def test_the_credit_the_book_holds_is_the_one_the_splits_say(self, imported):
        """50.00, from `lot_owner:` — not the 30.00 the summary declares."""
        book, _result = imported
        out = Path(str(book) + '.txt')
        assert CliRunner().invoke(cli, [
            'export', str(book), str(out),
            '--include-business-objects']).exit_code == 0

        text = out.read_text()
        assert 'amount: 50.00 CAD' in text, text
        assert 'amount: 30.00 CAD' not in text, text


class TestWhatItWarnsAbout:
    def test_the_figure_that_disagrees_is_named(self, imported):
        _book, result = imported

        assert 'open_prepayment' in result.output, result.output
        assert 'C-EDIT' in result.output, result.output

    def test_both_figures_are_shown(self, imported):
        """What the file says and what the book holds, or there is nothing to
        act on. Written exactly, so a figure carries the decimals it has and
        no more — 30, not 30.00."""
        _book, result = imported

        assert 'declares 30 ' in result.output, result.output
        assert 'holds 50' in result.output, result.output


class TestWhatIsNotAFigure:
    def test_a_block_naming_no_owner_is_not_warned_about(self, imported):
        """It declares 10.00 and belongs to nobody, so there is no owner whose
        credits it could disagree with."""
        _book, result = imported

        assert '10.00' not in result.output, result.output

    def test_an_amount_that_is_a_word_is_not_warned_about(self, imported):
        _book, result = imported

        assert 'about fifty' not in result.output, result.output

    def test_neither_stops_the_block_that_is_a_figure(self, imported):
        """A summary is read as a whole: one unreadable block must not take
        the checking of the others with it."""
        _book, result = imported

        assert 'C-EDIT' in result.output, result.output
        assert 'declares 30 ' in result.output, result.output
