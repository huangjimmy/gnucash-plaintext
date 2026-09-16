"""A tax table is not created without a name.

A tax table is found by its name, and an invoice or bill line gives the one it
uses as `tax_table: "<name>"`. `taxtable ""` was created, and an export then
wrote no `tax_table:` on a line using it, so re-importing the export changed the
line. GnuCash's own tax table dialog will not save one without a name either.
"""

from click.testing import CliRunner

from cli.main import cli


def test_it_is_refused_and_no_book_is_left(tmp_path):
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, [
        'import', '--new', str(book), 'tests/fixtures/a_tax_table_with_no_name.txt',
        '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert 'taxtable "": a tax table needs a name' in result.output, result.output
    assert not book.exists()
