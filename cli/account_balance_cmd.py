"""
CLI command for exporting account balances as of a given date.

Output format (balance directive):

    YYYY-MM-DD balance
        Account:Path  Amount Currency

No ACCOUNT_PREFIX:
    All accounts in the book (parent + leaf), each with its recursive cumulative
    balance.  Mixed-currency accounts require FX rates (from --fx-rates or the
    GnuCash pricedb); an error is raised when no rate is available.

With ACCOUNT_PREFIX (default):
    Only the matched account, with its recursive cumulative balance.

With ACCOUNT_PREFIX + --with-children:
    The matched account and all sub-accounts, each with their recursive balance.

With --fx-rates:
    Updates GnuCash pricedb for changed rates (today's date), then outputs all
    shown accounts consolidated to CAD.
"""

from datetime import date, datetime
from typing import Optional

import click

from infrastructure.gnucash.utils import money_text
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.fx_rates import FxRates, MissingFxRateError
from use_cases.account_balance import AccountBalanceUseCase


def _parse_date(ctx, param, value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise click.BadParameter(f"Date must be in YYYY-MM-DD format, got: {value}") from e


def _format_amount(amount, unit: int) -> str:
    """A balance at its own currency's decimals — 1200.00 CAD, 103 JPY.

    Exact: the figure reaches that unit through GnuCash's rounding, never a
    float whose nearest double sits a cent below the half.
    """
    return money_text(amount, unit)


@click.command("account-balance")
@click.argument("gnucash_file", type=click.Path(exists=True))
@click.argument("account_prefix", required=False, default=None)
@click.option(
    "--as-of",
    "as_of_str",
    default=None,
    callback=_parse_date,
    is_eager=True,
    expose_value=True,
    help="Balance date (YYYY-MM-DD). Defaults to today.",
)
@click.option(
    "--fx-rates",
    "fx_rates_file",
    default=None,
    type=click.Path(exists=True),
    help="YAML file with currency->CAD rates. Consolidates all accounts to CAD "
         "and writes updated rates to the GnuCash pricedb.",
)
@click.option(
    "--with-children",
    "with_children",
    is_flag=True,
    default=False,
    help="When ACCOUNT_PREFIX is given, also show all sub-accounts with their "
         "individual recursive balances.",
)
@click.option(
    "--output",
    "-o",
    "output_file",
    default=None,
    type=click.Path(),
    help="Output file path. Defaults to stdout.",
)
def account_balance(
    gnucash_file,
    account_prefix,
    as_of_str,
    fx_rates_file,
    with_children,
    output_file,
):
    """
    Output account balances as of a given date in balance directive format.

    Each account balance is the recursive cumulative sum of the account and
    all its sub-accounts.

    Without ACCOUNT_PREFIX: outputs every account in the book.
    With ACCOUNT_PREFIX: outputs only that account (use --with-children for breakdown).

    \b
    Format:
      YYYY-MM-DD balance
          Account:Path  Amount Currency

    \b
    Examples:
      Whole book (all accounts, recursive totals):
        gnucash-plaintext account-balance ledger.gnucash

      Single account total:
        gnucash-plaintext account-balance ledger.gnucash "Assets:Bank"

      Account with sub-account breakdown:
        gnucash-plaintext account-balance ledger.gnucash "Assets:Bank" --with-children

      As of a specific date:
        gnucash-plaintext account-balance ledger.gnucash --as-of 2024-12-31

      With FX consolidation to CAD (updates pricedb):
        gnucash-plaintext account-balance ledger.gnucash \\
            --as-of 2024-12-31 --fx-rates rates.yaml
    """
    as_of: date = as_of_str if as_of_str is not None else date.today()

    # Load FX rates if provided
    fx_rates: Optional[FxRates] = None
    if fx_rates_file:
        try:
            fx_rates = FxRates.load(fx_rates_file)
        except (FileNotFoundError, ValueError) as e:
            raise click.ClickException(str(e)) from e

    # Open in NORMAL mode when fx_rates provided (need to write pricedb),
    # otherwise read-only.
    mode = SessionMode.NORMAL if fx_rates is not None else SessionMode.READ_ONLY
    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=mode)

    try:
        use_case = AccountBalanceUseCase(repo)

        # Update pricedb before computing balances (so the balance uses fresh rates)
        if fx_rates is not None:
            today = date.today()
            try:
                use_case.update_pricedb(fx_rates, today)
            except Exception as e:
                raise click.ClickException(f"Failed to update pricedb: {e}") from e

        try:
            result = use_case.execute(
                as_of=as_of,
                account_prefix=account_prefix,
                fx_rates=fx_rates,
                include_children=with_children,
            )
        except MissingFxRateError as e:
            raise click.ClickException(str(e)) from e
        except ValueError as e:
            raise click.ClickException(str(e)) from e

        # Save if we wrote to pricedb.
        # GnuCash raises GnuCashBackendException when the backup file already
        # exists (e.g. same-second saves in tests). The XML data is still
        # written; ignore backup-only failures.
        if fx_rates is not None:
            try:
                repo.save()
            except Exception as e:
                if "ERR_FILEIO_BACKUP_ERROR" not in str(e):
                    raise click.ClickException(f"Failed to save: {e}") from e

    finally:
        repo.close()

    # Render output
    lines = []
    date_str = as_of.strftime("%Y-%m-%d")
    lines.append(f"{date_str} balance")
    for bal in result.balances:
        amount_str = _format_amount(bal.amount, bal.unit)
        lines.append(f"\t{bal.account_path}  {amount_str} {bal.currency}")
        if bal.share_price is not None and bal.original_amount is not None:
            # Show exchange rate and original amount, matching the transaction plaintext format
            lines.append(
                f"\t\tshare_price: \"{bal.share_price.numerator}/{bal.share_price.denominator}\""
            )
            lines.append(
                f"\t\toriginal: \""
                f"{_format_amount(bal.original_amount, bal.original_unit)} "
                f"{bal.original_currency}\""
            )

    output = "\n".join(lines) + "\n"

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output)
        click.echo(f"Written to {output_file}")
    else:
        click.echo(output, nl=False)
