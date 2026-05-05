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

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.delete_business_objects import (
    ArchiveCustomersUseCase,
    ArchiveStatus,
    ArchiveVendorsUseCase,
    DeleteCustomersUseCase,
    DeleteStatus,
)


def _run_delete(gnucash_file, ids, use_case_cls):
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    try:
        use_case = use_case_cls(repo.book)
        results = use_case.execute(list(ids))

        all_ok = True
        for r in results:
            click.echo(f'{r.id}: {r.message()}')
            if r.status != DeleteStatus.DELETED:
                all_ok = False

        if all_ok:
            try:
                repo.save()
            except Exception as e:
                if 'ERR_FILEIO_BACKUP_ERROR' not in str(e):
                    raise click.ClickException(f'Failed to save: {e}') from e
        else:
            # Only save if at least one deletion succeeded
            if any(r.status == DeleteStatus.DELETED for r in results):
                try:
                    repo.save()
                except Exception as e:
                    if 'ERR_FILEIO_BACKUP_ERROR' not in str(e):
                        raise click.ClickException(f'Failed to save: {e}') from e

        if not all_ok:
            sys.exit(1)
    finally:
        repo.close()


def _run_archive(gnucash_file, ids, use_case_cls):
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    try:
        use_case = use_case_cls(repo.book)
        results = use_case.execute(list(ids))

        all_ok = True
        for r in results:
            click.echo(f'{r.id}: {r.message()}')
            if r.status != ArchiveStatus.ARCHIVED:
                all_ok = False

        if any(r.status == ArchiveStatus.ARCHIVED for r in results):
            try:
                repo.save()
            except Exception as e:
                if 'ERR_FILEIO_BACKUP_ERROR' not in str(e):
                    raise click.ClickException(f'Failed to save: {e}') from e

        if not all_ok:
            sys.exit(1)
    finally:
        repo.close()


@click.command('delete-customers')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('ids', nargs=-1, required=True)
def delete_customers(gnucash_file, ids):
    """
    Hard-delete one or more customers by ID.

    Deletion is blocked if the customer has any linked invoices (paid or
    unpaid). Use archive-customers to soft-hide instead.

    Exit code 1 if any ID was not deleted.

    \b
    Examples:
      gnucash-plaintext delete-customers ledger.gnucash CUST001
      gnucash-plaintext delete-customers ledger.gnucash CUST001 CUST002 CUST003
    """
    _run_delete(gnucash_file, ids, DeleteCustomersUseCase)


@click.command('archive-customers')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('ids', nargs=-1, required=True)
def archive_customers(gnucash_file, ids):
    """
    Archive (hide) one or more customers by setting them inactive.

    Linked invoices are unaffected. The invoice count is shown as
    informational context when records exist.

    Exit code 1 if any ID was not found or already archived.

    \b
    Examples:
      gnucash-plaintext archive-customers ledger.gnucash CUST001
      gnucash-plaintext archive-customers ledger.gnucash CUST001 CUST002
    """
    _run_archive(gnucash_file, ids, ArchiveCustomersUseCase)


@click.command('archive-vendors')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('ids', nargs=-1, required=True)
def archive_vendors(gnucash_file, ids):
    """
    Archive (hide) one or more vendors by setting them inactive.

    Linked bills are unaffected. The bill count is shown as informational
    context when records exist.

    Exit code 1 if any ID was not found or already archived.

    \b
    Examples:
      gnucash-plaintext archive-vendors ledger.gnucash VEND001
      gnucash-plaintext archive-vendors ledger.gnucash VEND001 VEND002
    """
    _run_archive(gnucash_file, ids, ArchiveVendorsUseCase)
