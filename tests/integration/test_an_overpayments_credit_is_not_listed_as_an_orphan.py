"""An overpayment's credit is not listed as an orphan, and a payment an unpost left behind still is.

A payment larger than its invoice settles the invoice and leaves the rest in a
credit lot that no invoice was ever linked to. `find-orphan-payments` listed that
payment as an orphan whose invoice "was unposted", with advice to delete it,
while `find-prepayments` listed the same money as the customer's credit. The
invoice was posted and paid the whole time.

The second and third tests are books GnuCash unposted itself, which carry no
record of the unpost from this tool: one payment of one invoice, and one payment
settling two invoices of which one was unposted. Both payments are still listed.
"""

from datetime import datetime

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert result.exit_code == 0, result.output
    return str(book)


def _through_gnucash(book_path, build):
    """Open the book, hand `build` a function that posts a 100.00 invoice, and save."""
    from gnucash import GncNumeric
    from gnucash.gnucash_business import Customer, Entry, Invoice

    from infrastructure.gnucash.utils import find_account

    repo = GnuCashRepository(book_path)
    repo.open(SessionMode.NORMAL)
    try:
        book = repo.book
        cad = book.get_table().lookup('CURRENCY', 'CAD')
        root = book.get_root_account()
        customer = Customer(book, 'C001', cad, 'Acme')

        def invoice(number):
            record = Invoice(book, number, cad, customer)
            record.SetDateOpened(datetime(2026, 1, 5))
            line = Entry(book, record)
            line.SetDate(datetime(2026, 1, 5))
            line.SetDescription('Service')
            line.SetQuantity(GncNumeric(1, 1))
            line.SetInvAccount(find_account(root, 'Income:Sales'))
            line.SetInvPrice(GncNumeric(10000, 100))
            record.PostToAccount(find_account(root, 'Assets:Accounts Receivable'),
                                 datetime(2026, 1, 5), datetime(2026, 1, 5), '', True, False)
            return record

        def pay(record, cents):
            record.ApplyPayment(None, find_account(root, 'Assets:Bank'), GncNumeric(cents, 100),
                                GncNumeric(1, 1), datetime(2026, 1, 10), 'Deposit', '')

        build(invoice, pay)
        repo.save()
    finally:
        repo.close()


def test_an_overpaid_invoice_leaves_no_orphan(tmp_path):
    """INV-FP-SINGLE-100 for 100.00, paid 150.00: settled, with 50.00 of credit."""
    book = _book(tmp_path)
    runner = CliRunner()
    imported = runner.invoke(cli, ['import', book, 'tests/fixtures/q015_fp_single_cust_credit.txt',
                                   '--include-business-objects'])
    assert imported.exit_code == 0, imported.output

    orphans = runner.invoke(cli, ['find-orphan-payments', book])
    credits = runner.invoke(cli, ['find-prepayments', book])

    assert orphans.exit_code == 0, orphans.output
    assert 'No orphan bank-side payment transactions found.' in orphans.output, orphans.output
    assert ('customer C001 (Acme)  CAD 50.00  in Assets:Accounts Receivable'
            in credits.output), credits.output


def test_a_payment_left_by_gnucashs_own_unpost_is_listed(tmp_path):
    book = _book(tmp_path)

    def build(invoice, pay):
        record = invoice('INV-GUI')
        pay(record, 10000)
        record.Unpost(False)

    _through_gnucash(book, build)
    result = CliRunner().invoke(cli, ['find-orphan-payments', book])

    assert result.exit_code == 0, result.output
    assert 'Found 1 orphan bank-side payment transaction.' in result.output, result.output
    assert 'Assets:Bank  CAD 100.00  "Acme"' in result.output, result.output


def test_a_payment_settling_two_invoices_one_unposted_by_gnucash_is_listed(tmp_path):
    """INV-A paid 200.00, the 100.00 over applied to INV-B, and INV-B unposted."""
    book = _book(tmp_path)

    def build(invoice, pay):
        first, second = invoice('INV-A'), invoice('INV-B')
        pay(first, 20000)
        second.AutoApplyPayments()
        second.Unpost(False)

    _through_gnucash(book, build)
    result = CliRunner().invoke(cli, ['find-orphan-payments', book])

    assert result.exit_code == 0, result.output
    assert 'Found 1 orphan bank-side payment transaction.' in result.output, result.output
