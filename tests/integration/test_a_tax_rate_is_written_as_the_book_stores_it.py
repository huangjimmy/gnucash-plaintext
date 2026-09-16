"""A tax rate is written as the book stores it.

A whole-number rate is written with one decimal, `5.0%`, and a rate that
already has decimals is written with the ones it has, `9.975%`, rather than
with a `.0` added after them.
"""

from click.testing import CliRunner

from tests.conftest import _run

FIXTURE = 'tests/fixtures/a_tax_table_at_a_rate_with_three_decimals.txt'


def test_the_rate_keeps_its_decimals(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), FIXTURE, '--include-business-objects')
    assert made.exit_code == 0, made.output

    out = tmp_path / 'out.txt'
    exported = _run(runner, 'export', str(book), str(out), '--include-business-objects')

    assert exported.exit_code == 0, exported.output
    assert 'rate: 9.975%' in out.read_text(), out.read_text()
