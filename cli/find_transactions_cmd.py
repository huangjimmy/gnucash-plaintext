"""
CLI command to find transactions by account, date, and/or amount.

Used to discover the GUID of a bank transaction that was imported from a
bank feed and needs to be linked to an invoice payment block:

    gnucash-plaintext find-transactions ledger.gnucash \
        --account "Assets:Bank" \
        --date 2026-01-15 \
        --amount 100

Output (one line per match):
    317c8ae6e0084c33951d052b9f1b9f23  2026-01-15  100.00  "E-transfer from Acme"

Copy the GUID into the payment block's txn_guid field:

    payment:
        date: 2026-01-15
        amount: 100
        bank_account: "Assets:Bank"
        memo: "Payment INV-001"
        txn_guid: 317c8ae6e0084c33951d052b9f1b9f23
"""

from fractions import Fraction

import click

from cli._dates import parse_date
from infrastructure.gnucash.utils import (
    get_account_full_name,
    money_text,
    numeric_to_fraction,
)
from repositories.gnucash_repository import GnuCashRepository, SessionMode


def _exact_amount(ctx, param, value):
    """The figure the reader typed, as a number rather than a float.

    Read as a float and matched within half a cent, this answered about
    figures nobody asked for: a fund account kept to thousandths holds 12.345
    and 12.346 as two quantities, and a search for one returned both — and
    everything from 12.341 to 12.349 with them.
    """
    if value is None:
        return None
    try:
        return abs(Fraction(value))
    except (ValueError, ZeroDivisionError) as e:
        raise click.BadParameter(f'Amount must be a number, got: {value}') from e


@click.command('find-transactions')
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.option('--account', '-a', default=None,
              help='Account full name (e.g. "Assets:Bank"). Matches any split in the transaction.')
@click.option('--date', '-d', default=None, callback=parse_date,
              help='Transaction date filter (YYYY-MM-DD).')
@click.option('--amount', '-n', default=None, callback=_exact_amount,
              help='Absolute amount to match (sign-insensitive).')
def find_transactions(gnucash_file, account, date, amount):
    """
    Find transactions by account, date, and/or amount and print their GUIDs.

    At least one filter must be provided. Output is one matching transaction
    per line:

    \b
      GUID                              DATE        AMOUNT    DESCRIPTION
      317c8ae6e0084c33951d052b9f1b9f23  2026-01-15  100.00    E-transfer from Acme

    Use the GUID in a payment block's txn_guid field to link an existing bank
    transaction to an invoice payment without creating a duplicate.

    \b
    Examples:
      gnucash-plaintext find-transactions ledger.gnucash --account "Assets:Bank"
      gnucash-plaintext find-transactions ledger.gnucash --date 2026-01-15 --amount 100
      gnucash-plaintext find-transactions ledger.gnucash -a "Assets:Bank" -d 2026-01-15
    """
    if not any([account, date, amount is not None]):
        raise click.UsageError('At least one of --account, --date, or --amount must be provided.')

    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        matched = 0
        for tx in repo.get_all_transactions():
            tx_date = tx.GetDate().strftime('%Y-%m-%d')

            # Against a date, not the text of one. Compared as a string, a
            # `--date 2026-2-3` or `03/02/2026` matched nothing and said "no
            # transactions found" — an answer about the book, for a question
            # the command had not understood. Every other command refuses that
            # spelling by name through the same parser.
            if date and tx_date != date.isoformat():
                continue

            shown = None
            for split in tx.GetSplitList():
                split_account = split.GetAccount()
                if account is not None and (
                        get_account_full_name(split_account) != account):
                    continue
                units = abs(numeric_to_fraction(split.GetAmount()))
                if amount is not None and units != amount:
                    continue
                # The first matching split, said outright rather than by
                # letting the rest of the loop run into a test that can no
                # longer pass.
                #
                # At the unit the account holding it is kept to, which is the
                # only authority for how many decimals the figure has. Printed
                # to two whatever the commodity, 12.345 fund units came back as
                # 12.35 and ¥2,000 as 2000.00 — a quantity the account cannot
                # hold and a figure with no meaning in yen, either of which a
                # reader would then copy into a file.
                shown = money_text(units, split_account.GetCommoditySCU())
                break

            if shown is None:
                continue

            guid = tx.GetGUID().to_string()
            click.echo(f'{guid}  {tx_date}  {shown:>10}  '
                       f'"{tx.GetDescription() or ""}"')
            matched += 1

        if matched == 0:
            click.echo('No matching transactions found.', err=True)
    finally:
        repo.close()
