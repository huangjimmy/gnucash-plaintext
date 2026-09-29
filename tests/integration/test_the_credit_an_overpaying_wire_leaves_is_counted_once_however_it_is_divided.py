"""The credit an overpaying payment leaves is a cost basis, however the payment is divided.

A record for 100.00 USD, posted at 1.40, is overpaid by 100.00 USD. What is
left over is the customer's credit on an invoice, owed back — a liability cost
basis — and this book's own claim on a bill, held with the vendor — an asset
cost basis (Q-054). Its cost is the payment's:

- from or into the CAD bank, which converted at 1.37: the rate the payment
  converted at, stated in the entry. The record's part is converted too, so
  it consumes the record's cost basis, and the file states it and where the
  difference from the record's 1.40 goes;
- into or out of the USD bank, where no CAD figure is in the entry: the rates
  file's 1.37 for the payment's day, stored on the split. The bank's split
  opens a cost basis of its own for the 100.00 past the record, on the other
  side from the credit: held into the bank for an invoice, owed on a bank
  holding none for a bill.

A file can state the payment already divided into the split that settles the
record and the rest, with `txn_split_guid:` and `prepayment:`, or as one split
the import divides. Measured on 5.10, 4.13 and 3.8, the two disagreed: divided
in the file, the credit got no cost basis balance at all — `fx-balances` read
it as "none recorded" where the money converted, and did not list it where it
did not, so the book offered 100.00 USD while its banks moved 200.00.
"""

import re
from pathlib import Path

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


def test_a_customers_credit_divided_in_the_file_from_the_cad_bank_is_priced(tmp_path):
    """The invoice collected into Canadian dollars, and the credit owed at 1.37.

    The settling split states the invoice's cost basis and is valued at its
    1.40, so the invoice's cost basis goes to 0.00 and Income:FX Gain takes
    the 3.00 CAD between the 140.00 CAD it cost and its proceeds of 137.00 CAD.
    """
    book = tmp_path / 'book.gnucash'
    balances = _balances_after_importing(
        book, INVOICE_ACCOUNTS,
        'inv_usd_wire_overpaid_from_the_cad_bank_stating_the_invoices_cost_basis.txt')

    assert balances.exit_code == 0, balances.output
    assert re.search(r'c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1\s+Assets:Accounts Receivable USD\s+'
                     r'1\.4 CAD/USD\s+100\.00 USD\s+0\.00 USD\s+asset', balances.output), \
        balances.output
    assert re.search(CREDIT + r'\s+Assets:Accounts Receivable USD\s+1\.37 CAD/USD\s+'
                     r'100\.00 USD\s+100\.00 USD\s+liability', balances.output), balances.output
    assert ('Total USD cost basis balance: 0.00 USD held, 100.00 USD owed'
            in balances.output), balances.output
    integrity = _run('--verify-integrity', book)
    assert integrity.exit_code == 0, integrity.output


def test_a_customers_credit_divided_in_the_file_into_the_usd_bank_is_priced(tmp_path):
    """The credit owed at the payment's 1.37, and the bank's 100.00 held at the same.

    The rates file gives 1.37 for the payment's day, and the transaction states
    no Canadian dollar figure, so both cost bases the overpayment opens take
    it, as they do where GnuCash writes the payment (Q-054).
    """
    book = tmp_path / 'book.gnucash'
    balances = _balances_after_importing(
        book, INVOICE_ACCOUNTS, 'inv_usd_wire_overpaid_into_the_usd_bank_divided_in_the_file.txt')

    assert balances.exit_code == 0, balances.output
    assert re.search(CREDIT + r'\s+Assets:Accounts Receivable USD\s+1\.37 CAD/USD\s+'
                     r'100\.00 USD\s+100\.00 USD\s+liability', balances.output), balances.output
    assert re.search(r'Assets:Bank:USD\s+1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+asset',
                     balances.output), balances.output
    assert ('Total USD cost basis balance: 200.00 USD held, 100.00 USD owed'
            in balances.output), balances.output
    assert _run('--verify-integrity', book).exit_code == 0


def test_what_a_bill_overpaid_from_the_cad_bank_leaves_divided_in_the_file_is_priced(tmp_path):
    """The bill paid in Canadian dollars, and the vendor's debt held at 1.37.

    BILL-USD-001, posted by the accounts fixture, is still owed. BILL-USD-OVER
    is paid: its cost basis goes to 0.00, and Income:FX Gain takes the 3.00 CAD
    between the 140.00 it was carried at and the 137.00 it cost.
    """
    book = tmp_path / 'book.gnucash'
    balances = _balances_after_importing(
        book, BILL_ACCOUNTS, 'bill_usd_overpaid_from_the_cad_bank_stating_the_bills_cost_basis.txt')

    assert balances.exit_code == 0, balances.output
    assert re.search(r'c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1\s+Liabilities:Accounts Payable USD\s+'
                     r'1\.4 CAD/USD\s+100\.00 USD\s+0\.00 USD\s+liability', balances.output), \
        balances.output
    assert re.search(CREDIT + r'\s+Liabilities:Accounts Payable USD\s+1\.37 CAD/USD\s+'
                     r'100\.00 USD\s+100\.00 USD\s+asset', balances.output), balances.output
    assert ('Total USD cost basis balance: 100.00 USD held, 100.00 USD owed'
            in balances.output), balances.output
    integrity = _run('--verify-integrity', book)
    assert integrity.exit_code == 0, integrity.output


def test_what_a_bill_overpaid_out_of_the_usd_bank_leaves_divided_in_the_file_is_priced(tmp_path):
    """The bill paid out of a US dollar bank holding none: the bank owes 200.00.

    The first 100.00 the bank owes is BILL-USD-OVER paid, and the bill's cost
    basis stands for it. The other 100.00 went to the vendor, who holds it
    against the next bill: an asset cost basis on the payable, and a liability
    cost basis of the same 100.00 on the bank, both at the rates file's 1.37.
    """
    book = tmp_path / 'book.gnucash'
    balances = _balances_after_importing(
        book, BILL_ACCOUNTS, 'bill_usd_overpaid_into_the_usd_bank_divided_in_the_file.txt')

    assert balances.exit_code == 0, balances.output
    assert re.search(CREDIT + r'\s+Liabilities:Accounts Payable USD\s+1\.37 CAD/USD\s+'
                     r'100\.00 USD\s+100\.00 USD\s+asset', balances.output), balances.output
    assert re.search(r'Assets:Bank:USD\s+1\.37 CAD/USD\s+100\.00 USD\s+100\.00 USD\s+liability',
                     balances.output), balances.output
    # BILL-USD-001's 100.00, BILL-USD-OVER's 100.00 and the bank's 100.00.
    assert ('Total USD cost basis balance: 100.00 USD held, 300.00 USD owed'
            in balances.output), balances.output
    integrity = _run('--verify-integrity', book)
    assert integrity.exit_code == 0, integrity.output
