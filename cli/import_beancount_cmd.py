"""
CLI command for importing GnuCash-compatible beancount files.
"""

import os

import click

from repositories.gnucash_repository import GnuCashRepository
from services.beancount_parser import BeancountValidationError
from use_cases.import_beancount import ImportBeancountUseCase


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
            click.echo(f"  Commodities:  {len(parser.commodities)}")
            click.echo(f"  Accounts:     {len(parser.accounts)}")
            click.echo(f"  Transactions: {len(parser.transactions)}")
            click.echo("")
            click.echo("✓ Beancount file is valid for GnuCash import")
            click.echo(f"  All {len(parser.accounts)} accounts have required gnucash-* metadata")
            click.echo("  No implicit accounts detected")

        else:
            click.echo(f"Importing {beancount_file} to {gnucash_file}...")

            # Create new GnuCash file
            GnuCashRepository.create_new_file(gnucash_file)

            # Import from beancount
            repo = GnuCashRepository(gnucash_file)
            repo.open()

            try:
                use_case = ImportBeancountUseCase(repo)
                result = use_case.import_from_file(beancount_file)

                # Display results
                click.echo("")
                click.echo("Import Summary:")
                click.echo("=" * 50)
                click.echo(f"  Commodities:  {result.commodities_created}")
                click.echo(f"  Accounts:     {result.accounts_created}")
                click.echo(f"  Transactions: {result.transactions_created}")

                if result.has_errors():
                    click.echo("")
                    click.echo("Errors:")
                    for error in result.errors:
                        click.echo(f"  - {error}")
                    click.echo("")
                    click.echo("✗ Import completed with errors", err=True)
                    raise click.Abort()
                else:
                    repo.save()
                    click.echo("")
                    click.echo(f"✓ Import successful - saved to {gnucash_file}")

            finally:
                repo.close()

    except BeancountValidationError as e:
        click.echo("")
        click.echo("✗ Validation failed:", err=True)
        click.echo(str(e), err=True)
        click.echo("")
        click.echo("This beancount file is missing required gnucash-* metadata.", err=True)
        click.echo("Only beancount files exported from GnuCash can be imported.", err=True)
        raise click.Abort() from e

    except Exception as e:
        click.echo(f"✗ Error: {str(e)}", err=True)
        raise click.Abort() from e
