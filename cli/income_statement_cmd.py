"""CLI command: the income statement of a book for a period, printed by a customized GnuCash report (Q-042).

The figures are GnuCash's, in the currency the book is kept in: converted by
GnuCash through the book's price database and the prices any `--fx-rates` file
adds to it for this run. Output formats: text (stdout or a file), HTML, PDF.
"""

import click

from cli._dates import parse_date
from cli._gnucash_statements import (
    CURRENCY_HELP,
    OUTPUT_FORMATS,
    PRICE_SOURCE_HELP,
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
from services.fiscal_year import fiscal_year_start
from services.gnucash_report import PageNotRenderedError
from services.gnucash_statements import render_income_statement


@click.command("income-statement")
@click.argument("gnucash_file", type=click.Path(exists=True))
@click.option(
    "--fiscal-year-end",
    default=None,
    callback=parse_date,
    is_eager=True,
    expose_value=True,
    help="Fiscal year end date (YYYY-MM-DD). Start is auto-computed as end − 1 year + 1 day.",
)
@click.option(
    "--start",
    default=None,
    callback=parse_date,
    is_eager=True,
    expose_value=True,
    help="Period start date (YYYY-MM-DD). Use with --end for explicit range.",
)
@click.option(
    "--end",
    default=None,
    callback=parse_date,
    is_eager=True,
    expose_value=True,
    help="Period end date (YYYY-MM-DD). Use with --start for explicit range.",
)
@click.option("--currency", default=None, help=CURRENCY_HELP)
@click.option(
    "--fx-rates",
    "fx_rates_file",
    default=None,
    type=click.Path(exists=True),
    help=RATES_HELP,
)
@click.option("--price-source", default=None, help=PRICE_SOURCE_HELP)
@click.option(
    "--output-format",
    type=click.Choice(OUTPUT_FORMATS, case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--output",
    "output_file",
    default=None,
    type=click.Path(),
    help="Output file path. Required for html/pdf. Defaults to stdout for text.",
)
def income_statement(
    gnucash_file,
    fiscal_year_end,
    start,
    end,
    currency,
    fx_rates_file,
    price_source,
    output_format,
    output_file,
):
    """
    The income statement for a period, printed by a customized GnuCash report, in the book's currency.

    \b
    Date range — use ONE of:
      --fiscal-year-end YYYY-MM-DD       (auto-computes start = end − 1 year + 1 day)
      --start YYYY-MM-DD --end YYYY-MM-DD (explicit range)

    \b
    Examples:
      Text output (calendar year 2024):
        gnucash-plaintext income-statement ledger.gnucash --fiscal-year-end 2024-12-31

      PDF, in Hong Kong dollars:
        gnucash-plaintext income-statement ledger.gnucash \\
            --start 2023-04-01 --end 2024-03-31 --currency HKD \\
            --output-format pdf --output report.pdf
    """
    if fiscal_year_end is not None and (start is not None or end is not None):
        raise click.UsageError(
            "--fiscal-year-end cannot be combined with --start/--end. Use one or the other."
        )

    if fiscal_year_end is not None:
        period_end = fiscal_year_end
        period_start = fiscal_year_start(fiscal_year_end)
    elif start is not None and end is not None:
        period_start = start
        period_end = end
    elif start is not None or end is not None:
        raise click.UsageError("Provide both --start and --end together.")
    else:
        raise click.UsageError(
            "Provide a date range: --fiscal-year-end YYYY-MM-DD  "
            "or --start YYYY-MM-DD --end YYYY-MM-DD"
        )
    if period_start > period_end:
        raise click.UsageError("--start must be on or before --end.")

    check_output(output_format, output_file)
    quotes = read_price_files(fx_rates_file, None)
    # A sink of this run's own, as `balance-sheet` and `report` make one — see
    # there for why it is not shared at module level.
    warn = said_once()

    repo = GnuCashRepository(gnucash_file)
    repo.open(SessionMode.READ_ONLY)
    try:
        report_currency = the_currency(repo.book, currency)
        add_the_files_prices(repo.book, quotes, report_currency, [period_end])
        page = render_income_statement(repo.session, report_currency, period_start, period_end,
                                       page_for(output_format), price_source=price_source,
                                       warn=warn)
    except PageNotRenderedError as refusal:
        raise click.ClickException(str(refusal)) from refusal
    finally:
        repo.close()

    write_out(page, output_format, output_file)
