"""CLI command: the balance sheet of a book as of a date, printed by a customized GnuCash report (Q-042).

`balance-sheet <book> --as-of YYYY-MM-DD [--currency HKD] [--fx-rates file] [--prices file]
[--price-source pricedb-latest] [--output-format text|html|pdf] [--output file]`

The figures are GnuCash's, in the currency the book is kept in: its balances,
converted by GnuCash through the book's price database and the prices any
`--fx-rates` or `--prices` file adds to it for this run.
"""
import sys

import click

from cli._dates import parse_date
from cli._gnucash_statements import (
    CURRENCY_HELP,
    OUTPUT_FORMATS,
    PRICE_SOURCE_HELP,
    PRICES_HELP,
    RATES_HELP,
    add_the_files_prices,
    check_output,
    page_for,
    read_price_files,
    the_currency,
    write_out,
)
from cli._warnings import said_once
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.gnucash_report import PageNotRenderedError
from services.gnucash_statements import render_balance_sheet


@click.command("balance-sheet")
@click.argument("gnucash_file", type=click.Path(exists=True))
@click.option("--as-of", "as_of", required=True, callback=parse_date,
              help="Balance-sheet date (YYYY-MM-DD).")
@click.option("--currency", default=None, help=CURRENCY_HELP)
@click.option("--fx-rates", "fx_rates_file", default=None, type=click.Path(exists=True),
              help=RATES_HELP)
@click.option("--prices", "prices_file", default=None, type=click.Path(exists=True),
              help=PRICES_HELP)
@click.option("--price-source", default=None, help=PRICE_SOURCE_HELP)
@click.option("--output-format", type=click.Choice(OUTPUT_FORMATS, case_sensitive=False),
              default="text", show_default=True, help="Output format.")
@click.option("--output", "output_file", default=None, type=click.Path(),
              help="Output file. Required for html and pdf; defaults to stdout for text.")
@click.option("--itemize/--no-itemize", "itemize", default=True, show_default=True,
              help="Show how each gain figure was worked out, as comment lines.")
def balance_sheet(gnucash_file, as_of, currency, fx_rates_file, prices_file, price_source,
                  output_format, output_file, itemize):
    """The balance sheet as of a date, printed by a customized GnuCash report, in the book's currency."""
    check_output(output_format, output_file)
    quotes = read_price_files(fx_rates_file, prices_file)
    # A sink of this run's own. `said_once` keys each warning on what it is
    # about, and one made here starts empty every invocation — a sink shared
    # at module level would keep one run's keys and silence the next, which in
    # a process that invokes the command twice is every test that does.
    warn = said_once()

    repo = GnuCashRepository(gnucash_file)
    repo.open(SessionMode.READ_ONLY)
    try:
        report_currency = the_currency(repo.book, currency)
        add_the_files_prices(repo.book, quotes, report_currency, [as_of])
        page = render_balance_sheet(repo.session, report_currency, as_of, page_for(output_format),
                                    price_source=price_source, warn=warn, itemize=itemize)
    except PageNotRenderedError as refusal:
        raise click.ClickException(str(refusal)) from refusal
    finally:
        repo.close()

    write_out(page, output_format, output_file)


if __name__ == "__main__":
    sys.exit(balance_sheet())
