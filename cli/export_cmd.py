"""
CLI command for exporting GnuCash transactions to plaintext.
"""

import os

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.export_transactions import ExportTransactionsUseCase


@click.command()
@click.argument('gnucash_file', required=False, type=click.Path())
@click.argument('output_file', required=False, type=click.Path())
@click.option('-i', '--input', 'input_file', type=click.Path(), help='Input GnuCash XML file')
@click.option('-o', '--output', 'output_path', type=click.Path(), help='Output plaintext file')
@click.option('--start-date', '-s', help='Start date (YYYY-MM-DD)')
@click.option('--end-date', '-e', help='End date (YYYY-MM-DD)')
@click.option('--account', '-a', help='Filter by account path')
@click.option('--all-accounts', 'all_accounts', is_flag=True, help='Export all accounts even if they have no transactions')
def export_transactions(gnucash_file, output_file, input_file, output_path, start_date, end_date, account, all_accounts):
    """
    Export transactions from GnuCash file to plaintext format.

    Supports both positional and flag-based arguments:

    \b
    Positional style:
        gnucash-plaintext export mybook.gnucash transactions.txt

    \b
    Flag style:
        gnucash-plaintext export -i mybook.gnucash -o transactions.txt

    Examples:

        gnucash-plaintext export mybook.gnucash transactions.txt

        gnucash-plaintext export -i mybook.gnucash -o transactions.txt

        gnucash-plaintext export mybook.gnucash transactions.txt --start-date 2024-01-01

        gnucash-plaintext export -i mybook.gnucash -o transactions.txt --account "Expenses:Groceries"
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
        # Open repository
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=SessionMode.READ_ONLY)

        try:
            # Create use case
            use_case = ExportTransactionsUseCase(repo)

            # Export
            click.echo(f"Exporting transactions from {gnucash_file}...")
            count = use_case.export_to_file(
                output_file,
                start_date=start_date,
                end_date=end_date,
                account_filter=account,
                all_accounts=all_accounts
            )

            click.echo(f"✓ Exported {count} transaction(s) to {output_file}")

        finally:
            repo.close()

    except Exception as e:
        click.echo(f"✗ Error: {str(e)}", err=True)
        raise click.Abort() from e
