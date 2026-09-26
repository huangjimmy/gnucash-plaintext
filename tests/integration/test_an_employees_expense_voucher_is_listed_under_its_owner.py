"""An employee's expense voucher is listed under its owner.

An expense voucher is an invoice owned by an employee and posted to A/Payable,
and GnuCash's Business menu makes one. The plaintext format has no employee, so
these books are built through GnuCash's bindings. An overpaid voucher leaves a
credit, which `find-prepayments` lists; a voucher paid and then unposted leaves
its payment behind, which `find-orphan-payments` lists. Neither command has a
word for an employee, so each calls it the owner, and its voucher an
invoice/bill.
"""

from datetime import datetime

from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


def _a_voucher(tmp_path, paid_cents, unpost):
    """A book holding one 100.00 CAD voucher for employee E001, paid `paid_cents`."""
    from gnucash import GncNumeric
    from gnucash.gnucash_business import Bill, Employee, Entry

    from infrastructure.gnucash.utils import find_account

    book_path = tmp_path / 'book.gnucash'
    imported = CliRunner().invoke(cli, ['import', '--new', str(book_path), ACCOUNTS])
    assert imported.exit_code == 0, imported.output

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.NORMAL)
    try:
        book = repo.book
        cad = book.get_table().lookup('CURRENCY', 'CAD')
        root = book.get_root_account()
        employee = Employee(book, 'E001', cad, 'Pat Employee')
        # A `Bill`, because a voucher's lines are priced on the bill side and
        # only `Bill.AddEntry` sets a line's bill pointer (CLAUDE.md finding 8).
        voucher = Bill(book, 'EXP-1', cad, employee)
        voucher.SetDateOpened(datetime(2026, 1, 5))
        line = Entry(book, voucher)
        line.SetDate(datetime(2026, 1, 5))
        line.SetDescription('Taxi')
        line.SetQuantity(GncNumeric(1, 1))
        line.SetBillAccount(find_account(root, 'Expenses:Supplies'))
        line.SetBillPrice(GncNumeric(10000, 100))
        voucher.PostToAccount(find_account(root, 'Liabilities:Accounts Payable'),
                              datetime(2026, 1, 5), datetime(2026, 1, 5), '', True, False)
        # Negated, as a bill's payment is (CLAUDE.md finding 7), and with no memo.
        voucher.ApplyPayment(None, find_account(root, 'Assets:Bank'),
                             GncNumeric(-paid_cents, 100), GncNumeric(1, 1),
                             datetime(2026, 1, 10), '', '')
        if unpost:
            voucher.Unpost(False)
        repo.save()
    finally:
        repo.close()
    return str(book_path)


def test_an_overpaid_vouchers_credit_is_listed_under_its_owner(tmp_path):
    book = _a_voucher(tmp_path, 15000, unpost=False)

    result = CliRunner().invoke(cli, ['find-prepayments', book])

    assert result.exit_code == 0, result.output
    assert 'Found 1 open pre-payment credit.' in result.output, result.output
    assert ('owner E001 (Pat Employee)  CAD 50.00  in Liabilities:Accounts Payable'
            in result.output), result.output
    assert 'why classified as a pre-payment (AR/AP credit)' in result.output, result.output
    assert 'parent tx owner backref points at owner E001' in result.output, result.output


def test_an_unposted_vouchers_payment_is_listed_under_its_owner(tmp_path):
    book = _a_voucher(tmp_path, 10000, unpost=True)

    result = CliRunner().invoke(cli, ['find-orphan-payments', book])

    assert result.exit_code == 0, result.output
    assert 'Found 1 orphan bank-side payment transaction.' in result.output, result.output
    assert ('gncOwnerGetOwnerFromTxn(tx) returned owner E001 (Pat Employee)'
            in result.output), result.output
    assert 'AR/AP-side split is on Liabilities:Accounts Payable' in result.output, result.output
    assert 'invoice/bill was unposted' in result.output, result.output
    assert 'memo:' not in result.output, result.output
    assert 'Total: CAD 100.00 in Assets:Bank.' in result.output, result.output


def test_validate_reads_the_payment_of_a_voucher_without_counting_a_duplicate(tmp_path):
    """The duplicate check reads each transaction's owner. An employee is
    neither a customer nor a vendor, so the payment's owner is read from the
    slot a ledger stores it in instead, which holds none here."""
    book = _a_voucher(tmp_path, 10000, unpost=False)

    result = CliRunner().invoke(cli, ['validate', book])

    assert 'Traceback' not in result.output, result.output
    assert 'duplicate' not in result.output.lower(), result.output


def test_an_overpaid_voucher_is_exported_with_no_owner_the_format_has_no_word_for(tmp_path):
    """The format writes a customer or a vendor as an owner, and an employee is
    neither. So the payment carries `txn_type: P` and no `owner:` line, and
    the employee's credit is written as no `open_prepayment:`."""
    book = _a_voucher(tmp_path, 15000, unpost=False)
    out = tmp_path / 'out.txt'

    result = CliRunner().invoke(cli, ['export', book, str(out)])

    assert result.exit_code == 0, result.output
    text = out.read_text()
    assert 'txn_type: P' in text, text
    assert 'owner:' not in text, text
    assert 'open_prepayment:' not in text, text
