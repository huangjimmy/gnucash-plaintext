"""CLI command: run one or more named statements against a single open book.

`report <book> <statement>... [--fiscal-year-end | --start --end] [--as-of] [--fx-rates] [--output]`

You name the statements explicitly — `income-statement`, `balance-sheet` — so a
T2 package is one invocation and one (expensive) book open, instead of N command
runs. `report` is GnuCash's own term for these. Read-only; emits the statements
concatenated.

  gnucash-plaintext report book.gnucash income-statement balance-sheet \
      --fiscal-year-end 2026-12-31
"""
import sys
from datetime import datetime
from typing import Optional

import click

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.balance_sheet import BalanceSheet
from services.balance_sheet_renderer import render_text as bs_render_text
from services.fx_rates import FxRates, MissingFxRateError
from services.income_statement_renderer import render_text as is_render_text
from use_cases.generate_income_statement import (
    GenerateIncomeStatementUseCase,
    fiscal_year_start,
)

_STATEMENTS = ("income-statement", "balance-sheet")


def _parse_date(ctx, param, value):
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise click.BadParameter(f"Date must be YYYY-MM-DD, got: {value}") from e


@click.command("report")
@click.argument("gnucash_file", type=click.Path(exists=True))
@click.argument("statements", nargs=-1, required=True)
@click.option("--fiscal-year-end", callback=_parse_date,
              help="Fiscal year end (YYYY-MM-DD); start auto-computed as end − 1 year + 1 day.")
@click.option("--start", callback=_parse_date, help="Explicit period start (with --end).")
@click.option("--end", callback=_parse_date, help="Explicit period end (with --start).")
@click.option("--as-of", "as_of", callback=_parse_date,
              help="Balance-sheet date. Defaults to the period end.")
@click.option("--fx-rates", "fx_rates_file", default=None, type=click.Path(exists=True),
              help="YAML FX rates → CAD (for multi-currency T2 consolidation).")
@click.option("--prices", "prices_file", default=None, type=click.Path(exists=True),
              help="YAML security prices, per unit in each security's own trading "
                   "currency (same shape as --fx-rates). Marks Stock/Mutual Fund "
                   "holdings to market on the balance sheet, with an Unrealized "
                   "Gains line; a foreign-currency holding also needs --fx-rates.")
@click.option("--output", "output_file", default=None, type=click.Path(),
              help="Output file. Defaults to stdout.")
def report(gnucash_file, statements, fiscal_year_end, start, end, as_of,
           fx_rates_file, prices_file, output_file):
    """Run the named statements against one open book, output combined."""
    unknown = [s for s in statements if s not in _STATEMENTS]
    if unknown:
        raise click.UsageError(
            f"unknown statement(s): {', '.join(unknown)}. "
            f"Choose from: {', '.join(_STATEMENTS)}.")

    # Resolve the period (income statement) and the as-of date (balance sheet).
    if fiscal_year_end is not None and (start is not None or end is not None):
        raise click.UsageError("--fiscal-year-end cannot be combined with --start/--end.")
    if fiscal_year_end is not None:
        period_start, period_end = fiscal_year_start(fiscal_year_end), fiscal_year_end
    elif start is not None and end is not None:
        period_start, period_end = start, end
    else:
        raise click.UsageError(
            "Provide a period: --fiscal-year-end YYYY-MM-DD or --start … --end …")
    as_of_date = as_of or period_end

    fx: Optional[FxRates] = None
    if fx_rates_file:
        try:
            fx = FxRates.load(fx_rates_file)
        except (FileNotFoundError, ValueError) as e:
            raise click.ClickException(str(e)) from e

    prices: Optional[FxRates] = None
    if prices_file:
        try:
            prices = FxRates.load(prices_file)
        except (FileNotFoundError, ValueError) as e:
            raise click.ClickException(str(e)) from e

    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.READ_ONLY)
    parts = []
    try:
        root = repo.book.get_root_account()
        for stmt in statements:
            if stmt == "income-statement":
                result = GenerateIncomeStatementUseCase(repo).execute(
                    start_date=period_start, end_date=period_end, fx_rates=fx)
                parts.append(is_render_text(result))
            elif stmt == "balance-sheet":
                parts.append(bs_render_text(
                    BalanceSheet().compute(root, as_of_date, fx, prices)))
    except (ValueError, MissingFxRateError) as e:
        raise click.ClickException(str(e)) from e
    finally:
        repo.close()

    combined = "\n\n".join(parts)
    if output_file:
        with open(output_file, "w") as f:
            f.write(combined)
        click.echo(f"Written to {output_file}")
    else:
        click.echo(combined)


if __name__ == "__main__":
    sys.exit(report())
