"""
GnuCash Plaintext CLI - Main entry point

This CLI provides commands to convert between GnuCash files and human-readable
plaintext format.
"""

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
from cli.unpost_cmd import unpost_bills, unpost_invoices
from cli.validate_cmd import validate_ledger
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
    """

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except (BookUnavailableError, PageNotRenderedError,
                GuileUnavailableError, PdfEngineUnavailableError) as e:
            raise click.ClickException(str(e)) from e


@click.group(cls=_Cli)
@click.version_option(version='0.4.0', prog_name='gnucash-plaintext')
def cli():
    """
    GnuCash Plaintext - Work with GnuCash files in plaintext format.

    Convert GnuCash transactions to/from human-readable plaintext.

    \b
    Examples:
      Export transactions:
        $ gnucash-plaintext export ledger.gnucash transactions.txt

      Import transactions:
        $ gnucash-plaintext import ledger.gnucash transactions.txt

      Validate ledger:
        $ gnucash-plaintext validate ledger.gnucash
    """
    pass


# Register commands
cli.add_command(export_transactions, name='export')
cli.add_command(export_accounts, name='export-accounts')
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
cli.add_command(rename_account, name='rename-account')
cli.add_command(set_book_key, name='set-book-key')
cli.add_command(set_invoice_style, name='set-invoice-style')
cli.add_command(migrate, name='migrate')
cli.add_command(find_orphan_payments, name='find-orphan-payments')
cli.add_command(find_prepayments, name='find-prepayments')
cli.add_command(fx_balances, name='fx-balances')


if __name__ == '__main__':
    cli()
