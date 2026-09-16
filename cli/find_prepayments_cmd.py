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

from fractions import Fraction

import click

from infrastructure.gnucash.utils import money_text
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.unpost_business_objects import (
    find_loose_money_in_book,
    find_prepayments_in_book,
)


def _hyphenate(guid32: str) -> str:
    g = guid32
    return f'{g[0:8]}-{g[8:12]}-{g[12:16]}-{g[16:20]}-{g[20:32]}'


def _list_money_nobody_owns(loose) -> None:
    """The amounts on a receivable or payable in no lot, and how to give each an owner."""
    if not loose:
        return
    n = len(loose)
    noun, verb = ('amount', 'belongs') if n == 1 else ('amounts', 'belong')
    click.echo('')
    click.echo(f'Found {n} {noun} on a receivable or payable that {verb} to no '
               f'customer or vendor.')
    click.echo('')
    for each in loose:
        click.echo(f'  • {each.currency} {each.amount}  on {each.account}')
        click.echo(f'    transaction: {each.date}  "{each.description}"')
        click.echo(f'      guid: {_hyphenate(each.tx_guid)}')
    click.echo('')
    click.echo('None of it is a credit: it is in no lot and has no owner, so no')
    click.echo('invoice or bill can use it. Give it its owner with')
    click.echo('`lot_owner: customer:<id>` (or `vendor:<id>`) on its split and')
    click.echo('`import --strategy update`, or move it to the account it belongs on.')


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
        ownerless = []
        credits_ = find_prepayments_in_book(
            repo.book, customer_id=customer_id, vendor_id=vendor_id,
            unowned=ownerless)
        # For the whole book only: this money belongs to nobody, so no
        # `--customer` or `--vendor` selects it.
        loose = ([] if customer_id or vendor_id
                 else find_loose_money_in_book(repo.book))
    finally:
        repo.close()

    # A credit lot no owner can be read for — not from the lot, not through
    # GnuCash, not from the transaction's `owner:` line. GnuCash's View → Lots
    # makes one ("New Lot" attaches no owner), so it is a state of the book to
    # say, with how to give it an owner. It is exactly what the listing passes
    # over, so the warning and the listing cannot disagree about a credit.
    if ownerless:
        n = len(ownerless)
        heading = ('1 credit on a receivable or payable is in a lot with no owner.'
                   if n == 1 else
                   f'{n} credits on a receivable or payable are in lots with no owner.')
        click.echo('', err=True)
        click.echo(f'⚠  {heading}', err=True)
        for acct, amount, mnem, unit in ownerless:
            click.echo(f'   • {acct}  {mnem} {money_text(amount, unit)}', err=True)
        click.echo('   No invoice or bill can spend a credit nobody owns, and an export',
                   err=True)
        click.echo('   writes no `open_prepayment:` for it. Give it its owner with',
                   err=True)
        click.echo('   `lot_owner: customer:<id>` (or `vendor:<id>`) on its split and',
                   err=True)
        click.echo('   `import --strategy update`.', err=True)

    if not credits_:
        scope = ''
        if customer_id:
            scope = f' for customer {customer_id}'
        elif vendor_id:
            scope = f' for vendor {vendor_id}'
        click.echo(f'No pre-payment credits found{scope}.')
        _list_money_nobody_owns(loose)
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

    # Per-owner totals. Exact: the credits are added as the figures they are,
    # and written back at the same decimals they were listed with.
    by_owner: dict = {}
    units: dict = {}
    for c in credits_:
        key = (c.owner_type, c.owner_id, c.owner_name, c.currency)
        by_owner[key] = by_owner.get(key, Fraction(0)) + Fraction(c.amount)
        units[key] = 10 ** len(c.amount.partition('.')[2])
    click.echo('')
    if len(by_owner) == 1:
        key, total = next(iter(by_owner.items()))
        otype, oid, oname, ccy = key
        kind = 'customer' if otype == 2 else ('vendor' if otype == 4 else 'owner')
        click.echo(f'Total credit available: {ccy} {money_text(total, units[key])} '
                   f'for {kind} {oid} ({oname}).')
    else:
        click.echo('Totals per owner:')
        for key, total in sorted(by_owner.items()):
            otype, oid, oname, ccy = key
            kind = 'customer' if otype == 2 else ('vendor' if otype == 4 else 'owner')
            click.echo(f'  {ccy} {money_text(total, units[key])} '
                       f'for {kind} {oid} ({oname})')

    click.echo('')
    click.echo('To consume a credit toward an upcoming invoice/bill, post the')
    click.echo('new invoice/bill with `auto_apply_credit: true` in its header —')
    click.echo('GnuCash will then close the invoice/bill from the existing credit')
    click.echo('via gncInvoiceAutoApplyPayments. Residual credit (if any) stays')
    click.echo('open for the next invoice/bill.')
    _list_money_nobody_owns(loose)
