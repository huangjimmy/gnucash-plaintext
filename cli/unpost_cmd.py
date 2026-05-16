"""
CLI commands for unposting invoices and bills.

`unpost-invoices <book> <ids>... [--by-guid]` and `unpost-bills <book> <ids>... [--by-guid]`
take posted records to the unposted state. The posting transaction (AR for
invoices, AP for bills) is destroyed; the invoice/bill itself stays in the book
with its entries intact and can be edited and reposted.

**Important — payment transactions survive unpost.** When the record was paid,
the bank-side payment transaction(s) stay in the book as free-standing entries
(no longer linked to any invoice/bill lot). Your bank ledger still shows the
money received (invoice) or sent (bill). After unpost, each affected record
prints the list of bank-side transactions it just orphaned, with their GUIDs,
dates, accounts, and amounts. Use that list to either:

  - delete the orphan(s) with `delete-transactions --by-guid`, then re-import
    the invoice/bill with a fresh `payment:` block; or
  - re-import the invoice/bill with a `payment:` block carrying
    `txn_guid: "<orphan-guid>"` to retarget the existing bank tx into the new
    posted lot (see docs/issues/Q-004 for the retarget mechanism).

Doing neither, then re-paying via a fresh `payment:` block, leaves the orphan
in place alongside the new payment — silently doubling your bank entries.

Per-ID output examples:

    INV-001 (abc123…): unposted
    ⚠  1 bank-side payment transaction is now orphaned in the book.
       …
    INV-002 (def456…): not posted (already unposted)
    INV-003: not found
    INV-004: failed — multiple records share this id; rerun with --by-guid

Use this command when the .txt is stale or absent and you only want the
unpost itself. The re-import path (toggle `posted: { ... }` → `posted: none`
and re-import) also unposts but rebuilds entries from the .txt.
"""

import sys

import click

from infrastructure.gnucash.guid_lookup import normalise_guid
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.unpost_business_objects import (
    UnpostBillsUseCase,
    UnpostInvoicesUseCase,
    UnpostResult,
    UnpostStatus,
)


def _normalise_guids(guids):
    out = []
    for g in guids:
        try:
            out.append(normalise_guid(g))
        except ValueError as e:
            raise click.ClickException(str(e)) from e
    return out


def _format_orphan_warning(result: UnpostResult) -> str:
    """Render the orphan-payment warning block for one unposted record.

    Empty string if the record had no orphans (posted but never paid →
    silent success). For invoices: "AR", "received". For bills: "AP",
    "sent" — owner type is the only material difference per the Q-014
    research's bill-symmetry round.
    """
    if not result.orphans:
        return ''

    n = len(result.orphans)
    noun = 'transaction' if n == 1 else 'transactions'
    is_invoice = (result.kind == 'invoice')
    side = 'AR' if is_invoice else 'AP'
    flow = 'received in' if is_invoice else 'sent from'
    record_word = result.kind

    lines = []
    lines.append('')
    lines.append(
        f'⚠  {n} bank-side payment {noun} {"is" if n == 1 else "are"} '
        f'now orphaned in the book.'
    )
    lines.append(
        f'   GnuCash unpost destroys the {side} posting transaction but '
        f'leaves payment'
    )
    lines.append(
        f'   transactions intact — the money still shows as {flow} '
        f'your bank account.'
    )
    lines.append('')

    # GUID formatted with hyphens for human reading; the un-hyphenated form
    # below is what `delete-transactions --by-guid` accepts.
    def _hyphenate(guid32: str) -> str:
        g = guid32
        return f'{g[0:8]}-{g[8:12]}-{g[12:16]}-{g[16:20]}-{g[20:32]}'

    for o in result.orphans:
        memo_part = f' "{o.memo}"' if o.memo else ''
        lines.append(
            f'   • {o.date}  {o.bank_account}  {o.currency} {o.amount}  '
            f'"{o.description}"'
        )
        if o.memo:
            lines.append(f'     memo:{memo_part}')
        lines.append(f'     guid: {_hyphenate(o.tx_guid)}')

    if n > 1:
        by_acct: dict = {}
        for o in result.orphans:
            by_acct.setdefault((o.bank_account, o.currency), 0.0)
            by_acct[(o.bank_account, o.currency)] += float(o.amount)
        if len(by_acct) == 1:
            (acct, ccy), total = next(iter(by_acct.items()))
            lines.append('')
            lines.append(f'   Total orphaned: {ccy} {total:.2f} in {acct}.')
        else:
            lines.append('')
            lines.append('   Total orphaned per bank account:')
            for (acct, ccy), total in sorted(by_acct.items()):
                lines.append(f'     {ccy} {total:.2f} in {acct}')

    lines.append('')
    lines.append(f'   If you intend to re-pay this {record_word}, either:')
    lines.append('     a) delete the orphan(s) first:')
    for o in result.orphans:
        lines.append(
            f'          gnucash-plaintext delete-transactions <book> '
            f'--by-guid {o.tx_guid}'
        )
    lines.append(
        f'        then re-import the {record_word} with a fresh '
        f'`payment:` block, or'
    )
    lines.append(
        f'     b) re-import the {record_word} with a `payment:` block '
        f'that includes'
    )
    if n == 1:
        lines.append(f'          txn_guid: "{result.orphans[0].tx_guid}"')
    else:
        lines.append('          txn_guid: "<orphan-guid>"  (one block per orphan)')
    lines.append(
        '        to retarget the existing bank transaction(s) into the '
        'new posted lot'
    )
    lines.append('        (see docs/issues/Q-004 for the retarget mechanism).')

    return '\n'.join(lines)


def _run_unpost(gnucash_file, ids, use_case_cls, by_guid=False):
    ids = _normalise_guids(ids) if by_guid else list(ids)
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    try:
        use_case = use_case_cls(repo.book)
        results = use_case.execute(ids, by_guid=by_guid)

        all_ok = True
        for r in results:
            click.echo(f'{r.label()}: {r.message()}')
            warning = _format_orphan_warning(r)
            if warning:
                click.echo(warning)
            if r.status != UnpostStatus.UNPOSTED:
                all_ok = False

        if any(r.status == UnpostStatus.UNPOSTED for r in results):
            try:
                repo.save()
            except Exception as e:
                if 'ERR_FILEIO_BACKUP_ERROR' not in str(e):
                    raise click.ClickException(f'Failed to save: {e}') from e

        if not all_ok:
            sys.exit(1)
    finally:
        repo.close()


@click.command('unpost-invoices')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('ids', nargs=-1, required=True)
@click.option('--by-guid', is_flag=True, default=False,
              help='Treat positional args as invoice GUIDs instead of invoice numbers.')
def unpost_invoices(gnucash_file, ids, by_guid):
    """
    Unpost one or more posted customer invoices.

    Destroys the AR posting transaction. Bank-side payment transactions
    remain in the book as free-standing entries (the orphan-payment trap);
    each one is reported with its GUID so you can either delete it via
    `delete-transactions --by-guid` or retarget it via Q-004's
    `txn_guid:` re-import path. Doing neither, then re-paying via a fresh
    `payment:` block, silently duplicates the bank deposit.

    Entry GUIDs on the invoice are preserved.

    Exit code 1 if any record was not found, not posted, or ambiguous.

    \b
    Examples:
      gnucash-plaintext unpost-invoices ledger.gnucash INV-2026-001
      gnucash-plaintext unpost-invoices ledger.gnucash INV-001 INV-002
      gnucash-plaintext unpost-invoices ledger.gnucash --by-guid 9f14a498cc894d50931f855a9a31d594
    """
    _run_unpost(gnucash_file, ids, UnpostInvoicesUseCase, by_guid=by_guid)


@click.command('unpost-bills')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('ids', nargs=-1, required=True)
@click.option('--by-guid', is_flag=True, default=False,
              help='Treat positional args as bill GUIDs instead of bill numbers.')
def unpost_bills(gnucash_file, ids, by_guid):
    """
    Unpost one or more posted vendor bills.

    Symmetric to unpost-invoices: destroys the AP posting transaction;
    bank-side payment transactions remain in the book as free-standing
    entries (orphans), each reported with its GUID. The cleanup paths
    are the same as for invoices (`delete-transactions --by-guid` or
    `txn_guid:` retarget). Doing neither, then re-paying, silently
    duplicates the bank withdrawal.

    \b
    Examples:
      gnucash-plaintext unpost-bills ledger.gnucash BILL-2026-001
      gnucash-plaintext unpost-bills ledger.gnucash BILL-001 BILL-002
      gnucash-plaintext unpost-bills ledger.gnucash --by-guid f66df24e6e75424ba08c2b0a47ec292c
    """
    _run_unpost(gnucash_file, ids, UnpostBillsUseCase, by_guid=by_guid)
