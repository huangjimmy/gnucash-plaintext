"""CLI command: unapply a payment from a posted invoice or bill.

`unapply-payment <book> <id> --to <account> [--txn <guid> | --all] [--by-guid] [--bill]`

Peels a payment off a still-**posted** invoice/bill: the payment's AR/AP split
is detached from the record's lot (so the invoice returns to Outstanding, or
partially-paid if other payments remain) and given the account `--to` states. The
invoice or bill itself is untouched and stays posted; the bank/income
transaction is never deleted — only the payment split's account changes, and its
amount with it where `--to` is kept in another currency. Pass `--fx-rates` for
an account kept in the book's own currency where the split carries no figure in
it; an account in a third foreign currency is refused, since the restated
amount would be currency the book holds with no cost basis behind it. `unlink`
is the same operation under the name for undoing a link, and documents both.

This is NOT unpost: `unpost-invoices` / `unpost-bills` drop the record to Draft
and destroy the posting transaction. Use unapply-payment when the record is
correct but a payment was applied to the wrong invoice (or wasn't a payment at
all) and you need to peel it back without touching that record.

`--to` is required: the payment split had some prior account the apply step
overwrote and we never recorded, and money no longer applied to an invoice is a
payable you may owe back — only you know which account represents that in your
chart (often a LIABILITY "Due to ...", possibly an asset carried negative). Any
account type is accepted.

Selecting which payment(s):
  - one payment on the record → no selector needed
  - several payments → `--txn <bank-tx-guid>` to peel one; repeat `--txn` to
    peel a subset (e.g. two of three wrong payments); or `--all` for every
    payment. Omitting all selectors on a multi-payment record is an error
    (never a guess). Payments are identified by GUID, so equal amounts are
    unambiguous.
"""

import sys
from fractions import Fraction

import click

from cli.taking_a_payment_off import take_the_payment_off, the_options_both_take
from infrastructure.gnucash.utils import money_text


@click.command('unapply-payment')
@the_options_both_take(
    'unapply',
    to_help='Account the payment split takes (any type; typically the '
            'payable/liability you represent it with).')
def unapply_payment(gnucash_file, record_id, to_account_name, txn_guids,
                    take_all, is_bill, by_guid, fx_rates_file):
    """Take a payment off a posted invoice/bill; its split takes --to."""
    result = take_the_payment_off(
        gnucash_file, record_id, to_account_name, txn_guids=txn_guids,
        take_all=take_all, is_bill=is_bill, by_guid=by_guid,
        fx_rates_file=fx_rates_file, verb='unapply')

    # Reaching here at all means a payment came off: every other status is a
    # `ClickException` raised inside `take_the_payment_off`, worded from the
    # one place both commands answer a refused run out of.
    kind = 'bill' if is_bill else 'invoice'
    label = result.guid and f'{result.id} ({result.guid})' or result.id
    n = len(result.unapplied)
    noun = 'payment' if n == 1 else 'payments'
    click.echo(f'{label}: unapplied {n} {noun} → {result.to_account}')
    for tx_guid, amount, currency in result.unapplied:
        # Figure then currency, as `unlink` writes it and as the balance line
        # below writes it — one order for one operation.
        click.echo(f'   • {amount} {currency}  (was payment tx {tx_guid})')
    state = 'Outstanding' if result.remaining_balance != 0 else 'fully paid'
    # In the record's own currency: the balance is the record's figure, and a
    # USD invoice in a CAD book does not share the book's.
    left = money_text(Fraction(abs(result.remaining_balance)), result.unit)
    click.echo(f'   {kind} lot balance now {left} {result.currency} '
               f'({state}); it is still posted.')


if __name__ == '__main__':
    sys.exit(unapply_payment())
