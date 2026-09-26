"""A transfer between two accounts of one currency is written as a transaction of its own.

A transfer draws down no cost basis and opens none, because the book holds
every unit it held before. A fee paid out of the same accounts spends units and
draws a cost basis down by what it spent; units bought into them open one for
what arrived. In one transaction the two cannot be told apart: 4,010.00 USD
leaving the bank and 4,000.00 arriving in savings does not say which 10.00 was
the fee, and a cost basis is never guessed.

Imported, each drew or opened by the whole of its split. The fee drew the full
4,010.00 off the cost basis, which then held 4,000.00 less than the accounts;
the purchase opened a cost basis of 4,000.00 for 1,000.00 that arrived, which
then held 3,000.00 more. So each is refused and written again as two
transactions, and the cost bases then hold what the accounts hold.

A fee written as a split of its own, stating its cost basis beside a transfer
of whole splits, is not this: it says it is what left, and the rest is a
transfer (Q-051). `test_a_statement_line_on_a_holding_account_is_edited_into_what_it_settles.py`
imports that shape, and edits a deposit into it.

`tests/fixtures/a_transfer_between_us_dollar_accounts_sharing_a_transaction_with_a_fee_or_new_money.txt`
writes both refused shapes, and each again as two transactions.
"""

from click.testing import CliRunner

from cli.main import cli

LEDGER = ('tests/fixtures/a_transfer_between_us_dollar_accounts_sharing_a_'
          'transaction_with_a_fee_or_new_money.txt')


def _imported(tmp_path):
    book = tmp_path / 'book.gnucash'
    done = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    return book, done


def test_a_transfer_with_a_fee_in_it_is_refused(tmp_path):
    _, done = _imported(tmp_path)

    assert ('error: Move 4,000.00 USD to savings and pay a 10.00 USD fee, in '
            'one: this transaction moves 4000.00 USD between accounts on the '
            'held side, and 10.00 USD leaves that side as well.') \
        in done.output, done.output


def test_a_transfer_with_new_money_in_it_is_refused(tmp_path):
    _, done = _imported(tmp_path)

    assert ('error: Move 3,000.00 USD to savings and buy 1,000.00 more, in '
            'one: this transaction moves 3000.00 USD between accounts on the '
            'held side, and 1000.00 USD arrives on that side as well.') \
        in done.output, done.output


def test_it_says_how_to_write_it(tmp_path):
    _, done = _imported(tmp_path)

    assert ('Write the transfer as a transaction of its own, and what left or '
            'arrived as another.') in done.output, done.output
    assert 'Errors:       2' in done.output, done.output


def test_written_as_two_transactions_the_cost_bases_hold_what_the_accounts_hold(tmp_path):
    """9,990.00 at 1.30 and 1,000.00 at 1.35 against 2,990.00 and 8,000.00."""
    book, _ = _imported(tmp_path)
    listing = CliRunner().invoke(cli, ['fx-balances', str(book)]).output

    assert 'Total USD cost basis balance: 10,990.00 USD' in listing, listing
    assert 'Total USD held in accounts: 10,990.00 USD' in listing, listing
