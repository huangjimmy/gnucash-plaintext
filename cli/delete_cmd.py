"""
CLI commands for deleting and archiving GnuCash customers and vendors.

delete-customers
    Hard-delete customers by ID. Blocked if any invoices are linked (any status).
    Exit code 1 if any ID failed or was not found.
    NOTE: delete-vendors is NOT implemented — GnuCash's vendor Destroy() does
    not persist correctly. Use archive-vendors to soft-hide vendors instead.

archive-customers / archive-vendors
    Soft-hide by setting active=False. Never corrupts linked invoices/bills.
    Prints invoice/bill count as informational context when records exist.
    Exit code 1 if any ID was not found or already archived.

Per-ID output examples:
    CUST001: deleted
    CUST002: failed — cannot delete, 3 invoice(s) linked
    CUST003: not found
    VEND001: archived
    VEND002: archived — 2 invoice(s) linked
    VEND003: already archived
"""

import sys

import click

from cli._saving import save_or_report
from infrastructure.gnucash.guid_lookup import normalise_guid
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.delete_business_objects import (
    ArchiveCustomersUseCase,
    ArchiveStatus,
    ArchiveVendorsUseCase,
    DeleteBillsUseCase,
    DeleteCustomersUseCase,
    DeleteInvoiceStatus,
    DeleteInvoicesUseCase,
    DeleteStatus,
)


def _normalise_guids(guids):
    """Validate format and canonicalise each guid (lowercase, strip hyphens).
    Format errors surface as ClickException so the user sees a clean message
    rather than a traceback."""
    out = []
    for g in guids:
        try:
            out.append(normalise_guid(g))
        except ValueError as e:
            raise click.ClickException(str(e)) from e
    return out


def _run_delete(gnucash_file, ids, use_case_cls, by_guid=False):
    ids = _normalise_guids(ids) if by_guid else list(ids)
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    try:
        use_case = use_case_cls(repo.book)
        results = use_case.execute(ids, by_guid=by_guid)

        all_ok = True
        for r in results:
            click.echo(f'{r.label()}: {r.message()}')
            if r.status != DeleteStatus.DELETED:
                all_ok = False

        # Saved when anything was deleted, which `all_ok` implies and a
        # partial run has to be asked about.
        if all_ok or any(r.status == DeleteStatus.DELETED for r in results):
            save_or_report(repo)

        if not all_ok:
            sys.exit(1)
    finally:
        repo.close()


def _run_archive(gnucash_file, ids, use_case_cls, by_guid=False):
    ids = _normalise_guids(ids) if by_guid else list(ids)
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    try:
        use_case = use_case_cls(repo.book)
        results = use_case.execute(ids, by_guid=by_guid)

        all_ok = True
        for r in results:
            click.echo(f'{r.label()}: {r.message()}')
            if r.status != ArchiveStatus.ARCHIVED:
                all_ok = False

        if any(r.status == ArchiveStatus.ARCHIVED for r in results):
            save_or_report(repo)

        if not all_ok:
            sys.exit(1)
    finally:
        repo.close()


def _run_delete_invoice_or_bill(gnucash_file, ids, use_case_cls, by_guid=False):
    """Q-013: shared CLI body for `delete-invoices` / `delete-bills`.

    Mirrors `_run_delete` (customers) and `_run_unpost`. Saves on
    partial success so completed deletes are not thrown away when a
    later id in the batch hits FAILED_POSTED / NOT_FOUND.
    """
    ids = _normalise_guids(ids) if by_guid else list(ids)
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    try:
        use_case = use_case_cls(repo.book)
        results = use_case.execute(ids, by_guid=by_guid)

        all_ok = True
        for r in results:
            click.echo(f'{r.label()}: {r.message()}')
            if r.status != DeleteInvoiceStatus.DELETED:
                all_ok = False

        if any(r.status == DeleteInvoiceStatus.DELETED for r in results):
            save_or_report(repo)

        if not all_ok:
            sys.exit(1)
    finally:
        repo.close()


@click.command('delete-customers')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('ids', nargs=-1, required=True)
@click.option('--by-guid', is_flag=True, default=False,
              help='Treat positional args as customer GUIDs instead of customer numbers.')
def delete_customers(gnucash_file, ids, by_guid):
    """
    Hard-delete one or more customers by ID (or GUID with --by-guid).

    Deletion is blocked if the customer has any linked invoices (paid or
    unpaid). Use archive-customers to soft-hide instead.

    Exit code 1 if any record was not deleted.

    \b
    Examples:
      gnucash-plaintext delete-customers ledger.gnucash CUST001
      gnucash-plaintext delete-customers ledger.gnucash CUST001 CUST002 CUST003
      gnucash-plaintext delete-customers ledger.gnucash --by-guid 9f14a498cc894d50931f855a9a31d594
    """
    _run_delete(gnucash_file, ids, DeleteCustomersUseCase, by_guid=by_guid)


@click.command('archive-customers')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('ids', nargs=-1, required=True)
@click.option('--by-guid', is_flag=True, default=False,
              help='Treat positional args as customer GUIDs instead of customer numbers.')
def archive_customers(gnucash_file, ids, by_guid):
    """
    Archive (hide) one or more customers by setting them inactive.

    Linked invoices are unaffected. The invoice count is shown as
    informational context when records exist.

    Exit code 1 if any record was not found or already archived.

    \b
    Examples:
      gnucash-plaintext archive-customers ledger.gnucash CUST001
      gnucash-plaintext archive-customers ledger.gnucash CUST001 CUST002
      gnucash-plaintext archive-customers ledger.gnucash --by-guid 9f14a498cc894d50931f855a9a31d594
    """
    _run_archive(gnucash_file, ids, ArchiveCustomersUseCase, by_guid=by_guid)


@click.command('delete-invoices')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('ids', nargs=-1, required=True)
@click.option('--by-guid', is_flag=True, default=False,
              help='Treat positional args as invoice GUIDs instead of invoice numbers.')
def delete_invoices(gnucash_file, ids, by_guid):
    """
    Delete one or more UNPOSTED customer invoices by ID (or GUID with
    --by-guid).

    Refuses posted invoices. To delete a previously-posted invoice,
    first run `unpost-invoices <id>` and then `delete-invoices <id>`
    — the explicit two-step keeps the destruction of the posting
    transaction (and the orphaning of payment splits) from being a
    silent side effect of a delete command.

    Exit code 1 if any record was not found, was posted, or ambiguous.

    \b
    Examples:
      gnucash-plaintext delete-invoices ledger.gnucash INV-2026-001
      gnucash-plaintext delete-invoices ledger.gnucash INV-001 INV-002
      gnucash-plaintext delete-invoices ledger.gnucash --by-guid 9f14a498cc894d50931f855a9a31d594
    """
    _run_delete_invoice_or_bill(gnucash_file, ids, DeleteInvoicesUseCase,
                                by_guid=by_guid)


@click.command('delete-bills')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('ids', nargs=-1, required=True)
@click.option('--by-guid', is_flag=True, default=False,
              help='Treat positional args as bill GUIDs instead of bill numbers.')
def delete_bills(gnucash_file, ids, by_guid):
    """
    Delete one or more UNPOSTED vendor bills by ID (or GUID with
    --by-guid).

    Symmetric to delete-invoices — refuses posted bills. To delete a
    previously-posted bill, first run `unpost-bills <id>` and then
    `delete-bills <id>`.

    Exit code 1 if any record was not found, was posted, or ambiguous.

    \b
    Examples:
      gnucash-plaintext delete-bills ledger.gnucash BILL-2026-001
      gnucash-plaintext delete-bills ledger.gnucash BILL-001 BILL-002
      gnucash-plaintext delete-bills ledger.gnucash --by-guid f66df24e6e75424ba08c2b0a47ec292c
    """
    _run_delete_invoice_or_bill(gnucash_file, ids, DeleteBillsUseCase,
                                by_guid=by_guid)


@click.command('archive-vendors')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('ids', nargs=-1, required=True)
@click.option('--by-guid', is_flag=True, default=False,
              help='Treat positional args as vendor GUIDs instead of vendor numbers.')
def archive_vendors(gnucash_file, ids, by_guid):
    """
    Archive (hide) one or more vendors by setting them inactive.

    Linked bills are unaffected. The bill count is shown as informational
    context when records exist.

    Exit code 1 if any record was not found or already archived.

    \b
    Examples:
      gnucash-plaintext archive-vendors ledger.gnucash VEND001
      gnucash-plaintext archive-vendors ledger.gnucash VEND001 VEND002
      gnucash-plaintext archive-vendors ledger.gnucash --by-guid f66df24e6e75424ba08c2b0a47ec292c
    """
    _run_archive(gnucash_file, ids, ArchiveVendorsUseCase, by_guid=by_guid)
