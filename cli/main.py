"""
GnuCash Plaintext CLI - Main entry point

This CLI provides commands to convert between GnuCash files and human-readable
plaintext format.
"""

import click

from cli.account_balance_cmd import account_balance
from cli.close_books_cmd import close_books
from cli.delete_cmd import archive_customers, archive_vendors, delete_customers
from cli.delete_transaction_cmd import delete_transaction_by_guid
from cli.export_accounts_cmd import export_accounts
from cli.export_beancount_cmd import export_beancount
from cli.export_cmd import export_transactions
from cli.export_transaction_cmd import export_transaction
from cli.import_beancount_cmd import import_beancount
from cli.import_cmd import import_transactions
from cli.income_statement_cmd import income_statement
from cli.invoice_print_cmd import print_invoice
from cli.validate_cmd import validate_ledger


@click.group()
@click.version_option(version='0.2.0', prog_name='gnucash-plaintext')
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
cli.add_command(account_balance, name='account-balance')
cli.add_command(delete_transaction_by_guid, name='delete-transaction-by-guid')
cli.add_command(delete_customers, name='delete-customers')
cli.add_command(archive_customers, name='archive-customers')
cli.add_command(archive_vendors, name='archive-vendors')


if __name__ == '__main__':
    cli()
