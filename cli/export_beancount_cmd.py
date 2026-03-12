"""
CLI command for exporting GnuCash to beancount format.
"""

import os

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.export_beancount import ExportBeancountUseCase


@click.command()
@click.argument('gnucash_file', required=False, type=click.Path())
@click.argument('output_file', required=False, type=click.Path())
@click.option('-i', '--input', 'input_file', type=click.Path(), help='Input GnuCash XML file')
@click.option('-o', '--output', 'output_path', type=click.Path(), help='Output beancount file')
@click.option('--date-from', help='Start date (YYYY-MM-DD)')
@click.option('--date-to', help='End date (YYYY-MM-DD)')
@click.option('--account', help='Filter by account path (e.g., "Assets:Bank")')
def export_beancount(gnucash_file, output_file, input_file, output_path, date_from, date_to, account):
    """
    Export GnuCash file to beancount format.

    Converts GnuCash transactions, accounts, and commodities to beancount-compatible
    format with proper naming conventions.

    Supports both positional and flag-based arguments:

    \b
    Positional style:
        gnucash-plaintext export-beancount my.gnucash output.beancount

    \b
    Flag style:
        gnucash-plaintext export-beancount -i my.gnucash -o output.beancount

    Examples:

        \b
        # Export entire ledger
        $ gnucash-plaintext export-beancount my.gnucash output.beancount

        \b
        # Export with flags
        $ gnucash-plaintext export-beancount -i my.gnucash -o output.beancount

        \b
        # Export date range
        $ gnucash-plaintext export-beancount my.gnucash output.beancount \\
            --date-from 2024-01-01 --date-to 2024-12-31

        \b
        # Export specific account
        $ gnucash-plaintext export-beancount -i my.gnucash -o output.beancount \\
            --account "Assets:Bank"
    """
    # Support both positional and flag-based arguments
    gnucash_file = input_file or gnucash_file
    output_file = output_path or output_file

    if not gnucash_file:
        raise click.UsageError("Missing input file. Use positional argument or -i/--input flag.")
    if not output_file:
        raise click.UsageError("Missing output file. Use positional argument or -o/--output flag.")

    # Validate file existence
    if not os.path.exists(gnucash_file):
        raise click.UsageError(f"Input file does not exist: {gnucash_file}")

    try:
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=SessionMode.READ_ONLY)

        try:
            use_case = ExportBeancountUseCase(repo)

            click.echo(f"Exporting from: {gnucash_file}")
            if date_from or date_to:
                click.echo(f"Date range: {date_from or 'beginning'} to {date_to or 'end'}")
            if account:
                click.echo(f"Account filter: {account}")

            line_count = use_case.export_to_file(
                output_file,
                start_date=date_from,
                end_date=date_to,
                account_filter=account
            )

            click.secho(f"✓ Exported to: {output_file}", fg='green')
            click.echo(f"  Lines: {line_count}")

        finally:
            repo.close()

    except Exception as e:
        click.secho(f"✗ Export failed: {str(e)}", fg='red', err=True)
        raise click.Abort() from e
