"""`fx-balances` lists a cost basis whose transaction has no description.

Each row is followed by its transaction's description on a line of its own, and
a transaction with none gets no such line: the row is followed by the blank
line before the totals.
"""

from click.testing import CliRunner

from cli.main import cli


def test_the_row_has_no_description_line(tmp_path):
    book = tmp_path / 'book.gnucash'
    runner = CliRunner()
    imported = runner.invoke(cli, [
        'import', '--new', str(book), 'tests/fixtures/fx_buy_usd_with_no_description.txt'])
    assert imported.exit_code == 0, imported.output

    result = runner.invoke(cli, ['fx-balances', str(book)])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    rows = [i for i, line in enumerate(lines) if line.startswith('2026-01-10')]
    assert len(rows) == 1, result.output
    assert 'Assets:Bank:USD' in lines[rows[0]], result.output
    assert lines[rows[0] + 1] == '', result.output
