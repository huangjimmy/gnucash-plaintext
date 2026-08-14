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

from cli._saving import save_or_report
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
                # Encoded here rather than by the locale, so the undo copy is
                # the same bytes down a pipe as it is in the file above. This
                # one is the only copy of a transaction being destroyed.
                sys.stdout.buffer.write(combined.encode('utf-8'))

        # Save once after all deletes — keeps the backup file atomic
        # with respect to the on-disk book state.
        if any(r is not None for _, r, _ in results):
            save_or_report(repo)

        for guid, result, err in results:
            if result is not None:
                click.echo(
                    f'{result.guid}: deleted '
                    f'({result.date} "{result.description}")',
                    err=True,
                )
                # Said here as well as in the backup, because the backup is
                # the thing that is missing: a reader who redirected it and
                # did not look would otherwise learn on the day they needed
                # to undo.
                if result.undo_copy_error:
                    click.echo(
                        f'{result.guid}: WARNING no undo copy — '
                        f'{result.undo_copy_error}',
                        err=True,
                    )
            else:
                click.echo(f'{guid}: {err}', err=True)

        # A deletion with no way back does not report success. The transaction
        # is gone either way — this command is the only way to remove one the
        # format cannot write, which is why it proceeds — but the exit code is
        # what a script reads, and `delete-transactions … -o undo.txt &&
        # next-step` would otherwise chain on a backup holding only comments.
        # The same shape as `import` printing `Errors: N` and exiting 0.
        if not all_ok or any(r is not None and r.undo_copy_error
                             for _guid, r, _err in results):
            sys.exit(1)
    finally:
        repo.close()
