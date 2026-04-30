"""
CLI command for importing plaintext transactions to GnuCash.
"""

import os

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.conflict_resolver import ResolutionStrategy
from services.gnucash_importer import GnuCashImporter
from services.plaintext_parser import DirectiveType, PlaintextParser
from use_cases.export_transactions import ExportTransactionsUseCase
from use_cases.import_transactions import ImportTransactionsUseCase


@click.command()
@click.argument('gnucash_file', required=False, type=click.Path())
@click.argument('input_file', required=False, type=click.Path())
@click.option('-i', '--input', 'gnucash_path', type=click.Path(), help='GnuCash XML file')
@click.option('-f', '--file', 'plaintext_file', type=click.Path(), help='Plaintext transactions file')
@click.option(
    '--strategy',
    type=click.Choice(['skip', 'keep-existing', 'keep-incoming', 'update'], case_sensitive=False),
    default='skip',
    help='Conflict resolution strategy (default: skip). '
         'update: modify existing transactions in-place when a GUID match is found, preserving their GUID.'
)
@click.option(
    '--dry-run',
    is_flag=True,
    help='Preview import without making changes'
)
@click.option(
    '--new',
    'create_new',
    is_flag=True,
    help='Create a new GnuCash file (file must not already exist)'
)
@click.option('--include-business-objects', is_flag=True, help='Include business objects (customers, invoices, etc.)')
@click.option(
    '--output-new',
    'output_new',
    type=click.Path(),
    default=None,
    help='Write newly imported transactions (with GUIDs) to this file. Use "-" for stdout.'
)
def import_transactions(gnucash_file, input_file, gnucash_path, plaintext_file, strategy, dry_run, create_new, include_business_objects, output_new):
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

        gnucash-plaintext import --new mybook.gnucash chart-of-accounts.txt

        gnucash-plaintext import mybook.gnucash transactions.txt --output-new new.txt

        gnucash-plaintext import mybook.gnucash transactions.txt --output-new -
    """
    # Support both positional and flag-based arguments
    gnucash_file = gnucash_path or gnucash_file
    input_file = plaintext_file or input_file

    if not gnucash_file:
        raise click.UsageError("Missing GnuCash file. Use positional argument or -i/--input flag.")
    if not input_file:
        raise click.UsageError("Missing plaintext file. Use positional argument or -f/--file flag.")

    if create_new and dry_run:
        raise click.UsageError("--new and --dry-run are mutually exclusive: --new always creates a file.")
    if output_new and dry_run:
        click.echo("Warning: --output-new is ignored in dry-run mode (no changes are saved)", err=True)

    # Validate all paths before touching the filesystem
    if create_new:
        if os.path.exists(gnucash_file):
            raise click.UsageError(
                f"File already exists: {gnucash_file}. "
                "Remove it first or omit --new to import into existing file."
            )
    else:
        if not os.path.exists(gnucash_file):
            raise click.UsageError(
                f"GnuCash file does not exist: {gnucash_file}. "
                "Use --new to create it."
            )
    if not os.path.exists(input_file):
        raise click.UsageError(f"Plaintext file does not exist: {input_file}")
    if output_new and output_new != '-':
        out_dir = os.path.dirname(os.path.abspath(output_new))
        if not os.path.isdir(out_dir):
            raise click.UsageError(f"--output-new directory does not exist: {out_dir}")

    # Map CLI strategy to ResolutionStrategy enum
    strategy_map = {
        'skip': ResolutionStrategy.SKIP,
        'keep-existing': ResolutionStrategy.KEEP_EXISTING,
        'keep-incoming': ResolutionStrategy.KEEP_INCOMING,
        'update': ResolutionStrategy.UPDATE,
    }
    resolution_strategy = strategy_map[strategy]

    try:
        if create_new:
            GnuCashRepository.create_new_file(gnucash_file)

        # Open repository
        mode = SessionMode.READ_ONLY if dry_run else SessionMode.NORMAL
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=mode)

        try:
            biz_objects_imported = 0
            if include_business_objects:
                click.echo("Importing business objects...")
                parser = PlaintextParser()
                parser.parse_file(input_file)
                importer = GnuCashImporter()

                # Create accounts first
                for directive in parser.root_directive.children:
                    if directive.type == DirectiveType.OPEN_ACCOUNT:
                        importer.create_account(directive, repo.book)

                biz_types = {
                    DirectiveType.CUSTOMER, DirectiveType.VENDOR,
                    DirectiveType.TAXTABLE, DirectiveType.INVOICE, DirectiveType.BILL,
                }
                biz_objects_imported = sum(
                    1 for d in parser.root_directive.children if d.type in biz_types
                )
                importer.import_business_objects(parser.root_directive.children, repo.book)

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
            click.echo(f"  Updated:      {result.updated_count}")
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

            # Save if not dry run and something was imported.
            # biz_objects_imported must be included here: business objects are
            # written to GnuCash memory before import_from_file() runs, so they
            # are never reflected in result.imported_count / accounts_created.
            # Without this, importing into an existing file that already has all
            # accounts produces has_changes=False → repo.save() is skipped →
            # customers/invoices/bills are silently lost on session.end().
            has_changes = (
                result.imported_count > 0
                or result.updated_count > 0
                or result.accounts_created > 0
                or biz_objects_imported > 0
            )
            if not dry_run and has_changes:
                click.echo("")
                click.echo("Saving changes...")
                repo.save()
                click.echo("✓ Changes saved")

                # Write newly created transactions (transaction blocks only, with GUIDs)
                if output_new and result.new_transactions:
                    exporter = ExportTransactionsUseCase(repo)
                    plaintext = exporter.format_transaction_list(result.new_transactions)
                    if output_new == '-':
                        # Write raw plaintext to stdout — no header so output
                        # remains parseable when piped or redirected
                        click.echo(plaintext, nl=False)
                    else:
                        try:
                            with open(output_new, 'w', encoding='utf-8') as f:
                                f.write(plaintext)
                            click.echo(f"✓ New transactions written to {output_new}")
                        except OSError as exc:
                            raise click.ClickException(f"Could not write --output-new file: {exc}") from exc
            elif dry_run:
                click.echo("")
                click.echo("✓ Dry run complete (no changes made)")
            else:
                click.echo("")
                click.echo("✓ Nothing to import")

        finally:
            repo.close()

    except Exception as e:
        if create_new and os.path.exists(gnucash_file):
            os.remove(gnucash_file)
        raise click.ClickException(str(e)) from e
