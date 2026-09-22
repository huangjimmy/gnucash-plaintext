"""CLI command: several statements at once, printed by customized GnuCash reports against a single open book.

`report <book> <statement>... [--fiscal-year-end | --start --end] [--as-of] [--currency]
[--fx-rates] [--prices] [--price-source] [--fx-gain-account] [--output]`

You list the statements explicitly — `income-statement`, `balance-sheet` — so a
T2 package is one invocation and one book open, instead of one command run per
statement. Each is printed by a customized GnuCash report, in the currency the book is kept in
(Q-042). Read-only; writes the statements' text one after another.

  gnucash-plaintext report book.gnucash income-statement balance-sheet \
      --fiscal-year-end 2026-12-31
"""
import sys

import click

from cli._dates import parse_date
from cli._gnucash_statements import (
    CURRENCY_HELP,
    FX_GAIN_ACCOUNT_HELP,
    MAX_ITEMS_HELP,
    PRICE_SOURCE_HELP,
    PRICES_HELP,
    RATES_HELP,
    add_the_files_prices,
    read_price_files,
    the_currency,
)
from cli._warnings import said_once
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.fiscal_year import fiscal_year_start
from services.gnucash_report import PageNotRenderedError
from services.gnucash_statements import render_balance_sheet, render_income_statement

_STATEMENTS = ("income-statement", "balance-sheet")


@click.command("report")
@click.argument("gnucash_file", type=click.Path(exists=True))
@click.argument("statements", nargs=-1, required=True)
@click.option("--fiscal-year-end", callback=parse_date,
              help="Fiscal year end (YYYY-MM-DD); start auto-computed as end − 1 year + 1 day.")
@click.option("--start", callback=parse_date, help="Explicit period start (with --end).")
@click.option("--end", callback=parse_date, help="Explicit period end (with --start).")
@click.option("--as-of", "as_of", callback=parse_date,
              help="Balance-sheet date. Defaults to the period end.")
@click.option("--currency", default=None, help=CURRENCY_HELP)
@click.option("--fx-rates", "fx_rates_file", default=None, type=click.Path(exists=True),
              help=RATES_HELP)
@click.option("--prices", "prices_file", default=None, type=click.Path(exists=True),
              help=PRICES_HELP)
@click.option("--price-source", default=None, help=PRICE_SOURCE_HELP)
@click.option("--output", "output_file", default=None, type=click.Path(),
              help="Output file. Defaults to stdout.")
@click.option("--itemize/--no-itemize", "itemize", default=True, show_default=True,
              help="Show how the balance sheet's gain figures were worked out, "
                   "as keys nested under each — the cost bases, splits, "
                   "securities and accounts it was measured from. Keys a "
                   "parser sees, not comment lines. Applies to the balance "
                   "sheet; an income statement states no gain figure.")
@click.option("--max-items", "max_items", type=click.IntRange(min=-1), default=-1,
              show_default=True, help=MAX_ITEMS_HELP)
@click.option("--fx-gain-account", "gain_accounts", multiple=True,
              help=FX_GAIN_ACCOUNT_HELP)
def report(gnucash_file, statements, fiscal_year_end, start, end, as_of, currency,
           fx_rates_file, prices_file, price_source, output_file, itemize, max_items,
           gain_accounts):
    """Run the named statements against one open book, output combined."""
    unknown = [s for s in statements if s not in _STATEMENTS]
    if unknown:
        raise click.UsageError(
            f"unknown statement(s): {', '.join(unknown)}. "
            f"Choose from: {', '.join(_STATEMENTS)}.")

    if fiscal_year_end is not None and (start is not None or end is not None):
        raise click.UsageError("--fiscal-year-end cannot be combined with --start/--end.")
    if fiscal_year_end is not None:
        period_start, period_end = fiscal_year_start(fiscal_year_end), fiscal_year_end
    elif start is not None and end is not None:
        period_start, period_end = start, end
    else:
        raise click.UsageError(
            "Provide a period: --fiscal-year-end YYYY-MM-DD or --start … --end …")
    # As `income-statement` refuses it, and for the same reason: GnuCash draws
    # a statement over an inverted period without complaint, every figure
    # coming out zero, so nothing after this says what is wrong with the page.
    if period_start > period_end:
        raise click.UsageError("--start must be on or before --end.")
    as_of_date = as_of or period_end
    quotes = read_price_files(fx_rates_file, prices_file)
    # The day each statement asked for is for: a price given with no date is
    # added at the end of each.
    report_days = [period_end if stmt == "income-statement" else as_of_date for stmt in statements]

    # One sink for the run rather than one per statement. What the drawing
    # warns about is a property of the book — a date format GnuCash has no
    # style for, a configuration file that will not read — so the same
    # sentence would otherwise arrive once for each statement asked for.
    warn = said_once()

    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.READ_ONLY)
    parts = []
    try:
        report_currency = the_currency(repo.book, currency)
        add_the_files_prices(repo.book, quotes, report_currency, report_days)
        for stmt in statements:
            if stmt == "income-statement":
                parts.append(render_income_statement(repo.session, report_currency,
                                                     period_start, period_end,
                                                     price_source=price_source, warn=warn))
            # balance-sheet. The names are checked against `_STATEMENTS`
            # above, so there is no third case to fall through to.
            else:
                parts.append(render_balance_sheet(repo.session, report_currency, as_of_date,
                                                  price_source=price_source, warn=warn,
                                                  itemize=itemize,
                                                  gain_accounts=gain_accounts,
                                                  max_items=max_items))
    except PageNotRenderedError as refusal:
        raise click.ClickException(str(refusal)) from refusal
    finally:
        repo.close()

    # Each page ends with a newline, so one more puts a blank line between them.
    combined = "\n".join(parts)
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:   # not the locale's
            f.write(combined)
        click.echo(f"Written to {output_file}")
    else:
        click.echo(combined, nl=False)


if __name__ == "__main__":
    sys.exit(report())
