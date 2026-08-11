"""
CLI command for importing GnuCash-compatible beancount files.
"""

import contextlib
import os

import click

from repositories.gnucash_repository import GnuCashRepository
from services.beancount_parser import BeancountValidationError
from services.gnucash_importer import begin_currency_declarations
from use_cases.import_beancount import ImportBeancountUseCase


def _discard_unfinished_book(dry_run: bool, imported: bool, path: str) -> None:
    """Take away a book this run made and did not finish writing.

    The command refuses to write over an existing path, so a book left by a
    failed run blocks the retry of the command that made it — the reader has
    to delete a file they never created, from a message that does not say
    where it came from.

    A dry run makes no book, and a finished import's book is the work.
    """
    if dry_run or imported:
        return
    with contextlib.suppress(OSError):
        os.remove(path)


@click.command()
@click.argument('gnucash_file', required=False, type=click.Path())
@click.argument('beancount_file', required=False, type=click.Path())
@click.option('-o', '--output', 'gnucash_path', type=click.Path(), help='Output GnuCash file')
@click.option('-i', '--input', 'beancount_path', type=click.Path(), help='Input beancount file')
@click.option('--dry-run', is_flag=True, help='Validate without creating file')
def import_beancount(gnucash_file, beancount_file, gnucash_path, beancount_path, dry_run):
    """
    Import GnuCash-compatible beancount file to GnuCash.

    This command imports beancount files that were exported from GnuCash
    with all gnucash-* metadata. It reconstructs the original GnuCash file
    using the metadata, preserving:
    - Original account names (with spaces and special characters)
    - Account GUIDs, types, and properties
    - Transaction GUIDs, notes, and document links
    - Split-level memo and action fields

    IMPORTANT: This only works with beancount files exported from GnuCash.
    Standard beancount files without gnucash-* metadata cannot be imported.

    Supports both positional and flag-based arguments:

    \b
    Positional style:
        gnucash-plaintext import-beancount newbook.gnucash ledger.beancount

    \b
    Flag style:
        gnucash-plaintext import-beancount -o newbook.gnucash -i ledger.beancount

    Examples:

        gnucash-plaintext import-beancount newbook.gnucash ledger.beancount

        gnucash-plaintext import-beancount -o newbook.gnucash -i ledger.beancount

        gnucash-plaintext import-beancount -o newbook.gnucash -i ledger.beancount --dry-run
    """
    # Support both positional and flag-based arguments
    gnucash_file = gnucash_path or gnucash_file
    beancount_file = beancount_path or beancount_file

    if not gnucash_file:
        raise click.UsageError(
            "Missing output GnuCash file. Use positional argument or -o/--output flag."
        )
    if not beancount_file:
        raise click.UsageError(
            "Missing input beancount file. Use positional argument or -i/--input flag."
        )

    # Validate beancount file exists
    if not os.path.exists(beancount_file):
        raise click.UsageError(f"Beancount file does not exist: {beancount_file}")

    # Check GnuCash file doesn't exist (unless dry-run)
    if not dry_run and os.path.exists(gnucash_file):
        raise click.UsageError(
            f"GnuCash file already exists: {gnucash_file}. "
            f"Remove it first or choose a different output path."
        )

    # Whether the book has reached disk complete. Everything from the moment
    # it is created is covered by the outer handler below, because
    # `create_new_file` and `repo.open()` can both fail with the file already
    # written — and a book left by a failed run blocks the retry of the
    # command that made it.
    imported = False

    try:
        if dry_run:
            click.echo(f"[DRY RUN] Validating {beancount_file}...")

            # Just validate, don't create file
            from services.beancount_parser import BeancountParser
            parser = BeancountParser()
            parser.parse_file(beancount_file)

            click.echo("")
            click.echo("Validation Summary:")
            click.echo("=" * 50)
            # What the file declares, which is a different question from what
            # an import did with them — said differently, because an ordinary
            # ledger declares its currencies and creates none of them.
            click.echo(f"  Commodities:  {len(parser.commodities)} declared")
            click.echo(f"  Accounts:     {len(parser.accounts)}")
            click.echo(f"  Transactions: {len(parser.transactions)}")
            click.echo("")
            click.echo("✓ Beancount file is valid for GnuCash import")
            click.echo(f"  All {len(parser.accounts)} accounts have required gnucash-* metadata")
            click.echo("  No implicit accounts detected")

        else:
            click.echo(f"Importing {beancount_file} to {gnucash_file}...")

            # Create new GnuCash file. It is on disk before the beancount file
            # is read, so a run that fails has to take it away again: the
            # command refuses to write over an existing path, so an empty book
            # left by a failed run blocked the retry of the very command that
            # made it — the reader had to delete a file they never created,
            # from a message that did not say where it came from.
            GnuCashRepository.create_new_file(gnucash_file)

            # Import from beancount
            repo = GnuCashRepository(gnucash_file)
            repo.open()

            # As the plaintext import does: what this file restates a currency
            # from is this run's, and the previous run read a different file.
            begin_currency_declarations()

            try:
                use_case = ImportBeancountUseCase(repo)
                result = use_case.import_from_file(beancount_file)

                # Display results
                click.echo("")
                click.echo("Import Summary:")
                click.echo("=" * 50)
                click.echo(
                    f"  Commodities:  {result.commodities_created} created, "
                    f"{result.commodities_updated} updated")
                click.echo(f"  Accounts:     {result.accounts_created}")
                click.echo(f"  Transactions: {result.transactions_created}")

                if result.has_errors():
                    click.echo("")
                    click.echo("Errors:")
                    for error in result.errors:
                        click.echo(f"  - {error}")
                    click.echo("")
                    click.echo("✗ Import completed with errors", err=True)
                    raise SystemExit(1)
                else:
                    repo.save()
                    imported = True
                    click.echo("")
                    click.echo(f"✓ Import successful - saved to {gnucash_file}")

            finally:
                repo.close()

    except BeancountValidationError as e:
        _discard_unfinished_book(dry_run, imported, gnucash_file)
        raise click.ClickException(
            f"Validation failed: {e}\n"
            "This beancount file is missing required gnucash-* metadata.\n"
            "Only beancount files exported from GnuCash can be imported."
        ) from e

    except BaseException as e:
        # `BaseException`, because the per-object failure path raises
        # `SystemExit`, which is the commonest way this command fails and
        # which no `except Exception` reaches.
        _discard_unfinished_book(dry_run, imported, gnucash_file)
        if isinstance(e, (SystemExit, KeyboardInterrupt)):
            raise
        raise click.ClickException(str(e)) from e
