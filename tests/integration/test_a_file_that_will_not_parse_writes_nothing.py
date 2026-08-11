"""A file the parser could not read leaves no book, whichever flags are passed.

The parser records a structural error and keeps building directives, so a
mis-indented ledger still yields the commodities and accounts above the bad
line. The transaction pass returns on those errors before writing anything;
the second pass `--include-business-objects` used to run — making its own
commodities and accounts so business objects had something to refer to — never
asked.

That was harmless while nothing counted what that pass made. Once it did —
because a commodity-only file has to be able to save — the count reached
`has_changes`, and the run reported the error and saved the book anyway. The
same file without the flag wrote nothing: one file, two answers, decided by a
flag, and the saving one is the flag anyone with invoices or bills passes.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

BROKEN = 'tests/fixtures/commodity_beside_a_line_that_will_not_parse.txt'


@pytest.mark.parametrize('extra', [[], ['--include-business-objects']])
class TestEitherWay:
    def test_the_parse_error_is_reported(self, extra, tmp_path):
        gnc = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(gnc), BROKEN, *extra])

        # The positive assertions first: `'X' not in output` is true of empty
        # output, and a crash before anything is printed leaves it empty — so
        # on their own the two below would pass against a refusal that said
        # nothing at all, which is what this test is named for.
        assert 'cannot find parent directive' in result.output, result.output
        assert 'Errors:       0' not in result.output, result.output
        assert 'Traceback' not in result.output, result.output

    def test_it_names_the_line_the_reader_has_to_go_and_fix(self, extra,
                                                            tmp_path):
        """The last line of the file, counted the way an editor counts.

        The parser enumerated from zero, so every message named the line
        above the mistake — buried in a per-transaction error before, and the
        whole of the user-facing text once the pre-pass started refusing.
        """
        gnc = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(gnc), BROKEN, *extra])

        offender = len(Path(BROKEN).read_text().rstrip('\n').splitlines())
        assert f'line {offender}' in result.output, result.output

    def test_no_book_is_left_behind(self, extra, tmp_path):
        """Asserted, not branched on.

        `--new` writes the book before the file is read, so the question is
        whether the refusal takes it away again — and both arms have to give
        the same answer, which is the point of the parametrisation. Written
        as `if not gnc.exists(): return` the only assertion never ran on the
        arm that removes it, which is the same thing as not testing it.
        """
        gnc = tmp_path / 'book.gnucash'
        CliRunner().invoke(cli, ['import', '--new', str(gnc), BROKEN, *extra])

        assert not gnc.exists(), (
            'a file that did not parse left a book behind')

    def test_it_does_not_report_success(self, extra, tmp_path):
        gnc = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(gnc), BROKEN, *extra])

        assert '✓ Changes saved' not in result.output, result.output

    def test_a_partly_importable_file_leaves_the_same_book(self, extra,
                                                            tmp_path):
        """The flag decides what runs first, not what the run leaves behind.

        This file parses; one account's type does not exist. The bare import
        collected that, saved the good account and exited 1 with the book on
        disk, while the same file with `--include-business-objects` raised
        out of the pre-pass, deleted the book and imported nothing —
        measured. The pre-pass leaves what it cannot make to the transaction
        pass, which attempts the same declarations and reports what fails.
        """
        gnc = tmp_path / 'partial.gnucash'
        result = CliRunner().invoke(cli, [
            'import', '--new', str(gnc),
            'tests/fixtures/import_new_invalid_account_type.txt', *extra])

        assert result.exit_code == 1, result.output
        assert 'Unknown account type' in result.output, result.output
        assert result.output.count('Unknown account type') <= 2, result.output
        assert gnc.exists(), 'the book holding what did import was removed'

        # `--all-accounts`, because the book holds no transaction to collect
        # accounts from — the point is that the account it *could* make is
        # there.
        out = tmp_path / 'out.txt'
        assert CliRunner().invoke(
            cli, ['export', str(gnc), str(out), '--all-accounts']).exit_code == 0
        text = out.read_text()
        assert 'open Assets\n' in text, text
        assert 'Assets:Bank' not in text, text

    def test_it_exits_non_zero(self, extra, tmp_path):
        """The answer a script sees, and it has to be the same either way.

        Without the flag a parse error printed `Errors: 1` and exited 0 over
        the empty book `--new` had already written, so `import … && next-step`
        carried on; with the flag the same file failed and removed the book.
        """
        gnc = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(
            cli, ['import', '--new', str(gnc), BROKEN, *extra])

        assert result.exit_code != 0, result.output
        assert 'could not be read' in result.output, result.output
