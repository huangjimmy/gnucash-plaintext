"""A security traded in sixteenths keeps its quantity through export and import.

A commodity's fraction is the smallest unit of it the book holds, and for most
it is a power of ten. One of 16 is not: 3/16 of a share has no form in
sixteenths that a decimal point can place, so the export writes the exact
decimal it is, 0.1875, and a book rebuilt from that export holds the same 3/16.
"""

from click.testing import CliRunner

from cli.main import cli

FIXTURE = 'tests/fixtures/a_security_traded_in_sixteenths.txt'


def _export(tmp_path, book, name):
    out = tmp_path / name
    result = CliRunner().invoke(cli, ['export', str(book), str(out)])
    assert result.exit_code == 0, result.output
    return out.read_text(encoding='utf-8')


def test_the_quantity_is_written_as_the_exact_decimal_it_is(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), FIXTURE])
    assert made.exit_code == 0, made.output

    text = _export(tmp_path, book, 'first.txt')

    assert 'Assets:OLDCO 0.1875 NYSE.OLDCO' in text, text


def test_a_book_rebuilt_from_the_export_exports_the_same(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), FIXTURE])
    assert made.exit_code == 0, made.output
    first = _export(tmp_path, book, 'first.txt')

    rebuilt = tmp_path / 'rebuilt.gnucash'
    again = CliRunner().invoke(cli, ['import', '--new', str(rebuilt), str(tmp_path / 'first.txt')])
    assert again.exit_code == 0, again.output

    assert _export(tmp_path, rebuilt, 'second.txt') == first
