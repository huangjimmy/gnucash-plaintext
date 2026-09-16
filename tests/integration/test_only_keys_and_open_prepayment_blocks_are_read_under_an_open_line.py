"""Under an `open` line only the account's keys and `open_prepayment:` blocks are read.

Anything else indented under one, such as a `payment:` block, is a line the file
states and the run would ignore. So the file is refused with that line's number,
as a `price` block inside another block is, and nothing in it is imported.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURE = 'tests/fixtures/a_payment_block_under_an_open_line.txt'


@pytest.mark.parametrize('flags', [[], ['--include-business-objects']])
def test_a_payment_block_under_an_open_line_is_refused(tmp_path, flags):
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, ['import', '--new', str(book), FIXTURE, *flags])

    assert result.exit_code != 0, result.output
    assert ('Error processing line 16: under an `open` line only its keys and '
            '`open_prepayment:` blocks are read. This payment is under the open of '
            'Assets:Bank, where nothing would read it.') in result.output
    assert 'Traceback' not in result.output
