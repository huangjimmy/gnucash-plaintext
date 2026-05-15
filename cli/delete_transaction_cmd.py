"""
CLI command for deleting GnuCash transactions by GUID.

Each transaction is exported to plaintext before deletion so the user
has a copy they can re-import to undo the operation:

    gnucash-plaintext delete-transactions ledger.gnucash <GUID> --by-guid -o backup.txt
    # ... inspect backup.txt ...
    gnucash-plaintext import ledger.gnucash -f backup.txt

Without -o, the plaintext backup is written to stdout before the per-tx
status lines (which go to stderr) so it can be piped or redirected
independently.

`--by-guid` is required and is the only addressing scheme currently
supported for transactions (transactions have no user-facing ID like
invoices/customers do). The flag is explicit for consistency with
`delete-customers --by-guid`, `delete-invoices --by-guid`, etc., and
to leave room for `--by-num` / `--by-description` in the future.
"""

import sys

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.delete_transaction import DeleteTransactionUseCase


@click.command("delete-transactions")
@click.argument("gnucash_file", type=click.Path(exists=True))
@click.argument("guids", nargs=-1, required=True)
@click.option(
    "--by-guid", "by_guid", is_flag=True, required=True,
    help="Address positional args as transaction GUIDs. Required — "
         "no other addressing scheme is currently supported for "
         "transactions.",
)
@click.option(
    "-o", "--output",
    "output_file",
    default=None,
    type=click.Path(),
    help="Save the pre-deletion plaintext backups to this file instead "
         "of stdout. All transactions are concatenated.",
)
def delete_transactions(gnucash_file, guids, by_guid, output_file):
    """
    Delete one or more transactions by GUID, exporting them first as
    plaintext backups.

    Each GUID must match an existing transaction in the book; the
    command reports per-GUID status and exits 1 if any failed. Only
    transactions are deleted — accounts and commodities are not
    affected.

    The deleted transactions are written as plaintext (to -o FILE or
    stdout) before deletion so you can restore them with:

    \b
        gnucash-plaintext import GNUCASH_FILE -f BACKUP_FILE

    \b
    Examples:

        Delete one transaction, print backup to stdout:
          gnucash-plaintext delete-transactions ledger.gnucash --by-guid \\
              317c8ae6e0084c33951d052b9f1b9f23

        Delete one, save backup to a file:
          gnucash-plaintext delete-transactions ledger.gnucash --by-guid \\
              317c8ae6e0084c33951d052b9f1b9f23 -o backup.txt

        Delete several, single concatenated backup:
          gnucash-plaintext delete-transactions ledger.gnucash --by-guid \\
              317c8ae6e0084c33951d052b9f1b9f23 \\
              589d2f1c7a1b4e5a803b1ce9a72f0344 \\
              -o batch_backup.txt
    """
    # Click enforces `required=True` for the flag, but we keep an
    # explicit guard so the use case is callable from tests with
    # by_guid=False without silently picking GUID anyway.
    if not by_guid:
        raise click.UsageError(
            "--by-guid is required; no other addressing scheme is "
            "currently supported for transactions.")

    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    backups = []
    results = []
    all_ok = True
    try:
        use_case = DeleteTransactionUseCase(repo)
        for guid in guids:
            try:
                result = use_case.execute(guid)
                backups.append(result.plaintext)
                results.append((guid, result, None))
            except ValueError as e:
                results.append((guid, None, str(e)))
                all_ok = False

        # Write backups (only those that succeeded) before saving so
        # the user always has them even on save error.
        combined = "\n\n".join(p for p in backups if p)
        if combined:
            if output_file:
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(combined)
                click.echo(f"Backup written to {output_file}", err=True)
            else:
                sys.stdout.write(combined)

        # Save once after all deletes — keeps the backup file atomic
        # with respect to the on-disk book state.
        if any(r is not None for _, r, _ in results):
            try:
                repo.save()
            except Exception as e:
                if "ERR_FILEIO_BACKUP_ERROR" not in str(e):
                    raise click.ClickException(f"Failed to save: {e}") from e

        for guid, result, err in results:
            if result is not None:
                click.echo(
                    f'{result.guid}: deleted '
                    f'({result.date} "{result.description}")',
                    err=True,
                )
            else:
                click.echo(f'{guid}: {err}', err=True)

        if not all_ok:
            sys.exit(1)
    finally:
        repo.close()
