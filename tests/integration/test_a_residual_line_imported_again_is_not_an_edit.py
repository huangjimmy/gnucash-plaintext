"""A `$residual$` line imported again is not an edit, and a changed figure beside it still is.

A transaction whose guid the book already holds is skipped, and the run says so
when the file's content differs from the book's, because that is a person
editing it. The comparison read `$residual$` as the figure, so the same ledger
imported twice was reported as an edit, with advice to re-run with
`--strategy update`. The residual is whatever balances the other splits, so it is
compared as that.
"""

from click.testing import CliRunner

from cli.main import cli

FIXTURE = 'tests/fixtures/a_transaction_with_a_residual_line_and_a_guid.txt'
EDIT_NOTE = 'looks like an edit'


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(book), FIXTURE])
    assert result.exit_code == 0, result.output
    return book


def test_the_same_ledger_again_is_skipped_without_the_edit_note(tmp_path):
    book = _book(tmp_path)

    again = CliRunner().invoke(cli, ['import', str(book), FIXTURE])

    assert again.exit_code == 0, again.output
    assert 'Skipped:      1 (duplicates)' in again.output, again.output
    assert EDIT_NOTE not in again.output, again.output


def test_a_changed_figure_beside_the_residual_is_still_noted(tmp_path):
    book = _book(tmp_path)
    edited = tmp_path / 'edited.txt'
    with open(FIXTURE, encoding='utf-8') as source:
        edited.write_text(source.read().replace('Expenses 50.00 CAD', 'Expenses 60.00 CAD'),
                          encoding='utf-8')

    again = CliRunner().invoke(cli, ['import', str(book), str(edited)])

    assert again.exit_code == 0, again.output
    assert EDIT_NOTE in again.output, again.output
