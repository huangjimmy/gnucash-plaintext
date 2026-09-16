"""An unquoted value that starts with `#` and is no typed literal is read as text.

`#` starts a typed literal — `#True`, `#False`, `#None`, a number such as
`#100`. A hand-written colour, `colour: #ff0000`, is none of those, and the
import keeps it as the text it is. The export then writes it quoted.
"""

from click.testing import CliRunner

from cli.main import cli


def test_the_export_writes_it_quoted(tmp_path):
    book = tmp_path / 'book.gnucash'
    runner = CliRunner()
    imported = runner.invoke(cli, [
        'import', '--new', str(book),
        'tests/fixtures/a_customer_whose_colour_is_written_unquoted.txt',
        '--include-business-objects'])
    assert imported.exit_code == 0, imported.output

    out = tmp_path / 'exported.txt'
    exported = runner.invoke(cli, ['export', str(book), str(out), '--include-business-objects'])

    assert exported.exit_code == 0, exported.output
    assert 'colour: "#ff0000"' in out.read_text(encoding='utf-8')
