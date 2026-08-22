"""A bill line that never carried its bill-side owner pointer is repaired.

CLAUDE.md §8: a `GncEntry` holds two owner pointers, and GnuCash's XML
writer emits `b-taxable` / `b-taxincluded` only inside
`if (gncEntryGetBill(entry))`. A line added through `gncInvoiceAddEntry` —
what a vendor bill got before `wrap_invoice_or_bill`, and what a book
written by such a release still holds — carries the invoice pointer, so
those flags are never written and come back defaulted: `taxable: false`
reloads as true, `tax_included: true` reloads as false.

Rebuilding a bill healed that by accident, since every line was
destroyed and added again through the bill's own `AddEntry`. Lines are
edited in place now and `AddEntry` is called only for a line being created,
so nothing heals it: the bill compares unequal against its own exported
ledger on every run — `updated` for ever while unposted, and refused with
"unpost-bills first" once posted, which does not fix the pointer either.
That is CLAUDE.md §11's failure — an unchanged ledger writing the book on
every import — for this class of book.

The repair is `gncEntrySetBill`, not `AddEntry`: `gncBillAddEntry` returns
early only when the pointer already names this bill, so on a null pointer
it would set it *and* put a second reference in the bill's entry list.
Measured in `tests/research/a_legacy_bills_entry_owner_probe.py`.
"""

import datetime

import pytest
from click.testing import CliRunner
from gnucash import GncNumeric, Query
from gnucash.gnucash_business import Entry, Invoice, Vendor

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.utils import qof_pointer, wrap_invoice_or_bill
from repositories.gnucash_repository import GnuCashRepository, SessionMode

ACCOUNTS = """2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Expenses
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Expenses:Supplies
\ttype: Expense
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Payable
\ttype: Accounts Payable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

vendor "V-LEGACY"
\tname: "Legacy Supplies"
\tcurrency: CAD
"""

LEDGER = ACCOUNTS + """
bill "BILL-LEGACY"
\tvendor_id: "V-LEGACY"
\tcurrency: CAD
\tdate_opened: 2026-02-01
\tentry:
\t\tdate: 2026-02-01
\t\tdescription: "Legacy line"
\t\taccount: "Expenses:Supplies"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: #False
\t\ttax_included: #True
\tposted: none
\tpayment: none
"""


@pytest.fixture
def a_book_written_the_old_way(tmp_path):
    """A bill whose line was added as a customer invoice's would be.

    Exactly what `Invoice.AddEntry` on a vendor's bill does, which is
    what this tool did before it wrapped vendor bills as `Bill`.
    """
    ledger = tmp_path / 'accounts.txt'
    ledger.write_text(ACCOUNTS, encoding='utf-8')
    book_path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book_path),
                                    str(ledger), '--include-business-objects'])
    assert made.exit_code == 0, made.output

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.NORMAL)
    try:
        book = repo.book
        query = Query()
        query.search_for('gncVendor')
        query.set_book(book)
        vendor = Vendor(instance=query.run()[0])
        query.destroy()

        currency = book.get_table().lookup('CURRENCY', 'CAD')
        account = book.get_root_account().lookup_by_name(
            'Expenses').lookup_by_name('Supplies')
        legacy = Invoice(book, 'BILL-LEGACY', currency, vendor)
        entry = Entry(book, legacy)
        entry.SetDate(datetime.datetime(2026, 2, 1))
        entry.SetDescription('Legacy line')
        entry.SetBillAccount(account)
        entry.SetQuantity(GncNumeric(1, 1))
        entry.SetBillPrice(GncNumeric(100, 1))
        entry.SetBillTaxable(False)
        entry.SetBillTaxIncluded(True)
        legacy.AddEntry(entry)
        repo.save()
    finally:
        repo.close()
    return book_path


def _the_bills_line(book_path):
    """`(bill pointer, taxable, tax_included)` for the bill's only line."""
    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        record = wrap_invoice_or_bill(query.run()[0])
        query.destroy()
        entries = list(record.GetEntries())
        lib = load_gnc_engine()
        entry = entries[0]
        return (lib.gncEntryGetBill(qof_pointer(entry)),
                entry.GetBillTaxable(),
                entry.GetBillTaxIncluded(),
                [(e.GetDescription(), lib.gncEntryGetBill(qof_pointer(e)))
                 for e in entries])
    finally:
        repo.close()


class TestABookWrittenBeforeVendorsWereWrappedAsBills:
    def test_its_line_starts_without_the_pointer(self,
                                                 a_book_written_the_old_way):
        """The state the fix exists for, stated rather than assumed."""
        pointer, taxable, included, lines = _the_bills_line(
            a_book_written_the_old_way)

        assert pointer in (0, None), pointer
        # Authored False / True, and the writer dropped both.
        assert taxable is True, taxable
        assert included is False, included
        assert len(lines) == 1, lines

    def test_importing_its_ledger_gives_the_line_its_pointer(
            self, a_book_written_the_old_way, tmp_path):
        ledger = tmp_path / 'bill.txt'
        ledger.write_text(LEDGER, encoding='utf-8')

        result = CliRunner().invoke(cli, [
            'import', str(a_book_written_the_old_way), str(ledger),
            '--include-business-objects'])
        assert result.exit_code == 0, result.output

        pointer, taxable, included, lines = _the_bills_line(
            a_book_written_the_old_way)
        # The repair sets a pointer; it does not add the line a second time.
        assert len(lines) == 1, lines
        assert pointer not in (0, None), pointer
        assert taxable is False, taxable
        assert included is True, included

    def test_and_the_same_ledger_then_reads_as_unchanged(
            self, a_book_written_the_old_way, tmp_path):
        """The cost of leaving it unrepaired: the flags never persist, so
        the bill differs from its own ledger on every run and the book
        is written again each time."""
        ledger = tmp_path / 'bill.txt'
        ledger.write_text(LEDGER, encoding='utf-8')
        runner = CliRunner()
        first = runner.invoke(cli, [
            'import', str(a_book_written_the_old_way), str(ledger),
            '--include-business-objects'])
        assert first.exit_code == 0, first.output

        again = runner.invoke(cli, [
            'import', str(a_book_written_the_old_way), str(ledger),
            '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'BILL-LEGACY": unchanged' in again.output, again.output
