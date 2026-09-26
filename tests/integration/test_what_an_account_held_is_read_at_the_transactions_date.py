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


def test_the_parking_opens_what_it_owes_and_the_deposit_keeps_what_it_bought(tmp_path):
    """The parking owes a hundred and opens a cost basis for it; it spends none.

    500.00 held from the deposit, which the file lists first, and 100.00 owed
    from the parking, which takes the account from nothing to −100.00 on its
    own date (Q-047). By date the deposit came second and repaid that 100.00,
    leaving 400.00 held; imported first, it opened 500.00, so the cost bases
    hold 500.00 and owe 100.00 against the 400.00 the account holds. Q-047
    records it: a file listing a later-dated deposit first builds cost bases its
    dates contradict.
    """
    book = tmp_path / 'book.gnucash'
    CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    listing = CliRunner().invoke(cli, ['fx-balances', str(book)]).output

    assert 'Total USD cost basis balance: 600.00 USD' in listing, listing
    assert 'Total USD held in accounts: 400.00 USD' in listing, listing
