"""
CLI command for exporting GnuCash account structure to plaintext.

Unlike the 'export' command, this never loads transactions — it reads accounts
directly from the book and is therefore much faster on large files.
"""

import os

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.export_transactions import ExportTransactionsUseCase


@click.command()
@click.argument('gnucash_file', type=click.Path())
@click.argument('output_file', type=click.Path())
@click.option(
    '--as-of',
    'as_of_date',
    default=None,
    metavar='YYYY-MM-DD',
    help='Date to stamp each open/commodity declaration. Defaults to the file modification date.',
)
def export_accounts(gnucash_file, output_file, as_of_date):
    """
    Export account structure from a GnuCash file to plaintext.

    Writes commodity and account declarations only — no transactions are loaded
    or written.  Use this when you need the account chart without the full
    transaction history.

    \b
    Examples:
        gnucash-plaintext export-accounts mybook.gnucash accounts.txt
        gnucash-plaintext export-accounts mybook.gnucash accounts.txt --as-of 2024-01-01
    """
    if not os.path.exists(gnucash_file):
        raise click.UsageError(f"Input file does not exist: {gnucash_file}")

    try:
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_accounts_only()
            output = use_case.format_accounts_only(result, as_of_date=as_of_date)

            with open(output_file, 'w') as f:
                f.write(output)

            n_accounts = len(result.accounts)
            n_commodities = len(result.commodities)
            click.echo(f"Exported {n_accounts} account(s) and {n_commodities} commodity/ies to {output_file}")
        finally:
            repo.close()
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise click.Abort() from e
