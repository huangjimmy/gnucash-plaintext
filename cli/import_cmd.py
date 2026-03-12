"""
CLI command for importing plaintext transactions to GnuCash.
"""

import os

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.conflict_resolver import ResolutionStrategy
from use_cases.import_transactions import ImportTransactionsUseCase


@click.command()
@click.argument('gnucash_file', required=False, type=click.Path())
@click.argument('input_file', required=False, type=click.Path())
@click.option('-i', '--input', 'gnucash_path', type=click.Path(), help='GnuCash XML file')
@click.option('-f', '--file', 'plaintext_file', type=click.Path(), help='Plaintext transactions file')
@click.option(
    '--strategy',
    type=click.Choice(['skip', 'keep-existing', 'keep-incoming'], case_sensitive=False),
    default='skip',
    help='Conflict resolution strategy (default: skip)'
)
@click.option(
    '--dry-run',
    is_flag=True,
    help='Preview import without making changes'
)
def import_transactions(gnucash_file, input_file, gnucash_path, plaintext_file, strategy, dry_run):
    """
    Import plaintext transactions to GnuCash file.

    Supports both positional and flag-based arguments:

    \b
    Positional style:
        gnucash-plaintext import mybook.gnucash transactions.txt

    \b
    Flag style:
        gnucash-plaintext import -i mybook.gnucash -f transactions.txt

    Examples:

        gnucash-plaintext import mybook.gnucash transactions.txt

        gnucash-plaintext import -i mybook.gnucash -f transactions.txt

        gnucash-plaintext import mybook.gnucash transactions.txt --dry-run

        gnucash-plaintext import -i mybook.gnucash -f transactions.txt --strategy keep-incoming
    """
    # Support both positional and flag-based arguments
    gnucash_file = gnucash_path or gnucash_file
    input_file = plaintext_file or input_file

    if not gnucash_file:
        raise click.UsageError("Missing GnuCash file. Use positional argument or -i/--input flag.")
    if not input_file:
        raise click.UsageError("Missing plaintext file. Use positional argument or -f/--file flag.")

    # Validate file existence
    if not os.path.exists(gnucash_file):
        raise click.UsageError(f"GnuCash file does not exist: {gnucash_file}")
    if not os.path.exists(input_file):
        raise click.UsageError(f"Plaintext file does not exist: {input_file}")
    # Map CLI strategy to ResolutionStrategy enum
    strategy_map = {
        'skip': ResolutionStrategy.SKIP,
        'keep-existing': ResolutionStrategy.KEEP_EXISTING,
        'keep-incoming': ResolutionStrategy.KEEP_INCOMING
    }
    resolution_strategy = strategy_map[strategy]

    try:
        # Open repository
        mode = SessionMode.READ_ONLY if dry_run else SessionMode.NORMAL
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=mode)

        try:
            # Create use case
            use_case = ImportTransactionsUseCase(repo)

            # Import
            click.echo(f"Importing transactions from {input_file}...")
            if dry_run:
                click.echo("(Dry run - no changes will be made)")

            result = use_case.import_from_file(input_file, resolution_strategy)

            # Display results
            click.echo("")
            click.echo("Import Summary:")
            click.echo("=" * 50)
            click.echo(f"  Transactions: {result.imported_count}")
            click.echo(f"  Accounts:     {result.accounts_created}")
            click.echo(f"  Skipped:      {result.skipped_count} (duplicates)")
            click.echo(f"  Conflicts:    {len(result.conflicts)}")
            click.echo(f"  Errors:       {result.error_count}")

            if result.conflicts:
                click.echo("")
                click.echo("Conflicts detected:")
                for conflict in result.conflicts:
                    click.echo(f"  - {conflict.existing_description} vs {conflict.incoming_description}")

            if result.errors:
                click.echo("")
                click.echo("Errors:")
                for error in result.errors:
                    if isinstance(error, dict):
                        click.echo(f"  - {error.get('error', str(error))}")
                    else:
                        click.echo(f"  - {str(error)}")

            # Save if not dry run and something was imported
            has_changes = result.imported_count > 0 or result.accounts_created > 0
            if not dry_run and has_changes:
                click.echo("")
                click.echo("Saving changes...")
                repo.save()
                click.echo("✓ Changes saved")
            elif dry_run:
                click.echo("")
                click.echo("✓ Dry run complete (no changes made)")
            else:
                click.echo("")
                click.echo("✓ Nothing to import")

        finally:
            repo.close()

    except Exception as e:
        click.echo(f"✗ Error: {str(e)}", err=True)
        raise click.Abort() from e
