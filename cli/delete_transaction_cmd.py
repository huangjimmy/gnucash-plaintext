"""
CLI command for deleting a GnuCash transaction by GUID.

The transaction is exported to plaintext before deletion so the user has a
copy they can re-import to undo the operation:

    gnucash-plaintext delete-transaction-by-guid ledger.gnucash <GUID> -o backup.txt
    # ... inspect backup.txt ...
    gnucash-plaintext import ledger.gnucash -f backup.txt

Without -o, the plaintext backup is written to stdout before the confirmation
message, so it can be piped or redirected independently.
"""

import sys

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.delete_transaction import DeleteTransactionUseCase


@click.command("delete-transaction-by-guid")
@click.argument("gnucash_file", type=click.Path(exists=True))
@click.argument("guid")
@click.option(
    "-o", "--output",
    "output_file",
    default=None,
    type=click.Path(),
    help="Save the pre-deletion plaintext backup to this file instead of stdout.",
)
def delete_transaction_by_guid(gnucash_file, guid, output_file):
    """
    Delete a transaction by GUID, exporting it first as a plaintext backup.

    GUID must match an existing transaction in the book; the command fails
    immediately if it does not. Only transactions are deleted — accounts and
    commodities are not affected.

    The deleted transaction is written as plaintext (to -o FILE or stdout)
    before deletion so you can restore it with:

    \b
        gnucash-plaintext import GNUCASH_FILE -f BACKUP_FILE

    \b
    Examples:

        Delete and print backup to stdout:
          gnucash-plaintext delete-transaction-by-guid ledger.gnucash 317c8ae6e0084c33951d052b9f1b9f23

        Delete and save backup to file:
          gnucash-plaintext delete-transaction-by-guid ledger.gnucash 317c8ae6e0084c33951d052b9f1b9f23 -o backup.txt
    """
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    try:
        use_case = DeleteTransactionUseCase(repo)
        try:
            result = use_case.execute(guid)
        except ValueError as e:
            raise click.ClickException(str(e)) from e

        # Write backup before saving so the user always has it even on save error
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(result.plaintext)
            click.echo(f"Backup written to {output_file}")
        else:
            sys.stdout.write(result.plaintext)

        try:
            repo.save()
        except Exception as e:
            if "ERR_FILEIO_BACKUP_ERROR" not in str(e):
                raise click.ClickException(f"Failed to save: {e}") from e

        click.echo(
            f"Deleted transaction {result.guid} "
            f"({result.date} \"{result.description}\")",
            err=True,
        )
    finally:
        repo.close()
