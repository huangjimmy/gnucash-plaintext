"""
CLI command for closing books at fiscal year end.

Implements the 'close-books' subcommand which zeroes out all Income/Expense
accounts and transfers net income to Equity:Retained Earnings:{currency}.
"""

from datetime import date, datetime

import click

from repositories.gnucash_repository import GnuCashRepository
from use_cases.close_books import AlreadyClosedError, CloseBooksUseCase


def _parse_date(ctx, param, value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise click.BadParameter(f"Date must be in YYYY-MM-DD format, got: {value}") from e


@click.command("close-books")
@click.argument("gnucash_file", type=click.Path(exists=True))
@click.option(
    "--closing-date",
    required=True,
    callback=_parse_date,
    is_eager=True,
    expose_value=True,
    help="Date to close books (YYYY-MM-DD)",
)
@click.option(
    "--equity-account",
    default="Equity:Retained Earnings",
    show_default=True,
    help="Base path for retained earnings accounts",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Delete existing closing entries and re-close",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview what would be closed without making changes",
)
@click.option(
    "--status",
    is_flag=True,
    default=False,
    help="Check closing status without making changes",
)
def close_books(gnucash_file, closing_date, equity_account, force, dry_run, status):
    """
    Close books for fiscal year (per-currency closing).

    Zeroes out all Income/Expense account balances as of CLOSING_DATE and
    transfers net income to Equity:Retained Earnings:{currency} — one
    closing transaction per currency.

    \b
    Examples:
      Close books for 2024:
        gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31

      Preview closing without changes:
        gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31 --dry-run

      Check if already closed:
        gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31 --status

      Re-close (e.g. after adding missed transactions):
        gnucash-plaintext close-books mybook.gnucash --closing-date 2024-12-31 --force
    """
    repo = GnuCashRepository(gnucash_file)
    repo.open()

    try:
        use_case = CloseBooksUseCase(repo)

        if status:
            is_closed = use_case.check_status(closing_date)
            if is_closed:
                click.echo(f"Books are CLOSED as of {closing_date}")
                click.echo(
                    "All Income/Expense accounts have zero balance on this date."
                )
            else:
                click.echo(f"Books are OPEN as of {closing_date}")
                click.echo(
                    "Some Income/Expense accounts have non-zero balances on this date."
                )
            return

        try:
            result = use_case.execute(
                closing_date=closing_date,
                equity_template=equity_account,
                force=force,
                dry_run=dry_run,
            )
        except AlreadyClosedError as e:
            click.echo(f"Error: {e}", err=True)
            raise click.Abort() from e

        if not dry_run:
            repo.save()

        click.echo(result.get_summary())

    finally:
        repo.close()
