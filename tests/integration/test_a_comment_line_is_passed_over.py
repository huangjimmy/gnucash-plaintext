"""A line a person wrote for a reader, not for the book, is passed over.

The format has three comment openings, and a line starting with any of them is
skipped wherever it appears: `#`, `;` and `;;`. `#` is what
`print-invoice --format plaintext` prepends its caveats with, so a rendered
invoice re-imports cleanly (Q-019). `;` and `;;` are what a ledger keeps notes
with — beancount's own files use `;` (`services/beancount_parser.py`), and the
reconcile preview this tool writes opens its sections with `;;`
(`services/reconcile_preview_reader.py`) — so a person who edits one of those
and imports it, or who writes notes the way every other plaintext ledger does,
is writing a comment rather than a line the book must refuse.

Only at the beginning of a line. A `;` after a value is part of that value, as
a `#` is: the format has no trailing comments, and a description reading
`"paid; see note"` means what it says.

Each ledger below holds the same book — a CAD commodity, four accounts and one
100.00 opening transaction — and differs only in the comment written into it,
so what the import says is about the comment and nothing else.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import FIXTURES


def _import(tmp_path, fixture):
    book = tmp_path / 'book.gnucash'
    return book, _run(CliRunner(), 'import', '--new', str(book), str(FIXTURES / fixture))


class TestASemicolonOpensAComment:

    def test_a_single_semicolon_line_is_passed_over(self, tmp_path):
        _, result = _import(tmp_path, 'a_ledger_whose_note_opens_with_a_semicolon.txt')

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output

    def test_a_double_semicolon_line_is_passed_over(self, tmp_path):
        """What the reconcile preview writes its section headers with."""
        _, result = _import(tmp_path, 'a_ledger_whose_sections_open_with_two_semicolons.txt')

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output

    def test_a_comment_indented_inside_a_block_is_passed_over(self, tmp_path):
        """A note written among a transaction's splits, where `#` is already allowed."""
        _, result = _import(tmp_path, 'a_ledger_with_a_note_among_a_transactions_splits.txt')

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output

    def test_the_hash_comment_still_works(self, tmp_path):
        """Q-019: a rendered invoice's caveat lines re-import cleanly."""
        _, result = _import(tmp_path, 'a_ledger_whose_caveat_opens_with_a_hash.txt')

        assert result.exit_code == 0, result.output
        assert 'Errors:       0' in result.output, result.output


class TestASemicolonAfterAValueIsPartOfIt:

    def test_a_description_may_hold_a_semicolon(self, tmp_path):
        """The format has no trailing comments, so this is not one."""
        book, imported = _import(tmp_path, 'a_ledger_whose_description_holds_a_semicolon.txt')
        assert imported.exit_code == 0, imported.output
        written = tmp_path / 'out.txt'

        result = _run(CliRunner(), 'export', str(book), str(written))

        assert result.exit_code == 0, result.output
        assert 'Opening; see the note' in written.read_text(encoding='utf-8'), \
            written.read_text(encoding='utf-8')
