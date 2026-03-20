"""
CLI command for exporting a single GnuCash transaction by GUID to plaintext.
"""

import os
import sys

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.export_transactions import ExportTransactionsUseCase


@click.command()
@click.argument('gnucash_file', required=False, type=click.Path())
@click.option('-i', '--input', 'input_file', type=click.Path(), help='Input GnuCash XML file')
@click.option('--guid', required=False, default=None, help='GUID of the transaction to export (32-character hex)')
@click.option('-o', '--output', 'output_path', type=click.Path(), help='Output file (defaults to stdout)')
def export_transaction(gnucash_file, input_file, guid, output_path):
    """
    Export a single transaction from a GnuCash file to plaintext format.

    --guid is required. The output includes the commodity and account
    declarations needed to make the block self-contained for import or
    AI processing.

    \b
    Examples:

        gnucash-plaintext export-transaction mybook.gnucash --guid 317c8ae6e0084c33951d052b9f1b9f23

        gnucash-plaintext export-transaction -i mybook.gnucash --guid 317c8ae6e0084c33951d052b9f1b9f23 -o tx.txt
    """
    gnucash_file = input_file or gnucash_file

    if not gnucash_file:
        raise click.UsageError("Missing input file. Use positional argument or -i/--input flag.")

    if not guid:
        raise click.UsageError(
            "Missing --guid. export-transaction requires a transaction GUID.\n"
            "Example: gnucash-plaintext export-transaction mybook.gnucash --guid <32-char-hex>"
        )

    if not os.path.exists(gnucash_file):
        raise click.UsageError(f"Input file does not exist: {gnucash_file}")

    try:
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=SessionMode.READ_ONLY)

        try:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_by_guid(guid)
            plaintext = use_case.format_as_plaintext(result)

            if output_path:
                with open(output_path, 'w') as f:
                    f.write(plaintext)
                click.echo(f"✓ Transaction {guid} exported to {output_path}")
            else:
                sys.stdout.write(plaintext)

        finally:
            repo.close()

    except ValueError as e:
        click.echo(f"✗ {str(e)}", err=True)
        raise SystemExit(1) from e
    except Exception as e:
        click.echo(f"✗ Error: {str(e)}", err=True)
        raise SystemExit(1) from e
