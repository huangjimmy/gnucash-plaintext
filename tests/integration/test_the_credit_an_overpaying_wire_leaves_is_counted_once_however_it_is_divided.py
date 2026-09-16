"""The credit an overpaying payment leaves is a cost basis, however the payment is divided.

A record for 100.00 USD, posted at 1.40, is overpaid by 100.00 USD. What is
left over is currency this book holds and is owed back — the customer's on an
invoice, this book's own on a bill — and what it cost depends on how the money
moved:

- from the CAD bank, which converted at 1.37: the credit is priced at 1.37,
  the rate the payment converted at;
- into or out of the USD bank, where no CAD figure is in the entry: the credit
  is priced at 1.40, the rate the record was carried at, stored on the split.

A file can give the payment already divided into the split that settles the
record and the rest, with `txn_split_guid:` and `prepayment:`, or as one split
the import divides. Measured on 5.10, 4.13 and 3.8, the two disagreed: divided
in the file, the credit got no cost basis balance at all — `fx-balances` read
it as "none recorded" where the money converted, and did not list it where it
did not, so the book offered 100.00 USD while its banks moved 200.00.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
RATES = FIXTURES / 'fx_rates_usd_dated.yaml'
INVOICE_ACCOUNTS = FIXTURES / 'usd_invoicing_accounts_with_a_cad_bank_and_a_usd_bank.txt'
BILL_ACCOUNTS = FIXTURES / 'fx_usd_bill_cad_expense.txt'
CREDIT = 'f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3f3'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _balances_after_importing(book, accounts, payment):
    ledger = book.parent / 'in.txt'
    ledger.write_text((FIXTURES / payment).read_text())
    first = _run('import', '--new', book, accounts, '--include-business-objects',
                 '--fx-rates', RATES)
    assert first.exit_code == 0, first.output
    imported = _run('import', book, ledger, '--include-business-objects', '--fx-rates', RATES)
    assert imported.exit_code == 0, imported.output
    return _run('fx-balances', book, '--verify-costs')


@pytest.mark.parametrize('payment,account,rate', [
    ('inv_usd_wire_overpaid_from_the_cad_bank_divided_in_the_file.txt',
     'Assets:Accounts Receivable USD', '1.37'),
    ('inv_usd_wire_overpaid_into_the_usd_bank_divided_in_the_file.txt',
     'Assets:Accounts Receivable USD', '1.4'),
])
def test_a_customers_credit_divided_in_the_file_is_priced(tmp_path, payment, account, rate):
    balances = _balances_after_importing(tmp_path / 'book.gnucash', INVOICE_ACCOUNTS, payment)

    assert balances.exit_code == 0, balances.output
    assert re.search(CREDIT + r'\s+' + re.escape(account)
                     + r'\s+' + re.escape(rate) + r' CAD/USD\s+100\.00 USD\s+100\.00 USD',
                     balances.output), balances.output
    assert 'Total USD cost basis balance: 200.00 USD' in balances.output, balances.output


@pytest.mark.parametrize('payment,rate', [
    ('bill_usd_overpaid_from_the_cad_bank_divided_in_the_file.txt', '1.37'),
    ('bill_usd_overpaid_into_the_usd_bank_divided_in_the_file.txt', '1.4'),
])
def test_what_a_bill_overpaid_leaves_divided_in_the_file_is_priced(tmp_path, payment, rate):
    balances = _balances_after_importing(tmp_path / 'book.gnucash', BILL_ACCOUNTS, payment)

    assert balances.exit_code == 0, balances.output
    assert re.search(CREDIT + r'\s+Liabilities:Accounts Payable USD'
                     r'\s+' + re.escape(rate) + r' CAD/USD\s+100\.00 USD\s+100\.00 USD',
                     balances.output), balances.output
    # BILL-USD-001 is posted by the accounts fixture and holds 100.00 USD of
    # its own, beside BILL-USD-OVER's 100.00 and the 100.00 left over.
    assert 'Total USD cost basis balance: 300.00 USD' in balances.output, balances.output
