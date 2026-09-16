"""Under a transaction only its keys and its splits are read.

A block indented under one, such as `posted:`, is read by nothing. Every line
under a transaction was taken for a split, so the block failed the import with
`'account'` — the name of a key it did not have — and no line number. It is
refused where it is written instead, as a block under an `open` line is, and
nothing in the file is imported.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURE = 'tests/fixtures/a_posted_block_under_a_transaction.txt'


@pytest.mark.parametrize('flags', [[], ['--include-business-objects']])
def test_a_posted_block_under_a_transaction_is_refused(tmp_path, flags):
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, ['import', '--new', str(book), FIXTURE, *flags])

    assert result.exit_code != 0, result.output
    assert ('Error processing line 20: under a transaction only its keys and its '
            'splits are read. This posted is under the transaction on 2026-02-01, '
            'where nothing would read it.') in result.output
    assert "'account'" not in result.output
    assert 'Traceback' not in result.output
