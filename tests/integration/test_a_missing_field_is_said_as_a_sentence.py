"""A key a block is read for, left out, is reported as a sentence.

Reading a required key outright raises `KeyError`, and a `KeyError` renders as
the key's own name — `invoice "INV-CUT": 'due'` — which says neither that the
field is required, nor which block wanted it, nor what to write.

The translation is only for keys a block is actually read for. Applied to any
`KeyError` at all, an internal lookup that raised one — a guid missing from a
map, a currency missing from a rates dict — would tell the reader to add a
line their file has no place for.

Both halves need pinning, and only one was: two tests assert the sentence does
*not* appear where it should not, and none asserted it appears where it
should. An empty list of block fields would have passed the whole suite.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = str(Path('tests/fixtures/an_invoice_whose_posted_block_lost_a_line.txt'))


@pytest.fixture
def result(tmp_path):
    book = tmp_path / 'cut.gnucash'
    return CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER,
                                    '--include-business-objects'])


class TestWhatItSays:
    def test_the_run_is_refused(self, result):
        assert result.exit_code != 0, result.output

    def test_the_field_is_named_and_called_required(self, result):
        assert "is missing the required field 'due'" in result.output, \
            result.output

    def test_it_is_not_just_the_key_on_its_own(self, result):
        """`invoice "INV-CUT": 'due'` was the whole of what the reader got."""
        assert 'the block it belongs to has to be stated' in result.output, \
            result.output
