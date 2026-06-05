"""
CLI command for listing open customer/vendor credit lots (pre-payments).

A pre-payment is an open AR/AP lot that holds a balance NOT attached to
any invoice or bill. Two ways one gets created:

  * Customer overpayment: `payment: 150` on a $100 invoice produces a
    closed invoice lot ($0) plus an open AR lot with balance −$50 — the
    customer credit. Symmetric for vendor bills (AP, opposite signs).
  * Standalone payment recorded without an invoice — e.g. a customer
    pre-payment received before any invoice is issued.

Either way the credit is invisible in plaintext until consumed. This
command surfaces every credit lot in the book (or filtered to a single
customer / vendor) so the user can decide whether to apply it against
an upcoming invoice (via `auto_apply_credit: true` on that invoice) or
refund it (drop the lot's source bank tx via
`delete-transactions --by-guid`).
"""

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.export_transactions import find_ownerless_credit_lots
from use_cases.unpost_business_objects import find_prepayments_in_book


def _hyphenate(guid32: str) -> str:
    g = guid32
    return f'{g[0:8]}-{g[8:12]}-{g[12:16]}-{g[16:20]}-{g[20:32]}'


@click.command('find-prepayments')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.option('--customer', 'customer_id', default=None,
              help='Only list credits held for this customer id (e.g. C001).')
@click.option('--vendor', 'vendor_id', default=None,
              help='Only list credits held for this vendor id (e.g. V001).')
def find_prepayments(gnucash_file, customer_id, vendor_id):
    """
    List open customer / vendor credit lots (pre-payments) — open AR/AP
    lots that are NOT attached to any invoice or bill.

    Each credit is reported with the owner (customer or vendor), credit
    amount, currency, source bank transaction (the original payment that
    produced the credit), and the AR/AP account holding it. A total per
    owner is printed at the end. Exit code is 0 whether or not any
    credits are found (the command is informational).

    What to do with each credit:
      a) Apply against the next invoice/bill — add `auto_apply_credit: true`
         to that invoice/bill on import. GnuCash's `gncInvoiceAutoApplyPayments`
         consumes the credit toward the new posted lot.
      b) Refund — drop the source bank transaction via
         `delete-transactions --by-guid <source-bank-tx>` (writes a
         plaintext backup first).

    \b
    Examples:
      gnucash-plaintext find-prepayments ledger.gnucash
      gnucash-plaintext find-prepayments ledger.gnucash --customer C001
      gnucash-plaintext find-prepayments ledger.gnucash --vendor V001
    """
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        credits_ = find_prepayments_in_book(
            repo.book, customer_id=customer_id, vendor_id=vendor_id)
        ownerless = find_ownerless_credit_lots(repo.book)
    finally:
        repo.close()

    # Guard: an open AR/AP credit lot with no LOT owner is a data defect — the
    # credit belongs to no customer/vendor, so the `open_prepayment:` summary
    # (and export-accounts) silently omit it. Every legitimate path attaches the
    # owner, so this should never appear; surface it loudly if it ever does.
    if ownerless:
        click.echo('', err=True)
        click.echo(
            f'⚠  {len(ownerless)} open credit lot(s) have NO owner attached — '
            f'a bug: such a credit is unattributable and is hidden from the '
            f'open_prepayment summary / export-accounts. Please report it.',
            err=True)
        for acct, amount, mnem in ownerless:
            click.echo(f'   • {acct}  {mnem} {amount:.2f}  (ownerless credit lot)',
                       err=True)

    if not credits_:
        scope = ''
        if customer_id:
            scope = f' for customer {customer_id}'
        elif vendor_id:
            scope = f' for vendor {vendor_id}'
        click.echo(f'No pre-payment credits found{scope}.')
        return

    n = len(credits_)
    noun = 'credit' if n == 1 else 'credits'
    click.echo(f'Found {n} open pre-payment {noun}.')
    click.echo('')
    for c in credits_:
        if c.owner_type == 2:
            owner_kind = 'customer'
            ar_ap = 'AR'
        elif c.owner_type == 4:
            owner_kind = 'vendor'
            ar_ap = 'AP'
        else:
            owner_kind = 'owner'
            ar_ap = 'AR/AP'

        click.echo(
            f'  • {owner_kind} {c.owner_id} ({c.owner_name})  '
            f'{c.currency} {c.amount}  in {c.ar_ap_account}'
        )
        click.echo(
            f'    source bank tx: {c.date} on {c.bank_account}  "{c.description}"'
        )
        if c.memo:
            click.echo(f'      memo: "{c.memo}"')
        click.echo(f'      guid: {_hyphenate(c.tx_guid)}')
        click.echo(
            '      NOTE: this is the parent bank tx of the credit lot\'s split.'
        )
        click.echo(
            '      Deleting it via `delete-transactions --by-guid` may also '
            'remove other'
        )
        click.echo(
            '      splits on the same tx (e.g. the original invoice payment if '
            'this credit'
        )
        click.echo(
            '      came from an overpayment). Consuming via `auto_apply_credit` '
            'on the next'
        )
        click.echo(
            '      invoice/bill is the non-destructive option.'
        )
        click.echo(f'    why classified as a pre-payment ({ar_ap} credit):')
        click.echo(
            '      - the lot lives on an AR/AP account and is open '
            '(balance != 0),')
        click.echo(
            '      - gncInvoiceGetInvoiceFromLot returned NULL — no invoice / bill '
        )
        click.echo(
            '        owns this lot, so the credit is unconsumed,')
        click.echo(
            f'      - parent tx owner backref points at {owner_kind} {c.owner_id}.'
        )

    # Per-owner totals.
    by_owner: dict = {}
    for c in credits_:
        key = (c.owner_type, c.owner_id, c.owner_name, c.currency)
        by_owner.setdefault(key, 0.0)
        by_owner[key] += float(c.amount)
    click.echo('')
    if len(by_owner) == 1:
        (otype, oid, oname, ccy), total = next(iter(by_owner.items()))
        kind = 'customer' if otype == 2 else ('vendor' if otype == 4 else 'owner')
        click.echo(f'Total credit available: {ccy} {total:.2f} for {kind} {oid} ({oname}).')
    else:
        click.echo('Totals per owner:')
        for (otype, oid, oname, ccy), total in sorted(by_owner.items()):
            kind = 'customer' if otype == 2 else ('vendor' if otype == 4 else 'owner')
            click.echo(f'  {ccy} {total:.2f} for {kind} {oid} ({oname})')

    click.echo('')
    click.echo('To consume a credit toward an upcoming invoice/bill, post the')
    click.echo('new invoice/bill with `auto_apply_credit: true` in its header —')
    click.echo('GnuCash will then close the invoice/bill from the existing credit')
    click.echo('via gncInvoiceAutoApplyPayments. Residual credit (if any) stays')
    click.echo('open for the next invoice/bill.')
