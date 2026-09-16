"""A line no part of the format reads is refused, with its line number.

A line that is not a block, not a split and not a `key: value` was passed over
in silence, so the file imported as though the line were not there. A note
typed where a key belongs, or a split whose amount is written in a way the
format does not read, went missing from the book with nothing said. It is
refused where it is written instead, as a block in the wrong place is, and
nothing in the file is imported.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURE = 'tests/fixtures/a_line_nothing_reads_under_a_transaction.txt'


@pytest.mark.parametrize('flags', [[], ['--include-business-objects']])
def test_the_line_is_refused_and_nothing_is_imported(tmp_path, flags):
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, ['import', '--new', str(book), FIXTURE, *flags])

    assert result.exit_code != 0, result.output
    assert ("Error processing line 19: 'paid in cash at the counter' is not a line "
            "this format reads: not a block, not a split, and not a `key: value`."
            ) in result.output, result.output
    assert 'Traceback' not in result.output, result.output
