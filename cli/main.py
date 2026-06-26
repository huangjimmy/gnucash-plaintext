"""
GnuCash Plaintext CLI - Main entry point

This CLI provides commands to convert between GnuCash files and human-readable
plaintext format.
"""

import click

from cli.account_balance_cmd import account_balance
from cli.bill_print_cmd import print_bill
from cli.close_books_cmd import close_books
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
from cli.rename_account_cmd import rename_account
from cli.unapply_cmd import unapply_payment
from cli.unpost_cmd import unpost_bills, unpost_invoices
from cli.validate_cmd import validate_ledger


@click.group()
@click.version_option(version='0.3.3', prog_name='gnucash-plaintext')
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
cli.add_command(find_orphan_payments, name='find-orphan-payments')
cli.add_command(find_prepayments, name='find-prepayments')


if __name__ == '__main__':
    cli()
