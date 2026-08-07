"""CLI command: unapply a payment from a posted invoice or bill.

`unapply-payment <book> <id> --to <account> [--txn <guid> | --all] [--by-guid] [--bill]`

Peels a payment off a still-**posted** invoice/bill: the payment's AR/AP split
is detached from the record's lot (so the invoice returns to Outstanding, or
partially-paid if other payments remain) and re-homed to `--to <account>`. The
invoice/bill document is untouched and stays posted; the bank/income
transaction is never deleted — only the freed split's account changes.

This is NOT unpost: `unpost-invoices` / `unpost-bills` drop the record to Draft
and destroy the posting transaction. Use unapply-payment when the document is
correct but a payment was applied to the wrong invoice (or wasn't a payment at
all) and you need to peel it back without touching the document.

`--to` is required: the freed money had some prior account the apply step
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

from infrastructure.gnucash.guid_lookup import normalise_guid
from infrastructure.gnucash.utils import money_text
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.gnucash_importer import find_account
from use_cases.unapply_payment import execute_unapply


@click.command('unapply-payment')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('record_id')
@click.option('--to', 'to_account_name', required=True,
              help='Account to re-home the freed payment split into (any type; '
                   'typically the payable/liability you represent it with).')
@click.option('--txn', 'txn_guids', multiple=True,
              help='Peel this payment, named by its bank transaction GUID. '
                   'Repeatable — pass --txn once per payment to peel a subset '
                   '(e.g. two of three).')
@click.option('--all', 'unapply_all', is_flag=True, default=False,
              help='Unapply every payment on the record (→ fully Outstanding).')
@click.option('--bill', 'is_bill', is_flag=True, default=False,
              help='Target a vendor bill instead of a customer invoice.')
@click.option('--by-guid', 'by_guid', is_flag=True, default=False,
              help='Resolve RECORD_ID as an invoice/bill GUID rather than its id.')
def unapply_payment(gnucash_file, record_id, to_account_name, txn_guids,
                    unapply_all, is_bill, by_guid):
    """Detach a payment from a posted invoice/bill and re-home it to --to."""
    if txn_guids and unapply_all:
        raise click.ClickException('--txn and --all are mutually exclusive.')
    try:
        txn_guids = [normalise_guid(g) for g in txn_guids]
    except ValueError as e:
        raise click.ClickException(str(e)) from e

    kind = 'bill' if is_bill else 'invoice'
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    try:
        to_account = find_account(repo.book.get_root_account(), to_account_name)
        if to_account is None:
            raise click.ClickException(
                f'--to account {to_account_name!r} not found in the book')
        result = execute_unapply(
            repo.book, record_id, to_account, is_bill=is_bill,
            by_guid=by_guid, txn_guids=txn_guids, unapply_all=unapply_all)
        if result.status == 'unapplied':
            repo.save()
    finally:
        repo.close()

    label = result.guid and f'{result.id} ({result.guid})' or result.id

    if result.status == 'unapplied':
        n = len(result.unapplied)
        noun = 'payment' if n == 1 else 'payments'
        click.echo(f'{label}: unapplied {n} {noun} → {result.to_account}')
        for tx_guid, amount, currency in result.unapplied:
            click.echo(f'   • {currency} {amount}  (was payment tx {tx_guid})')
        state = 'Outstanding' if result.remaining_balance != 0 else 'fully paid'
        click.echo(f'   {kind} lot balance now '
                   f'{money_text(Fraction(abs(result.remaining_balance)), result.unit)} '
                   f'({state}); document still posted.')
        return

    # Error statuses → exit non-zero with a clear message.
    msgs = {
        'not_found': f'{kind} {result.id!r} not found',
        'ambiguous_id': (f'{result.id!r} matches multiple records — rerun with '
                         f'--by-guid <guid>'),
        'not_posted': f'{result.id!r} is not posted — nothing to unapply',
        'no_payments': f'{result.id!r} is posted but has no payments to unapply',
        'need_selector': result.detail,
        'txn_not_found': result.detail,
    }
    raise click.ClickException(msgs.get(result.status, f'unapply failed: {result.status}'))


if __name__ == '__main__':
    sys.exit(unapply_payment())
