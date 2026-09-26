"""
GnuCash Plaintext CLI - Main entry point

This CLI provides commands to convert between GnuCash files and human-readable
plaintext format.
"""

import os

import click

from cli.account_balance_cmd import account_balance
from cli.balance_sheet_cmd import balance_sheet
from cli.bill_print_cmd import print_bill
from cli.close_books_cmd import close_books
from cli.cost_basis_cmd import fx_balances
from cli.delete_cmd import (
    archive_customers,
    archive_vendors,
    delete_bills,
    delete_customers,
    delete_invoices,
)
from cli.delete_transaction_cmd import delete_transactions
from cli.export_accounts_cmd import export_accounts
from cli.export_beancount_cmd import export_beancount
from cli.export_cmd import export_transactions
from cli.export_prices_cmd import export_prices
from cli.export_transaction_cmd import export_transaction
from cli.find_orphan_payments_cmd import find_orphan_payments
from cli.find_prepayments_cmd import find_prepayments
from cli.find_transactions_cmd import find_transactions
from cli.import_beancount_cmd import import_beancount
from cli.import_cmd import import_transactions
from cli.income_statement_cmd import income_statement
from cli.invoice_print_cmd import print_invoice
from cli.migrate_cmd import migrate
from cli.rename_account_cmd import rename_account
from cli.report_cmd import report
from cli.set_book_key_cmd import set_book_key
from cli.set_invoice_style_cmd import set_invoice_style
from cli.unapply_cmd import unapply_payment
from cli.unlink_cmd import unlink
from cli.unpost_cmd import unpost_bills, unpost_invoices
from cli.validate_cmd import validate_ledger
from cli.verify_integrity_cmd import VERIFY_HELP, verify_integrity, verify_the_book
from infrastructure.guile import GuileUnavailableError
from infrastructure.pdf.printing import PdfEngineUnavailableError
from repositories.gnucash_repository import BookUnavailableError
from services.gnucash_report import PageNotRenderedError


class _Cli(click.Group):
    """The group every command hangs off, so what a command cannot do is
    answered once rather than in thirty places.

    Each of these is already written as a sentence for a person to read — a
    book that will not open, a machine with no Scheme interpreter to draw an
    invoice with, one with no PDF engine to lay the page out, a page
    GnuCash's report declined to draw. Commands that wrap the call print it
    themselves; the ones that do not would let it out as a traceback, and a
    refusal a reader cannot read tells them nothing about what to do next.
    Caught here, all of them say the same thing.

    **`--verify-integrity` is answered here too**, and for the same reason: it
    applies to every command that writes a book, and adding an option to each
    of the twenty that do would be twenty chances to spell it differently or
    leave it off. Passed before the command, it runs the check once the command
    has finished and saved. Passed with no command at all, the token after it is
    a book to check rather than a command to run, and `resolve_command` says so
    — a `click.Group` otherwise refuses an unknown command before the callback
    is ever reached.
    """

    def resolve_command(self, ctx, args):
        if ctx.params.get('verify_integrity') and args[0] not in self.commands:
            # A token that is neither a command nor a file is most likely a
            # command mistyped, so both are said rather than a missing book.
            if not os.path.exists(args[0]):
                raise click.UsageError(
                    f"No such command '{args[0]}', and no book at that path to "
                    f"check.", ctx=ctx)
            return 'verify-integrity', self.commands['verify-integrity'], args
        name, command, rest = super().resolve_command(ctx, args)
        # Kept because Click hands the command its own context and does not
        # keep it: a group sees only its own parameters afterwards, and the
        # book passed to the command is in the command's. A copy of the
        # arguments, because Click parses that very list by taking items off
        # it, so the list itself is empty by the time the command returns.
        ctx.meta['dispatched'] = (name, command, list(rest))
        return name, command, rest

    def invoke(self, ctx):
        try:
            outcome = super().invoke(ctx)
        except (BookUnavailableError, PageNotRenderedError,
                GuileUnavailableError, PdfEngineUnavailableError) as e:
            raise click.ClickException(str(e)) from e
        except SystemExit as leaving:
            # Several commands end by exiting with a code of their own — an
            # import that reports errors exits 1 — and a check that ran only
            # where a command returned normally would silently skip exactly
            # the runs worth checking. The book is checked, and the command's
            # own code is kept where the check passes; where it fails, the run
            # ends on the check's refusal and exits 1.
            #
            # A command that ends by raising `click.ClickException`, or by
            # `ctx.exit()` — Click's `Exit`, which is not a `SystemExit` — is
            # not checked: every command that writes reports its errors and
            # exits with a code, or refuses before it saves. One that saved
            # and then ended either way would need catching here as well.
            _check_what_the_command_wrote(ctx)
            raise leaving
        _check_what_the_command_wrote(ctx)
        return outcome


def _the_parsed_command(ctx):
    """The subcommand's own arguments, read back after it has run.

    Parsed a second time, with `resilient_parsing`, because Click's own parse
    happens inside a context it discards. Nothing is prompted for and no eager
    option acts under that flag, so the second parse asks the machine nothing
    and answers only the questions the check has: which book, and whether the
    run was a dry run.
    """
    name, command, args = ctx.meta['dispatched']
    return name, command, command.make_context(name, list(args), parent=ctx,
                                               resilient_parsing=True)


def _the_book_passed_to_the_command(command, parsed):
    """The book passed to a subcommand, read out of its own arguments.

    **There is always one to answer with.** Every command takes a book under
    one of the three names below — every registered command was listed and
    read — and a run that passes none is refused by Click or by the command
    itself before anything happens, a `UsageError` that ends the run without
    reaching the check. A command added with its book under another name
    would hand the check the string `'None'`, which then reports that no book
    is at that path; use one of these three names.

    `gnucash_file` is the positional book on every command. The same book is
    `gnucash_path` behind `-i/--input` on `import` and behind `-o/--output` on
    `import-beancount`, and `input_file` behind `-i/--input` on `export`,
    `export-transaction`, `validate` and `export-beancount`. `input_file` is
    read only as that option: `import`'s `input_file` is the plaintext ledger,
    a positional argument, and checking that would open the wrong file.
    """
    behind_the_input_flag = any(
        param.name == 'input_file' and '-i' in getattr(param, 'opts', ())
        for param in command.params)
    return str(parsed.params.get('gnucash_file')
               or parsed.params.get('gnucash_path')
               or (parsed.params.get('input_file') if behind_the_input_flag else None))


def _check_what_the_command_wrote(ctx) -> None:
    """Reopen the book passed to the command and check it, where asked.

    Reopened rather than asked of the session the command used, because what is
    worth checking is the book on disk — the one the next command will read.

    The standalone spelling is left alone: it does the check itself and would
    otherwise do it twice.
    """
    if not ctx.params.get('verify_integrity'):
        return
    if ctx.invoked_subcommand in (None, 'verify-integrity'):
        return
    # A command that refused before saving leaves no book to reopen — an
    # `import --new` whose ledger GnuCash would not take. Its own refusal is
    # already printed; this says the check found nothing to read, where a
    # traceback said nothing a reader could use.
    _name, command, parsed = _the_parsed_command(ctx)
    # A dry run writes nothing — `import-beancount -o new.gnucash --dry-run`
    # leaves no book at all — so there is nothing the command did to check.
    if parsed.params.get('dry_run'):
        click.echo('--verify-integrity: a dry run writes nothing, so there is '
                   'nothing to check.')
        return
    try:
        report = verify_the_book(_the_book_passed_to_the_command(command, parsed))
    except (BookUnavailableError, PageNotRenderedError,
            GuileUnavailableError) as e:
        raise click.ClickException(f'the book could not be checked: {e}') from e
    if not report.passed:
        raise click.ClickException(
            f'this command left the book with {len(report.findings)} thing(s) '
            f'wrong with it, each printed above')


@click.group(cls=_Cli, invoke_without_command=True)
@click.option('--verify-integrity', 'verify_integrity', is_flag=True,
              is_eager=True, help=VERIFY_HELP)
@click.version_option(version='0.4.0', prog_name='gnucash-plaintext')
@click.pass_context
def cli(ctx, verify_integrity):
    """
    GnuCash Plaintext - Work with GnuCash files in plaintext format.

    Convert GnuCash transactions to/from human-readable plaintext.

    \b
    Examples:
      Export transactions:
        $ gnucash-plaintext export ledger.gnucash transactions.txt

    \b
      Import transactions:
        $ gnucash-plaintext import ledger.gnucash transactions.txt

    \b
      Validate ledger:
        $ gnucash-plaintext validate ledger.gnucash

    \b
      Check whether a book is consistent and balanced, after a command
      that writes it or on its own:
        $ gnucash-plaintext --verify-integrity import ledger.gnucash today.txt
        $ gnucash-plaintext --verify-integrity ledger.gnucash
    """
    if ctx.invoked_subcommand is None and verify_integrity:
        raise click.UsageError(
            '--verify-integrity takes a book to check, or a command to run '
            'before checking the book that command works on', ctx=ctx)
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        ctx.exit()


# Register commands
cli.add_command(export_transactions, name='export')
cli.add_command(export_accounts, name='export-accounts')
cli.add_command(export_prices, name='export-prices')
cli.add_command(import_transactions, name='import')
cli.add_command(validate_ledger, name='validate')
cli.add_command(export_beancount, name='export-beancount')
cli.add_command(import_beancount, name='import-beancount')
cli.add_command(close_books, name='close-books')
cli.add_command(export_transaction, name='export-transaction')
cli.add_command(income_statement, name='income-statement')
cli.add_command(balance_sheet, name='balance-sheet')
cli.add_command(report, name='report')
cli.add_command(print_invoice, name='print-invoice')
cli.add_command(print_bill, name='print-bill')
cli.add_command(account_balance, name='account-balance')
cli.add_command(delete_transactions, name='delete-transactions')
cli.add_command(find_transactions, name='find-transactions')
cli.add_command(delete_customers, name='delete-customers')
cli.add_command(delete_invoices, name='delete-invoices')
cli.add_command(delete_bills, name='delete-bills')
cli.add_command(archive_customers, name='archive-customers')
cli.add_command(archive_vendors, name='archive-vendors')
cli.add_command(unpost_invoices, name='unpost-invoices')
cli.add_command(unpost_bills, name='unpost-bills')
cli.add_command(unapply_payment, name='unapply-payment')
cli.add_command(unlink, name='unlink')
cli.add_command(rename_account, name='rename-account')
cli.add_command(set_book_key, name='set-book-key')
cli.add_command(set_invoice_style, name='set-invoice-style')
cli.add_command(migrate, name='migrate')
cli.add_command(find_orphan_payments, name='find-orphan-payments')
cli.add_command(find_prepayments, name='find-prepayments')
cli.add_command(fx_balances, name='fx-balances')
cli.add_command(verify_integrity, name='verify-integrity')


if __name__ == '__main__':
    cli()
