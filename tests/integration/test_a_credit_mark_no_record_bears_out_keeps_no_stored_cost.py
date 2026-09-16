"""A credit mark no record bears out does not keep a stored cost in the export.

The export drops a `cost_basis_cost` nothing reads, and keeps one on an owner's
credit this book has spent, whose stored cost is the only thing pricing it.
Whether a split is such a credit is asked of the book as well as of the mark,
because a file may write `applied_from_credit` onto any split: the split has to
sit in a lot a record owns. One in no lot is not a spent credit, so a cost on
it that nothing reads is dropped like any other.
"""

import re

from click.testing import CliRunner

from tests.conftest import _run


def test_the_stored_cost_is_not_written_out(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _run(runner, 'import', '--new', str(book),
                  'tests/fixtures/usd_moved_between_two_usd_accounts.txt')
    assert result.exit_code == 0, result.output
    result = _run(runner, 'import', str(book),
                  'tests/fixtures/a_credit_mark_written_on_a_usd_move.txt')
    assert result.exit_code == 0, result.output
    assert 'Errors:       0' in result.output, result.output

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    block = re.search(r'2026-02-02 \* "Move 10 USD[^\n]*\n(?:\t[^\n]*\n)*',
                      out.read_text()).group(0)
    assert 'applied_from_credit: "true"' in block, block
    assert 'cost_basis_cost' not in block, block
