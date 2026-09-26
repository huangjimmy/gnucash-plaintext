"""A line's `guid:` that nothing can parse is refused when the invoice is read again.

Reading an invoice the book already holds, the import pairs the file's lines
with the book's before it asks whether the file changes anything, and a line
stating a guid that is no guid is refused there. So the invoice keeps its line.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
INVOICE = 'tests/fixtures/a_draft_invoice_with_one_line.txt'


def test_the_second_read_is_refused_and_the_line_stays(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output
    first = CliRunner().invoke(cli, ['import', str(book), INVOICE,
                                     '--include-business-objects'])
    assert first.exit_code == 0, first.output
    again = tmp_path / 'again.txt'
    text = Path(INVOICE).read_text()
    assert '\tentry:\n' in text, text
    again.write_text(text.replace('\tentry:\n', '\tentry:\n\t\tguid: "not-a-guid"\n'))

    result = CliRunner().invoke(cli, ['import', str(book), str(again),
                                      '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert "Invalid GUID format: 'not-a-guid'" in result.output, result.output
    out = tmp_path / 'out.txt'
    assert CliRunner().invoke(cli, ['export', str(book), str(out),
                                    '--include-business-objects']).exit_code == 0
    assert 'description: "Service"' in out.read_text(), out.read_text()
