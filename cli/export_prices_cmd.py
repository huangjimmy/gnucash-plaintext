"""
CLI command for exporting a book's prices to plaintext.

Writes the book's `price` blocks and nothing else, apart from the commodity
declarations those prices use, so the file imports on its own. It reads the
price database only, and loads no transaction.
"""

import os

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.prices import (
    commodities_of,
    format_price_blocks,
    prices_in_book,
    select_prices,
)
from use_cases.export_transactions import ExportTransactionsUseCase


@click.command()
@click.argument('gnucash_file', type=click.Path())
@click.argument('output_file', type=click.Path())
@click.option('--start-date', type=click.DateTime(formats=['%Y-%m-%d']), default=None,
              metavar='YYYY-MM-DD', help='Keep no price dated before this day.')
@click.option('--end-date', type=click.DateTime(formats=['%Y-%m-%d']), default=None,
              metavar='YYYY-MM-DD', help='Keep no price dated after this day.')
@click.option('--latest', type=click.IntRange(min=1), default=None, metavar='N',
              help='Keep the N most recent prices of each commodity in each currency, '
                   'counting back from --end-date, or from today without it.')
def export_prices(gnucash_file, output_file, start_date, end_date, latest):
    """
    Export a book's prices to plaintext.

    Each option works on its own, none requires another, and any of them can
    be given together.

    \b
    Examples:
        gnucash-plaintext export-prices mybook.gnucash prices.txt
        gnucash-plaintext export-prices mybook.gnucash prices.txt --latest 1
        gnucash-plaintext export-prices mybook.gnucash prices.txt --latest 5 --end-date 2025-12-31
        gnucash-plaintext export-prices mybook.gnucash prices.txt --start-date 2025-01-01 --end-date 2025-12-31
    """
    if not os.path.exists(gnucash_file):
        raise click.UsageError(f"Input file does not exist: {gnucash_file}")

    try:
        repo = GnuCashRepository(gnucash_file)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            prices = select_prices(
                prices_in_book(repo.book),
                start_date=start_date.date() if start_date is not None else None,
                end_date=end_date.date() if end_date is not None else None,
                latest=latest,
            )
            declarations = ExportTransactionsUseCase(repo).format_commodities(
                commodities_of(prices, repo.book))
            blocks = format_price_blocks(prices)
            text = declarations + ('\n' if declarations and blocks else '') + blocks

            # Rendered in full before the file is opened, as `export` does, so
            # a failure leaves yesterday's file where it was.
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(text)

            click.echo(f"Exported {len(prices)} price(s) to {output_file}")
        finally:
            repo.close()
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(str(e)) from e
