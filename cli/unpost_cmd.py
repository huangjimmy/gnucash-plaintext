"""
CLI commands for unposting invoices and bills (Q-010).

unpost-invoices / unpost-bills
    Unpost one or more posted records by ID (or GUID with --by-guid).
    Calls GnuCash's Unpost(False) directly — does NOT consult any
    plaintext file. Entry GUIDs are preserved.

    Exit code 1 if any ID was not found, not posted, or ambiguous.

Per-ID output examples:
    INV-001 (abc123…): unposted
    INV-002 (def456…): not posted (already unposted)
    INV-003: not found
    INV-004: failed — multiple records share this id; rerun with --by-guid

This complements the re-import path: changing `posted: { ... }` to
`posted: none` in a .txt and re-importing also unposts, but it
rebuilds entries from the .txt. Use this command when the .txt is
stale or absent and you only want the unpost itself.
"""

import sys

import click

from infrastructure.gnucash.guid_lookup import normalise_guid
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.unpost_business_objects import (
    UnpostBillsUseCase,
    UnpostInvoicesUseCase,
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

    Destroys the posting transaction. Payment transactions in the bank
    account remain but become orphaned (no longer linked to a lot) —
    same as GnuCash's UI Unpost.

    Entry GUIDs are preserved (no destroy + recreate).

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

    See unpost-invoices for behaviour details — the bill side is
    symmetric (AP rather than AR).

    \b
    Examples:
      gnucash-plaintext unpost-bills ledger.gnucash BILL-2026-001
      gnucash-plaintext unpost-bills ledger.gnucash BILL-001 BILL-002
      gnucash-plaintext unpost-bills ledger.gnucash --by-guid f66df24e6e75424ba08c2b0a47ec292c
    """
    _run_unpost(gnucash_file, ids, UnpostBillsUseCase, by_guid=by_guid)
