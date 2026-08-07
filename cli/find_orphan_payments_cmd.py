"""
CLI command for finding orphan bank-side payment transactions.

An "orphan" is a bank-side payment whose AR/AP-side split's lot is no
longer attached to any invoice or bill — typically because the
invoice/bill it paid was unposted in a prior session.

Two shapes reach this. One is a payment GnuCash wrote itself, through
`gncOwnerApplyPayment`, recognisable by its transaction type and owner
slots. The other is a settlement attached by retargeting an existing
bank transaction (`txn_guid:`), which has neither — those are found by
the note this tool writes on the split when it unposts a document, and
each such split is its own row, since one deposit can settle several
documents.

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


from fractions import Fraction

import click

from infrastructure.gnucash.utils import money_text
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

    Each orphan is reported with its GUID, date, the account its figure is in,
    amount, currency, customer/vendor backref, transaction description, and
    split memo. A total per account is printed at the end — that is the bank on
    an ordinary book, and the receivable or payable where the two hold
    different money. Exit code is 0 whether or not any
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

    # Counted in transactions, because that is what a guid names and what the
    # cleanup advice acts on. One deposit settling two documents that are both
    # unposted is two orphaned payments on one transaction, and saying "2
    # transactions" there would invite deleting a guid twice.
    guids = {o.tx_guid for o in orphans}
    # From the row's own record, not from what survived a filter. Counting
    # duplicates here was right unfiltered and silent under `--customer` — the
    # narrowing a reader does *while cleaning up one customer*, which is the
    # path where deleting the guid takes the other's money.
    shared = {o.tx_guid for o in orphans if o.shares_its_transaction}
    n = len(guids)
    noun = 'transaction' if n == 1 else 'transactions'
    click.echo(f'Found {n} orphan bank-side payment {noun}'
               + (f', reported as {len(orphans)} orphaned payments.'
                  if len(orphans) > n else '.'))
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

        # Named against the account the figure is *of*. For an orphaned
        # settlement that is the receivable, not the bank: on a USD document
        # paid out of a CAD bank the row reads "USD 100.00" beside an account
        # that never held a dollar of it.
        click.echo(
            f'  • {o.date}  {o.amount_account or o.bank_account}  '
            f'{o.currency} {o.amount}  "{o.description}"'
        )
        if o.amount_account and o.amount_account != o.bank_account:
            click.echo(f'    paid through: {o.bank_account}')
        if o.memo:
            click.echo(f'    memo: "{o.memo}"')
        click.echo(f'    guid: {_hyphenate(o.tx_guid)}')
        click.echo('    why classified as orphan (evidence on this tx):')
        # Each reading is printed only where it actually held. Both can: a
        # payment GnuCash wrote and this tool later unposted answers to the
        # type slots *and* carries the note. Only the note answers for a
        # settlement attached by retarget, whose transaction has neither slot
        # set — printing the type lines there offered an audit trail that was
        # not the reasoning used.
        if o.typed_by_engine:
            click.echo(
                '      - xaccTransGetTxnType(tx) == \'P\' — payment-class transaction,'
            )
            click.echo(
                '        created by gncOwnerApplyPayment when the invoice/bill was paid'
            )
        if o.typed_by_kvp:
            click.echo(
                '      - the transaction carries `txn_type: P` — written by a'
            )
            click.echo(
                '        previous export, which is what says so on a book that'
            )
            click.echo(
                '        has been through plaintext and back'
            )
        if o.marked_by_unpost:
            click.echo(
                '      - the split carries `orphaned_by_unpost` — this tool '
                'recorded'
            )
            click.echo(
                '        the unpost that detached it, and no credit ever paid it'
            )
        # Whichever answered for *this row*, named for what it was. The type
        # reading is the transaction's and the owner is the split's own, so a
        # deposit covering two customers can be payment-typed while each row's
        # owner comes from its own lot — one line for one reading, or the
        # block attributes one customer's money to the other, and calls the
        # exporter's `owner:` line a backref set at payment time.
        _owner_said_by = {
            'lot': 'the lot it sits in names',
            'txn': 'gncOwnerGetOwnerFromTxn(tx) returned',
            'kvp': 'the transaction carries `owner:` naming',
            'another_lot': 'a sibling orphan\'s lot on this transaction names',
        }.get(o.owner_source)
        if _owner_said_by and o.owner_id:
            click.echo(
                f'      - {_owner_said_by} {owner_kind} '
                f'{o.owner_id} ({o.owner_name})'
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

    # Per-bank-account totals. Exact: the amounts are added as the figures they
    # are, and written back at the same decimals they were listed with — two
    # for CAD, none for a currency without a minor unit.
    by_acct: dict = {}
    units: dict = {}
    for o in orphans:
        key = (o.amount_account or o.bank_account, o.currency)
        by_acct[key] = by_acct.get(key, Fraction(0)) + Fraction(o.amount)
        # The finest any row on this key used, not the last one's. Rows format
        # at the unit of the account their figure is on, and a marked row's is
        # the receivable's while an unmarked row's is the bank's — so on one
        # key the last writer could round a total finer than itself.
        units[key] = max(units.get(key, 1),
                         10 ** len(o.amount.partition('.')[2]))
    click.echo('')
    if len(by_acct) == 1:
        (acct, ccy), total = next(iter(by_acct.items()))
        click.echo(f'Total: {ccy} {money_text(total, units[(acct, ccy)])} in {acct}.')
    else:
        click.echo('Totals per account:')
        for (acct, ccy), total in sorted(by_acct.items()):
            click.echo(f'  {ccy} {money_text(total, units[(acct, ccy)])} in {acct}')

    click.echo('')
    click.echo('Cleanup options per orphan (pick one, per the Q-014 / Q-004 docs):')
    if shared == guids:
        # Nothing here is safe to delete, and there is no second category to
        # send the reader to. Ending on "for a guid not marked" when no guid
        # qualifies names an option they would go looking for and not find —
        # on the commonest shape of all, one document overpaid by a retarget,
        # whose transaction holds the settlement and the parked residue and so
        # is shared by its own two splits.
        click.echo(
            '  a) not available for any guid in this listing — each carries')
        click.echo(
            '     money beyond the row naming it, and `delete-transactions')
        click.echo(
            '     --by-guid` would take that with them, or')
    elif shared:
        # Deleting is by transaction, and a transaction here carries more than
        # one owner's money: acting on one row's guid would take the other
        # portions with it, and re-importing only that document leaves the
        # rest gone. Retargeting moves one split and touches nothing else.
        click.echo(
            '  a) NOT for the guids marked below — they carry money beyond')
        click.echo(
            '     the rows naming them, and `delete-transactions --by-guid`')
        click.echo(
            '     would take that with them. For a guid not marked: delete it')
        click.echo(
            '     and re-import the invoice/bill with a fresh `payment:` block.')
    else:
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
    if shared:
        click.echo('')
        # What the guid carries beyond the row, rather than beyond the
        # listing: unpost the second document too and its portion becomes a
        # row of its own, so the listing is then about all of it while the
        # delete still takes both. What a whole-transaction delete costs is
        # measured against the row a reader is acting on.
        click.echo('     Guids carrying money beyond the rows naming them: '
                   + ', '.join(sorted(_hyphenate(g) for g in shared)))
