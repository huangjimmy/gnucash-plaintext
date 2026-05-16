"""
CLI command for finding orphan bank-side payment transactions.

An "orphan" is a payment-class transaction (originally created by
`gncOwnerApplyPayment`) whose AR/AP-side split's lot is no longer
attached to any invoice or bill — typically because the invoice/bill
that the payment paid was unposted in a prior session.

The orphan is harmless on its own — the money still shows as moved
through the bank — but if the user later re-pays the same invoice
without using `txn_guid:` retarget, a second bank-side transaction
gets created and the bank balance is silently doubled. This command
surfaces the orphans so the user can decide between
`delete-transactions --by-guid` (drop the orphan, fresh `payment:`
block on re-import) or Q-004's `txn_guid:` retarget (re-link the
existing bank tx to the new posted lot).

`unpost-invoices` / `unpost-bills` already warn about orphans at the
moment of unpost. This command exists for the after-the-fact case —
inheriting a book, auditing for accumulated orphans, etc.
"""


import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.unpost_business_objects import find_orphan_payments_in_book


def _hyphenate(guid32: str) -> str:
    g = guid32
    return f'{g[0:8]}-{g[8:12]}-{g[12:16]}-{g[16:20]}-{g[20:32]}'


@click.command('find-orphan-payments')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.option('--customer', 'customer_id', default=None,
              help='Only list orphans for this customer id (e.g. C001).')
@click.option('--vendor', 'vendor_id', default=None,
              help='Only list orphans for this vendor id (e.g. V001).')
def find_orphan_payments(gnucash_file, customer_id, vendor_id):
    """
    List bank-side payment transactions that are no longer attached to any
    invoice or bill — typically left behind by a prior unpost.

    Each orphan is reported with its GUID, date, bank account, amount, currency,
    customer/vendor backref, transaction description, and split memo. A total
    per bank account is printed at the end. Exit code is 0 whether or not any
    orphans are found (the command is informational); 1 only on a real error
    (file not found, etc.).

    Cleanup paths for each orphan:
      a) `gnucash-plaintext delete-transactions <book> --by-guid <guid>` — drop
         the orphan (with plaintext backup), then re-import the invoice/bill
         with a fresh `payment:` block.
      b) Re-import the invoice/bill with a `payment:` block carrying
         `txn_guid: "<orphan-guid>"` — retargets the existing bank tx into
         the new posted lot (see docs/issues/Q-004).

    \b
    Examples:
      gnucash-plaintext find-orphan-payments ledger.gnucash
      gnucash-plaintext find-orphan-payments ledger.gnucash --customer C001
      gnucash-plaintext find-orphan-payments ledger.gnucash --vendor V001
    """
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        orphans = find_orphan_payments_in_book(
            repo.book, customer_id=customer_id, vendor_id=vendor_id)
    finally:
        repo.close()

    if not orphans:
        scope = ''
        if customer_id:
            scope = f' for customer {customer_id}'
        elif vendor_id:
            scope = f' for vendor {vendor_id}'
        click.echo(f'No orphan bank-side payment transactions found{scope}.')
        return

    n = len(orphans)
    noun = 'transaction' if n == 1 else 'transactions'
    click.echo(f'Found {n} orphan bank-side payment {noun}.')
    click.echo('')
    for o in orphans:
        # Owner-type drives wording — 2=Customer, 4=Vendor.
        if o.owner_type == 2:
            owner_kind = 'customer'
            side = 'AR-side'
        elif o.owner_type == 4:
            owner_kind = 'vendor'
            side = 'AP-side'
        else:
            owner_kind = 'owner'
            side = 'AR/AP-side'

        click.echo(
            f'  • {o.date}  {o.bank_account}  {o.currency} {o.amount}  '
            f'"{o.description}"'
        )
        if o.memo:
            click.echo(f'    memo: "{o.memo}"')
        click.echo(f'    guid: {_hyphenate(o.tx_guid)}')
        click.echo('    why classified as orphan (evidence on this tx):')
        click.echo(
            '      - xaccTransGetTxnType(tx) == \'P\' — payment-class transaction,'
        )
        click.echo(
            '        created by gncOwnerApplyPayment when the invoice/bill was paid'
        )
        click.echo(
            f'      - gncOwnerGetOwnerFromTxn(tx) returned {owner_kind} '
            f'{o.owner_id} ({o.owner_name})'
        )
        click.echo(
            '        — KVP customer/vendor backref, set at payment time, survived unpost'
        )
        click.echo(
            f'      - {side} split is on {o.ar_ap_account}, but the split\'s lot'
        )
        click.echo(
            '        has no invoice/bill attached — gncInvoiceGetInvoiceFromLot'
        )
        click.echo(
            '        returned NULL, i.e. the lot was detached when its'
        )
        click.echo(
            f'        {"invoice" if o.owner_type == 2 else "bill"} was unposted'
        )

    # Per-bank-account totals.
    by_acct: dict = {}
    for o in orphans:
        by_acct.setdefault((o.bank_account, o.currency), 0.0)
        by_acct[(o.bank_account, o.currency)] += float(o.amount)
    click.echo('')
    if len(by_acct) == 1:
        (acct, ccy), total = next(iter(by_acct.items()))
        click.echo(f'Total: {ccy} {total:.2f} in {acct}.')
    else:
        click.echo('Totals per bank account:')
        for (acct, ccy), total in sorted(by_acct.items()):
            click.echo(f'  {ccy} {total:.2f} in {acct}')

    click.echo('')
    click.echo('Cleanup options per orphan (pick one, per the Q-014 / Q-004 docs):')
    click.echo(
        '  a) delete with `delete-transactions --by-guid <guid>` and '
        're-import the')
    click.echo(
        '     invoice/bill with a fresh `payment:` block, or')
    click.echo(
        '  b) re-import the invoice/bill with `txn_guid: "<guid>"` inside '
        'the new')
    click.echo(
        '     `payment:` block to retarget the existing bank tx '
        '(see Q-004).')
