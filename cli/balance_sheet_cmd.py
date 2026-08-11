"""CLI command: balance sheet as of a date (F-002).

`balance-sheet <book> --as-of YYYY-MM-DD [--fx-rates rates.yaml] [--output file]`

Assets / Liabilities / Equity as of the date, with a Current Year Earnings line
so it balances whether or not the books are closed.
"""
import sys
from typing import Optional

import click

from cli._dates import parse_date
from repositories.gnucash_repository import GnuCashRepository
from services.balance_sheet import BalanceSheet
from services.balance_sheet_renderer import render_text
from services.fx_rates import FxRates, MissingFxRateError


@click.command("balance-sheet")
@click.argument("gnucash_file", type=click.Path(exists=True))
@click.option("--as-of", "as_of", required=True, callback=parse_date,
              help="Balance-sheet date (YYYY-MM-DD).")
@click.option("--fx-rates", "fx_rates_file", default=None, type=click.Path(exists=True),
              help="YAML FX rates → CAD (for multi-currency T2 consolidation).")
@click.option("--prices", "prices_file", default=None, type=click.Path(exists=True),
              help="YAML security prices, per unit in each security's own trading "
                   "currency (same shape as --fx-rates). Marks Stock/Mutual Fund "
                   "holdings to market (shares × price) with an Unrealized Gains "
                   "line; a foreign-currency holding also needs --fx-rates. "
                   "Without it, securities show at cost.")
@click.option("--output", "output_file", default=None, type=click.Path(),
              help="Output file. Defaults to stdout.")
def balance_sheet(gnucash_file, as_of, fx_rates_file, prices_file, output_file):
    """Generate a balance sheet as of a date."""
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
    repo.open()
    try:
        result = BalanceSheet().compute(repo.book.get_root_account(), as_of, fx, prices)
    except (ValueError, MissingFxRateError) as e:
        raise click.ClickException(str(e)) from e
    finally:
        repo.close()

    text = render_text(result)
    if output_file:
        with open(output_file, "w") as f:
            f.write(text)
        click.echo(f"Written to {output_file}")
    else:
        click.echo(text)


if __name__ == "__main__":
    sys.exit(balance_sheet())
