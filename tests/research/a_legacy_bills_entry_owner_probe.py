"""What a bill entry added the wrong way looks like, and what can repair it.

CLAUDE.md §8: a `GncEntry` carries two owner pointers, and GnuCash's XML
writer emits the bill-side tax flags only inside `if (gncEntryGetBill(entry))`.
An entry added through `gncInvoiceAddEntry` — which is what this tool did to
vendor bills before `wrap_invoice_or_bill` — gets the *invoice* pointer, so
`b-taxable` / `b-taxincluded` are never written and default on reload.

A rebuild used to heal such a book by accident: every line was destroyed and
added again, through `Bill.AddEntry` this time. Lines are edited in place now,
and `AddEntry` is called only for a line being created, so nothing heals it.

Three questions, none answerable from the headers:

1. Does a bill entry added through `Invoice.AddEntry` really come back from a
   save with no bill pointer, and its `b-taxable` lost?
2. Is there an API to set the pointer on an entry that already exists —
   `gncEntrySetBill` in the library, or `SetBill` on the SWIG class?
3. Does `gncBillAddEntry` on such an entry set the pointer, and does it
   double the entry in the bill's list while doing it?

Run: ./scripts/test.sh <tag> tests/research/a_legacy_bills_entry_owner_probe.py -s
"""

import ctypes

from click.testing import CliRunner
from gnucash import Query
from gnucash.gnucash_business import Bill, Entry, Invoice, Vendor

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from repositories.gnucash_repository import GnuCashRepository, SessionMode

LEDGER = """2026-01-01 commodity CAD
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

vendor "V-P"
\tname: "Probe Supplies"
\tcurrency: CAD
"""


def _the_bill(book):
    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    raw = q.run()[0]
    q.destroy()
    return raw


def test_what_the_engine_answers(tmp_path):
    ledger = tmp_path / 'in.txt'
    ledger.write_text(LEDGER, encoding='utf-8')
    book_path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book_path),
                                    str(ledger), '--include-business-objects'])
    assert made.exit_code == 0, made.output

    report = []
    lib = load_gnc_engine()

    # What the bindings offer for setting the pointer after the fact.
    for name in ('gncEntrySetBill', 'gncBillAddEntry', 'gncEntryGetBill',
                 'gncInvoiceAddEntry'):
        report.append(f'library has {name}: {hasattr(lib, name)}')
    for name in ('SetBill', 'SetInvoice', 'GetBill'):
        report.append(f'SWIG Entry has {name}: {hasattr(Entry, name)}')

    # A bill whose line was added the legacy way: the vendor's bill
    # wrapped as an Invoice, so AddEntry dispatches to gncInvoiceAddEntry.
    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.NORMAL)
    try:
        book = repo.book
        q = Query()
        q.search_for('gncVendor')
        q.set_book(book)
        vendor = Vendor(instance=q.run()[0])
        q.destroy()

        currency = book.get_table().lookup('CURRENCY', 'CAD')
        legacy = Invoice(book, 'BILL-LEGACY', currency, vendor)
        account = book.get_root_account().lookup_by_name('Expenses') \
            .lookup_by_name('Supplies')
        entry = Entry(book, legacy)   # constructor's own add
        entry.SetDate(__import__('datetime').datetime(2026, 2, 1))
        entry.SetDescription('Legacy line')
        entry.SetBillAccount(account)
        entry.SetQuantity(__import__('gnucash').GncNumeric(1, 1))
        entry.SetBillPrice(__import__('gnucash').GncNumeric(100, 1))
        entry.SetBillTaxable(False)
        entry.SetBillTaxIncluded(True)
        legacy.AddEntry(entry)        # <- gncInvoiceAddEntry, the legacy path

        report.append(f'before save, bill pointer: '
                      f'{lib.gncEntryGetBill(int(entry.instance))}')
        repo.save()
    finally:
        repo.close()

    # Reloaded: what survived the writer.
    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.NORMAL)
    try:
        raw = _the_bill(repo.book)
        as_bill = Bill(instance=raw)
        entries = list(as_bill.GetEntries())
        report.append(f'entries after reload: {len(entries)}')
        reloaded = entries[0]
        ptr = int(reloaded.instance)
        lib.gncEntryGetInvoice.restype = ctypes.c_void_p
        lib.gncEntryGetInvoice.argtypes = [ctypes.c_void_p]
        report.append(f'bill pointer after reload: {lib.gncEntryGetBill(ptr)}')
        report.append(f'invoice pointer after reload: '
                      f'{lib.gncEntryGetInvoice(ptr)}')
        report.append(f'b-taxable after reload: {reloaded.GetBillTaxable()} '
                      f'(authored False)')
        report.append(f'b-taxincluded after reload: '
                      f'{reloaded.GetBillTaxIncluded()} (authored True)')

        # Can the pointer be repaired in place, and what does it cost?
        report.append(f'library has gncEntrySetInvoice: '
                      f'{hasattr(lib, "gncEntrySetInvoice")}')
        lib.gncEntrySetBill.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.gncEntrySetBill.restype = None
        lib.gncEntrySetInvoice.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.gncEntrySetInvoice.restype = None
        reloaded.BeginEdit()
        lib.gncEntrySetBill(ptr, int(raw))
        # The entry still carries the invoice pointer it was added with, and
        # the writer emits a reference for each — so leaving it set lists the
        # one entry twice when the book is read back.
        lib.gncEntrySetInvoice(ptr, None)
        # As an import does: the flags are written from the file every time,
        # and the question is whether the writer keeps them now.
        reloaded.SetBillTaxable(False)
        reloaded.SetBillTaxIncluded(True)
        reloaded.CommitEdit()
        report.append(f'after repair, bill pointer: {lib.gncEntryGetBill(ptr)}')
        report.append(f'after repair, invoice pointer: '
                      f'{lib.gncEntryGetInvoice(ptr)}')
        report.append(f'entries in this session: '
                      f'{len(list(Bill(instance=raw).GetEntries()))}')
        repo.save()
    finally:
        repo.close()

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.READ_ONLY)
    try:
        raw = _the_bill(repo.book)
        entries = list(Bill(instance=raw).GetEntries())
        report.append(f'entries after repair and reload: {len(entries)}')
        report.append(f'b-taxable after repair: {entries[0].GetBillTaxable()} '
                      f'(authored False)')
        report.append(f'b-taxincluded after repair: '
                      f'{entries[0].GetBillTaxIncluded()} (authored True)')
    finally:
        repo.close()

    print('\n'.join(report))

    # What was measured, on GnuCash 5.10, so the answers are the record
    # rather than the printout — stdout does not survive this runner.
    assert 'library has gncEntrySetBill: True' in report, report
    assert 'SWIG Entry has SetBill: False' in report, report
    assert 'bill pointer after reload: None' in report, report
    # The pointer it does carry, and the one the repair clears: measured,
    # not asserted from the header — the writer emits a reference per
    # pointer and the reader adds the entry once per reference.
    assert any(line.startswith('invoice pointer after reload: ')
               and not line.endswith('None') for line in report), report
    assert 'after repair, invoice pointer: None' in report, report
    assert 'b-taxable after reload: True (authored False)' in report, report
    assert 'b-taxincluded after reload: False (authored True)' in report, report
    assert 'entries after repair and reload: 1' in report, report
    assert 'b-taxable after repair: False (authored False)' in report, report
    assert 'b-taxincluded after repair: True (authored True)' in report, report
