"""A stranded balance travels in the ledger rather than stopping it.

`--verify-costs` reports a `cost_basis_balance` stored on a split that is no
cost basis, and says the export writes it back out. What that costs is worth
stating exactly, because the two halves of this fault behave differently on the
way out.

The **guid** a sale gives is refused on re-import — `_validate_pick` has
nothing to measure against — so a book holding that half cannot rebuild itself,
which `test_a_disposal_drawing_on_a_split_that_is_no_basis` pins.

The **balance** on its own is not. It is stored as an ordinary custom key and
the import's check on a stated balance asks about currency, parseability, sign,
unit and size, never whether the split is a cost basis. So the export re-imports
cleanly and the rebuilt book holds the same figure in the same place: the fault
is carried forward, not caught. Nothing clears it but saying so.
"""

import re

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run
from tests.integration.test_an_atomic_import_commits_or_rolls_back import (
    DEPOSIT_SPLIT,
    RATES,
    _a_book_already_wrong,
)


def test_the_book_is_reported(tmp_path):
    runner = CliRunner()
    book = _a_book_already_wrong(runner, tmp_path)
    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert verified.exit_code == 1, verified.output
    assert DEPOSIT_SPLIT in verified.output, verified.output
    assert 'holds the same figure in the same place' in verified.output, \
        verified.output


def test_its_export_re_imports_and_carries_the_fault(tmp_path):
    """Which is why the report tells the reader how to clear it."""
    runner = CliRunner()
    book = _a_book_already_wrong(runner, tmp_path)

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out),
                '--include-business-objects').exit_code == 0
    assert 'cost_basis_balance: "2720.00"' in out.read_text(), out.read_text()

    fresh = tmp_path / 'fresh.gnucash'
    again = _run(runner, 'import', '--new', str(fresh), str(out),
                 '--include-business-objects', '--fx-rates', RATES)
    assert again.exit_code == 0, again.output
    assert re.search(r'Errors:\s+0$', again.output, re.M), again.output

    rebuilt = _run(runner, 'fx-balances', str(fresh), '--verify-costs')
    assert rebuilt.exit_code == 1, rebuilt.output
    assert DEPOSIT_SPLIT in rebuilt.output, rebuilt.output


def test_stating_an_empty_balance_clears_it(tmp_path):
    """The one thing that does, and what the report asks for."""
    runner = CliRunner()
    book = _a_book_already_wrong(runner, tmp_path)

    out = tmp_path / 'out.txt'
    assert _run(runner, 'export', str(book), str(out)).exit_code == 0
    block = re.search(r'2026-08-13 \* "Received[^\n]*\n(?:\t[^\n]*\n)*',
                      out.read_text()).group(0)
    clear = tmp_path / 'clear.txt'
    clear.write_text(re.sub(r'cost_basis_balance: "[^"]*"',
                            'cost_basis_balance: ""', block))
    assert _run(runner, 'import', str(book), str(clear),
                '--strategy', 'update').exit_code == 0

    verified = _run(runner, 'fx-balances', str(book), '--verify-costs')
    assert DEPOSIT_SPLIT not in verified.output, verified.output
