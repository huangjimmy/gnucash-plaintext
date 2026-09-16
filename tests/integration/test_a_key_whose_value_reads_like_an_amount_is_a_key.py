"""A key whose value reads like an amount and a quoted commodity is still a key.

`notes: 3 "late fees"` has the shape of a split: a name, an amount, and a
commodity in quotes. A split's account never ends in a colon and a key always
does, so the line is read as the transaction's notes, not as a split on an
account called `notes:` that the import would then fail to find.
"""

import re

from click.testing import CliRunner

from tests.conftest import _run

FIXTURE = 'tests/fixtures/a_note_that_starts_with_a_number_and_a_quoted_phrase.txt'


def test_the_line_is_the_transactions_notes(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'

    result = _run(runner, 'import', '--new', str(book), FIXTURE)

    assert result.exit_code == 0, result.output
    assert 'Errors:       0' in result.output, result.output
    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    block = re.search(r'2026-02-01 \* "Late fees"\n(?:\t[^\n]*\n)*',
                      out.read_text()).group(0)
    notes = [line for line in block.splitlines() if line.startswith('\tnotes:')]
    assert len(notes) == 1 and 'late fees' in notes[0], block
    assert 'Expenses 3.00 CAD' in block and 'Assets -3.00 CAD' in block, block
