"""A `cost_basis_cost:` in a file is refused for what it states, with the reason.

A stated cost is read only where nothing else in the transaction says what the
currency cost, so a cost no reader can use would leave that currency priced by
nothing. Each block in the fixture states one: written the wrong way round, not
a number, dividing by zero, zero, and below zero. Every one is refused and
counted, and the block that states no cost is still imported.
"""

import pytest
from click.testing import CliRunner

from tests.conftest import _run

FIXTURE = 'tests/fixtures/stated_costs_each_refused_for_what_they_state.txt'


@pytest.fixture
def imported(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    first = _run(runner, 'import', '--new', str(book),
                 'tests/fixtures/foreign_security_book.txt')
    assert first.exit_code == 0, first.output
    return _run(runner, 'import', str(book), FIXTURE)


def test_only_the_block_stating_no_cost_is_imported(imported):
    assert 'Transactions: 1' in imported.output, imported.output
    assert 'Errors:       5' in imported.output, imported.output


def test_a_cost_on_an_account_never_opened_is_refused_for_the_account(tmp_path):
    """No account, so no currency to read the cost in: the account is what the run reports."""
    result = _run(CliRunner(), 'import', '--new', str(tmp_path / 'book.gnucash'),
                  'tests/fixtures/stated_cost_on_an_account_never_opened.txt')

    assert "'Assets:Bank:USD' not found" in result.output, result.output
    assert 'Errors:       1' in result.output, result.output
    assert 'cost_basis_cost on split' not in result.output, result.output


@pytest.mark.parametrize('reason', [
    "cost_basis_cost on split 'Assets:USD Cash' is stated in USD/CAD, but that "
    "split holds USD and the book counts in CAD — state it as CAD/USD",
    "cost_basis_cost on split 'Assets:USD Cash' is not a number: 'abc'",
    "cost_basis_cost on split 'Assets:USD Cash' is not a number: '1/0'",
    "cost_basis_cost on split 'Assets:USD Cash' must be positive, got 0",
    "cost_basis_cost on split 'Assets:USD Cash' must be positive, got -1.35",
])
def test_each_reason_is_printed(imported, reason):
    assert reason in imported.output, imported.output
