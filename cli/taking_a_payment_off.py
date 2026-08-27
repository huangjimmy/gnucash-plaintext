"""What `unapply-payment` and `unlink` both do, written once.

The two are one operation under two names — the same code, the same seven
statuses — and everything between reading the arguments and printing the
outcome is the same work: refuse `--txn` beside `--all`, parse the guids,
read `--fx-rates`, open the book, find the `--to` account, run
`execute_unapply`, save. Each command carries only what is its own: the help a
reader meets, the verb its refusals are worded with, and the lines it prints
when a payment comes off.

Written once because the copies had already drifted. The same mistyped `--to`
answered `--to account 'X' not found in the book` under one command and
`account not found: 'X'` under the other, for two commands README calls the
same operation; and the guards against `--txn --all` and an unparseable guid
existed twice with a test against one copy.
"""

from typing import List

import click

from infrastructure.gnucash.guid_lookup import normalise_guid
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.fx_rates import MissingFxRateError
from services.gnucash_importer import find_account
from services.payment_links import AccountCannotTakeTheSplitError
from use_cases.unapply_payment import (
    UnapplyResult,
    execute_unapply,
    the_reason_nothing_came_off,
)


def the_options_both_take(verb: str, to_help: str):
    """The arguments and options both commands take, in one order.

    `verb` words the help that describes an action — a reader of `unlink`
    reading "peel this payment" has been handed the other command's manual.
    `to_help` is the one option whose help genuinely differs: `unlink` says
    what the figure does, `unapply-payment` says what kind of account people
    usually give it.
    """
    options = [
        click.argument('gnucash_file', type=click.Path(exists=True)),
        click.argument('record_id'),
        click.option('--to', 'to_account_name', required=True, help=to_help),
        click.option('--txn', 'txn_guids', multiple=True,
                     help=f'{verb.capitalize()} this payment, by its '
                          f'transaction GUID. Repeatable — pass once per '
                          f'payment to take a subset off.'),
        click.option('--all', 'take_all', is_flag=True, default=False,
                     help=f'{verb.capitalize()} every payment on the record.'),
        click.option('--bill', 'is_bill', is_flag=True, default=False,
                     help='Target a vendor bill instead of a customer invoice.'),
        click.option('--by-guid', 'by_guid', is_flag=True, default=False,
                     help='Resolve RECORD_ID as an invoice/bill GUID rather '
                          'than its id.'),
        click.option('--fx-rates', 'fx_rates_file', type=click.Path(exists=True),
                     help='Rates file, for a --to account kept in the book\'s '
                          'own currency where the payment split carries no '
                          'figure in it. Read at the transaction\'s own date. '
                          'An account in a third foreign currency is refused '
                          'whatever is passed.'),
    ]

    def decorate(command):
        for option in reversed(options):
            command = option(command)
        return command

    return decorate


def take_the_payment_off(gnucash_file: str, record_id: str,
                         to_account_name: str, *, txn_guids, take_all: bool,
                         is_bill: bool, by_guid: bool, fx_rates_file,
                         verb: str) -> UnapplyResult:
    """Take the payment(s) off the record and save, or raise a message.

    The book is saved before this returns, so a command cannot announce a
    payment that a failed save did not write. Every refusal leaves the book as
    it was found: `execute_unapply` works every figure out before it changes
    the first account.

    Raises `click.ClickException` or `click.UsageError` — never anything a
    reader would meet as a traceback. Click's standalone mode catches neither
    `AccountCannotTakeTheSplitError` nor `MissingFxRateError`, and both are
    refusals that say what would answer them, so both are wrapped here.
    """
    if txn_guids and take_all:
        raise click.ClickException('--txn and --all are mutually exclusive.')
    try:
        guids: List[str] = [normalise_guid(g) for g in txn_guids]
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    fx_rates = None
    if fx_rates_file:
        from services.fx_rates import FxRates
        try:
            fx_rates = FxRates.load(fx_rates_file)
        except (OSError, ValueError) as exc:
            raise click.UsageError(
                f'Could not read --fx-rates file: {exc}') from exc

    repo = GnuCashRepository(gnucash_file)
    repo.open(mode=SessionMode.NORMAL)
    try:
        to_account = find_account(repo.book.get_root_account(), to_account_name)
        if to_account is None:
            raise click.ClickException(
                f'--to account {to_account_name!r} not found in the book')
        result = execute_unapply(repo.book, record_id, to_account,
                                 is_bill=is_bill, by_guid=by_guid,
                                 txn_guids=guids, unapply_all=take_all,
                                 fx_rates=fx_rates)
        if result.status != 'unapplied':
            raise click.ClickException(
                the_reason_nothing_came_off(result, verb=verb))
        repo.save()
    except click.ClickException:
        raise
    except (AccountCannotTakeTheSplitError, MissingFxRateError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        repo.close()
    return result
