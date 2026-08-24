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
    `txn_guid: "<orphan-guid>"` to link the existing bank tx into the new
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

from cli._saving import save_or_report
from infrastructure.gnucash.guid_lookup import normalise_guid
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.unpost_business_objects import (
    UnpostBillsUseCase,
    UnpostInvoicesUseCase,
    UnpostResult,
    UnpostStatus,
    format_orphan_warning_block,
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

    Thin adapter over `format_orphan_warning_block` so the same warning
    text is emitted from both the unpost CLI commands and the importer
    (Q-015), which calls the shared formatter when its own `Unpost(False)`
    is about to orphan one or more bank txs.
    """
    return format_orphan_warning_block(result.kind, result.orphans)


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
            save_or_report(repo)

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
    `delete-transactions --by-guid` or link it via Q-004's
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
    are the same as for invoices (`delete-transactions --by-guid`, or
    linking it back with `txn_guid:` on re-import). Doing neither, then
    re-paying, silently
    duplicates the bank withdrawal.

    \b
    Examples:
      gnucash-plaintext unpost-bills ledger.gnucash BILL-2026-001
      gnucash-plaintext unpost-bills ledger.gnucash BILL-001 BILL-002
      gnucash-plaintext unpost-bills ledger.gnucash --by-guid f66df24e6e75424ba08c2b0a47ec292c
    """
    _run_unpost(gnucash_file, ids, UnpostBillsUseCase, by_guid=by_guid)
