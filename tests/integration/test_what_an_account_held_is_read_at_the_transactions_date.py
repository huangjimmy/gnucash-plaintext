"""Whether a transaction spent currency is read from what its accounts held on its own date.

A disposal is a fall in what a side holds, floored at nothing: an account taken
below nothing has spent no units the book had, it owes them. What it held is
read at the transaction's date, not from the whole balance, so a later-dated
deposit that comes first in a file does not make an earlier parking look like a
spend.

`tests/fixtures/usd_parked_on_a_clearing_account_before_the_day_it_held_any.txt`
parks −100.00 USD on a clearing account on 2032-03-01, when it held nothing,
after a block depositing 500.00 USD there on 2032-06-01.
"""

from click.testing import CliRunner

from cli.main import cli

LEDGER = 'tests/fixtures/usd_parked_on_a_clearing_account_before_the_day_it_held_any.txt'


def test_the_parking_is_not_read_as_a_disposal(tmp_path):
    book = tmp_path / 'book.gnucash'
    done = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])

    assert done.exit_code == 0, done.output
    assert 'Errors:       0' in done.output, done.output


def test_the_cost_basis_keeps_the_dollars_bought(tmp_path):
    """500.00 bought and none spent: the parking owes a hundred, it does not spend one."""
    book = tmp_path / 'book.gnucash'
    CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    listing = CliRunner().invoke(cli, ['fx-balances', str(book)]).output

    assert 'Total USD cost basis balance: 500.00 USD' in listing, listing
