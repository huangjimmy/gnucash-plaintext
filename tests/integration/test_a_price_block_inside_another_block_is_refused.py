"""A `price` block inside another block is refused where it is written.

A price is a block of its own, written at the start of a line. Indented under a
transaction it would be a child the transaction does not read, so the file is
refused at the line the block starts on, and nothing in it is imported.
"""

from click.testing import CliRunner

from cli.main import cli

FIXTURE = 'tests/fixtures/a_price_block_inside_a_transaction.txt'


def test_the_block_is_refused_at_its_line(tmp_path):
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, ['import', '--new', str(book), FIXTURE])

    assert result.exit_code != 0, result.output
    assert ('Error processing line 19: a `price` block stands on its own, not '
            'inside transaction.') in result.output, result.output
    assert 'Traceback' not in result.output, result.output
