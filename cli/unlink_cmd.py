"""CLI command: undo an invoice's payment by unlinking the transaction that paid it.

`unlink <book> <id> --to <account> [--txn <guid> | --all] [--by-guid] [--bill]`

An invoice can be paid without entering any money. The bank feed arrived
first, or a director paid a supplier out of pocket, so the transaction is
already in the book; a `payment:` block giving its guid puts the receivable's
account on one of its splits, and that split becomes the settlement.

`unlink` undoes that, and what it leaves is a payment with nothing to do with
the invoice any more: the split comes off the receivable, leaves the record's
lot, and takes the account `--to` gives, carrying the figure that account is
kept in. The invoice owes again.

**Either command takes either kind of payment.** `unapply-payment` is the same
operation under the name for a payment this tool created, and neither can
refuse the other's case, because nothing in the book says which one it holds:
measured on GnuCash 5.10, a bank entry reads as no transaction type at all
until a `payment:` block gives its guid, and `'P'` afterwards, which is what
the engine stamps on a payment it creates itself. The names describe the
situation the reader is in, not a difference the book records — see
`tests/research/what_tells_a_linked_payment_from_an_applied_one_probe.py`.

**The transaction is not touched.** It was the book's own record before the
link existed and it survives the unlink whole: nothing is deleted, and its
other side, its description, its guid and its date all come through. What
changes is the one split the link wrote on — the account it is on, and the
amount that account is kept in. That is the difference from `unpost-invoices`,
which destroys the posting, and the reason to reach for this rather than
rebuilding a payment: nothing here was made by this tool, so nothing here is
this tool's to remake.

**An account in another currency is restated, not renumbered.** A split
carries two figures — an amount, in the commodity of the account the split is
on, and a value, in the currency the transaction is quoted in — so the figure
changes with the account. Giving a 100.00 USD settlement a CAD account writes
the value the split already holds — −139.00 — rather than leaving 100.00 to be
read as Canadian dollars. Where `--to` is kept in the book's own currency and
the split carries no figure in it, that genuinely converts and the transaction
states no rate, so `--fx-rates` supplies one, read at the transaction's own
date and rounded to the unit that account is kept to. Without a rates file
that case is refused rather than guessed at.

**Two currencies an account may be kept in, and no others**: the commodity the
split already holds, and the book's own. A split that brings foreign currency
into the book carries a `share_price:` and a `value:` in the currency the
transaction is quoted in, and a cost basis is opened from the two; restating a
settlement states neither figure, so any other currency would be money the
book holds with nothing accounting for it. Buying that currency is a
transaction of its own.

The currency the transaction is *quoted* in is not a third. It is one of those
two or it is refused like any other — a USD invoice settled by an HKD-quoted
entry cannot send its split to an HKD account.

**An account too coarse for the figure is refused too.** `commodity_scu:` lets
an account be kept coarser than its own currency, and a figure read off the
split is handed back untouched — so writing −139.37 onto an account that counts
whole dollars would round it to −139 in silence.

`--to` is required, and for the same reason `unapply-payment` requires it: the
account the split had before the link was overwritten and never recorded, so
only the person holding the book knows where it belongs. `Assets:Due From
Director` is the shape this was reported for.

Selecting which link, where a record has more than one payment: `--txn <guid>`
(repeatable) or `--all`. Omitting both on a record with several is an error
rather than a guess, and payments are identified by guid, so equal amounts are
unambiguous.
"""

from fractions import Fraction

import click

from cli.taking_a_payment_off import take_the_payment_off, the_options_both_take
from infrastructure.gnucash.utils import money_text


@click.command('unlink')
@the_options_both_take(
    'unlink',
    to_help='Account the payment split takes. Its figure is restated into '
            'that account\'s currency where it differs.')
def unlink(gnucash_file, record_id, to_account_name, txn_guids, take_all,
           is_bill, by_guid, fx_rates_file):
    """Undo an invoice's payment by unlinking the transaction that paid it."""
    result = take_the_payment_off(
        gnucash_file, record_id, to_account_name, txn_guids=txn_guids,
        take_all=take_all, is_bill=is_bill, by_guid=by_guid,
        fx_rates_file=fx_rates_file, verb='unlink')

    kind = 'bill' if is_bill else 'invoice'
    for tg, amount, currency in result.unapplied:
        click.echo(f'unlinked {amount} {currency} from {kind} '
                   f'{result.id} (tx {tg}) → {result.to_account}')
    # A bill's lot balance is negative — what is owed is its size, as
    # `unapply-payment` reports it. In the record's own currency, which a USD
    # invoice in a CAD book does not share with the book.
    owed = money_text(Fraction(abs(result.remaining_balance)), result.unit)
    click.echo(f'  {kind} {result.id} now owes {owed} {result.currency}')


if __name__ == '__main__':  # pragma: no cover - click entry point
    unlink()
