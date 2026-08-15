"""
CLI command for exporting one or more GnuCash transactions by GUID to plaintext.
"""

import os
import sys

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from use_cases.export_transactions import ExportTransactionsUseCase


@click.command()
@click.argument('gnucash_file', required=False, type=click.Path())
@click.option('-i', '--input', 'input_file', type=click.Path(), help='Input GnuCash XML file')
@click.option('--guid', 'guids', required=False, multiple=True, help='GUID of a transaction to export (32-character hex); repeat for multiple')
@click.option('-o', '--output', 'output_path', type=click.Path(), help='Output file (defaults to stdout)')
def export_transaction(gnucash_file, input_file, guids, output_path):
    """
    Export one or more transactions from a GnuCash file to plaintext format.

    --guid is required and may be repeated to export multiple transactions in
    one pass. The output includes the commodity and account declarations needed
    to make the block self-contained for import or AI processing. Shared
    commodities and accounts are emitted only once.

    \b
    Examples:

        gnucash-plaintext export-transaction mybook.gnucash --guid 317c8ae6e0084c33951d052b9f1b9f23

        gnucash-plaintext export-transaction mybook.gnucash \\
            --guid 317c8ae6e0084c33951d052b9f1b9f23 \\
            --guid a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4

        gnucash-plaintext export-transaction -i mybook.gnucash --guid 317c8ae6e0084c33951d052b9f1b9f23 -o tx.txt
    """
    gnucash_file = input_file or gnucash_file

    if not gnucash_file:
        raise click.UsageError("Missing input file. Use positional argument or -i/--input flag.")

    if not guids:
        raise click.UsageError(
            "Missing --guid. export-transaction requires at least one transaction GUID.\n"
            "Example: gnucash-plaintext export-transaction mybook.gnucash --guid <32-char-hex>"
        )

    if not os.path.exists(gnucash_file):
        raise click.UsageError(f"Input file does not exist: {gnucash_file}")

    try:
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=SessionMode.READ_ONLY)

        try:
            use_case = ExportTransactionsUseCase(repo)
            result = use_case.execute_by_guids(guids)
            plaintext = use_case.format_as_plaintext(result)

            if output_path:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(plaintext)
                click.echo(f"✓ {len(guids)} transaction(s) exported to {output_path}")
            else:
                # Through the byte stream, encoded here: `sys.stdout` takes
                # the locale's encoding, and the file arm above states UTF-8 —
                # so the same transaction would come out one way to a file and
                # another down a pipe.
                sys.stdout.buffer.write(plaintext.encode('utf-8'))

        finally:
            repo.close()

    except ValueError as e:
        raise click.ClickException(str(e)) from e
    except Exception as e:
        raise click.ClickException(str(e)) from e
