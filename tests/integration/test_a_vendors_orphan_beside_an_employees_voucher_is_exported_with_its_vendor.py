"""A vendor's orphaned payment, sharing a transaction with an employee's voucher, keeps its vendor.

One payment of 150.00 settles two records on the payable: employee E001's
expense voucher for 100.00 and vendor V001's BILL-001 for 50.00. GnuCash's
Process Payment makes one transaction per owner, so this is the register and
View → Lots: the transaction is entered by hand, and each payable split is
added to a lot with `gnc_lot_add_split`, as the lot viewer adds it. The test
builds it with those calls. Then `unpost-bills BILL-001` leaves the 50.00 as
an orphan.

The export writes the transaction's `txn_type:` and `owner:` so the orphan is
still found after a round trip. GnuCash reads the owner off the first payable
split in an owned lot, which is the voucher's, and an employee is not an owner
the format can write. The orphan's own lot still says V001, so that is the
owner the export writes.
"""

from datetime import datetime

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import find_account, qof_pointer
from repositories.gnucash_repository import GnuCashRepository
from services.gnucash_importer import _find_bills_by_id

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
BILL = 'tests/fixtures/q010_bill_posted.txt'


def _the_book(tmp_path):
    from gnucash import GncNumeric, Split, Transaction
    from gnucash.gnucash_business import Bill, Employee, Entry

    book_path = tmp_path / 'book.gnucash'
    for args in (['import', '--new', str(book_path), ACCOUNTS],
                 ['import', str(book_path), BILL, '--include-business-objects']):
        made = CliRunner().invoke(cli, args)
        assert made.exit_code == 0, made.output

    lib = load_gnc_engine()
    repo = GnuCashRepository(str(book_path))
    repo.open()
    try:
        book = repo.book
        cad = book.get_table().lookup('CURRENCY', 'CAD')
        root = book.get_root_account()
        payable = find_account(root, 'Liabilities:Accounts Payable')
        bank = find_account(root, 'Assets:Bank')

        employee = Employee(book, 'E001', cad, 'Pat Employee')
        # A `Bill`, because a voucher's lines are priced on the bill side
        # (CLAUDE.md finding 8).
        voucher = Bill(book, 'EXP-1', cad, employee)
        voucher.SetDateOpened(datetime(2026, 1, 5))
        line = Entry(book, voucher)
        line.SetDate(datetime(2026, 1, 5))
        line.SetDescription('Taxi')
        line.SetQuantity(GncNumeric(1, 1))
        line.SetBillAccount(find_account(root, 'Expenses:Supplies'))
        line.SetBillPrice(GncNumeric(10000, 100))
        voucher.PostToAccount(payable, datetime(2026, 1, 5), datetime(2026, 1, 5),
                              '', True, False)

        payment = Transaction(book)
        payment.BeginEdit()
        payment.SetCurrency(cad)
        payment.SetDescription('Paid Pat and Supplier')
        payment.SetDate(10, 1, 2026)
        splits = []
        for account, cents in ((payable, 10000), (payable, 5000), (bank, -15000)):
            split = Split(book)
            split.SetParent(payment)
            split.SetAccount(account)
            split.SetValue(GncNumeric(cents, 100))
            split.SetAmount(GncNumeric(cents, 100))
            splits.append(split)
        payment.CommitEdit()

        bill = _find_bills_by_id(book, 'BILL-001')[0]
        payable.BeginEdit()
        lib.gnc_lot_add_split(qof_pointer(voucher.GetPostedLot()), int(splits[0].instance))
        lib.gnc_lot_add_split(qof_pointer(bill.GetPostedLot()), int(splits[1].instance))
        payable.CommitEdit()
        repo.save()
    finally:
        repo.close()
    return book_path


def test_the_orphan_is_exported_with_its_vendor(tmp_path):
    book = _the_book(tmp_path)
    unposted = CliRunner().invoke(cli, ['unpost-bills', str(book), 'BILL-001'])
    assert unposted.exit_code == 0, unposted.output
    out = tmp_path / 'out.txt'

    exported = CliRunner().invoke(cli, ['export', str(book), str(out)])

    assert exported.exit_code == 0, exported.output
    text = out.read_text()
    assert '* "Paid Pat and Supplier"' in text, text
    start = text.index('* "Paid Pat and Supplier"')
    # The last transaction in the ledger has no blank line after it.
    end = text.find('\n\n', start)
    block = text[start:] if end < 0 else text[start:end]
    assert '\ttxn_type: P\n' in block, block
    assert '\towner: vendor:V001\n' in block, block
