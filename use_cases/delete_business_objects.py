"""
Use cases for deleting and archiving GnuCash customers, vendors, and
unposted invoices/bills.

delete-customers — hard-removes a customer via Destroy(); blocked if any
                   invoices are linked (paid or unpaid, posted or unposted).
                   NOTE: vendor deletion is NOT supported — GnuCash's
                   gncVendorDestroy does not properly remove the entity from
                   the XML backend's serialization path, so the vendor
                   reappears after save/reload regardless of the in-memory
                   state. Use archive-vendors instead.

archive — sets SetActive(False); always succeeds for a found, currently-active
          entity; reports the linked invoice/bill count as informational context.

delete-invoices / delete-bills (Q-013) — hard-remove an unposted
                   invoice/bill via Destroy(). Posted records are refused
                   so that the destruction of the posting transaction (and
                   the orphaning of payment splits) cannot happen as a
                   silent side effect of a delete command. The natural
                   two-step path for posted records is:
                       unpost-invoices <id>  &&  delete-invoices <id>

All use cases accept a list of IDs and return one result per ID so callers
can display per-ID status lines and compute an overall exit code.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import List

from gnucash import Book, Query

from infrastructure.gnucash.guid_lookup import (
    find_customer_by_guid,
    find_vendor_by_guid,
)
from infrastructure.gnucash.utils import wrap_invoice_or_bill
from services.gnucash_importer import (
    _find_bill_by_guid,
    _find_bills_by_id,
    _find_invoice_by_guid,
    _find_invoices_by_id,
    _swig_invoice_guid_str,
)


class DeleteStatus(Enum):
    DELETED = auto()
    FAILED_HAS_INVOICES = auto()
    NOT_FOUND = auto()


class ArchiveStatus(Enum):
    ARCHIVED = auto()
    ALREADY_ARCHIVED = auto()
    NOT_FOUND = auto()


@dataclass
class DeleteResult:
    id: str             # matched record's user-facing id (or original input on a miss)
    guid: str = ''      # matched record's GUID (empty on a miss — no record to read it from)
    status: DeleteStatus = None
    invoice_count: int = 0  # > 0 only for FAILED_HAS_INVOICES

    def message(self) -> str:
        if self.status == DeleteStatus.DELETED:
            return 'deleted'
        if self.status == DeleteStatus.FAILED_HAS_INVOICES:
            noun = 'invoice(s)' if self.invoice_count != 1 else 'invoice'
            return f'failed — cannot delete, {self.invoice_count} {noun} linked'
        return 'not found'

    def label(self) -> str:
        """Per-record line prefix: '<id> (<guid>)' when a record was matched,
        else just whatever the user typed (no guid is available on a miss)."""
        if self.guid:
            return f'{self.id} ({self.guid})'
        return self.id


@dataclass
class ArchiveResult:
    id: str             # matched record's user-facing id (or original input on a miss)
    guid: str = ''      # matched record's GUID (empty on a miss)
    status: ArchiveStatus = None
    invoice_count: int = 0  # informational; > 0 when linked invoices exist

    def message(self) -> str:
        if self.status == ArchiveStatus.ALREADY_ARCHIVED:
            return 'already archived'
        if self.status == ArchiveStatus.NOT_FOUND:
            return 'not found'
        # ARCHIVED
        if self.invoice_count > 0:
            noun = 'invoice(s)' if self.invoice_count != 1 else 'invoice'
            return f'archived — {self.invoice_count} {noun} linked'
        return 'archived'

    def label(self) -> str:
        """Per-record line prefix: '<id> (<guid>)' when a record was matched,
        else just whatever the user typed."""
        if self.guid:
            return f'{self.id} ({self.guid})'
        return self.id


def _count_invoices_for_owner(book: Book, owner_id: str, owner_type_int: int) -> int:
    """Count invoices/bills linked to a given owner ID and owner-type integer.

    owner_type_int: 2 = Customer (GNC_OWNER_CUSTOMER), 4 = Vendor (GNC_OWNER_VENDOR)
    """
    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    invoices = list(q.run())
    q.destroy()
    count = 0
    for r in invoices:
        inv = wrap_invoice_or_bill(r)
        if inv.GetOwnerType() != owner_type_int:
            continue
        try:
            if owner_type_int == 2:  # Customer
                owner = inv.GetOwner().GetCustomer()
            else:                    # Vendor
                owner = inv.GetOwner().GetVendor()
            if owner and owner.GetID() == owner_id:
                count += 1
        except Exception:
            pass
    return count


def _resolve_customer(book: Book, id_or_guid: str, by_guid: bool):
    """Look up a customer by id (default) or guid (when by_guid=True).

    Returns (customer, report_id, report_guid):
      - hit:  (Customer, customer.id, customer.guid)
      - miss: (None,     original_input, '')
    """
    cust = find_customer_by_guid(book, id_or_guid) if by_guid else book.CustomerLookupByID(id_or_guid)
    if cust is None or not cust.GetID():
        return None, id_or_guid, ''
    return cust, cust.GetID(), cust.GetGUID().to_string()


def _resolve_vendor(book: Book, id_or_guid: str, by_guid: bool):
    """See _resolve_customer."""
    v = find_vendor_by_guid(book, id_or_guid) if by_guid else book.VendorLookupByID(id_or_guid)
    if v is None or not v.GetID():
        return None, id_or_guid, ''
    return v, v.GetID(), v.GetGUID().to_string()


class DeleteCustomersUseCase:
    """Hard-delete customers by ID (or GUID with by_guid=True);
    blocked if any invoices are linked."""

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str], by_guid: bool = False) -> List[DeleteResult]:
        """`ids` are customer numbers (default) or GUIDs (when by_guid=True)."""
        results = []
        for arg in ids:
            cust, rid, rguid = _resolve_customer(self.book, arg, by_guid)
            if cust is None:
                results.append(DeleteResult(id=rid, status=DeleteStatus.NOT_FOUND))
                continue
            n = _count_invoices_for_owner(self.book, cust.GetID(), 2)
            if n > 0:
                results.append(DeleteResult(id=rid, guid=rguid,
                                            status=DeleteStatus.FAILED_HAS_INVOICES,
                                            invoice_count=n))
                continue
            cust.Destroy()
            results.append(DeleteResult(id=rid, guid=rguid, status=DeleteStatus.DELETED))
        return results


class ArchiveCustomersUseCase:
    """Set customers inactive (SetActive(False)); informational invoice count.

    Accepts customer ids by default; pass by_guid=True to look up by GUID.
    """

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str], by_guid: bool = False) -> List[ArchiveResult]:
        """`ids` are customer numbers (default) or GUIDs (when by_guid=True)."""
        results = []
        for arg in ids:
            cust, rid, rguid = _resolve_customer(self.book, arg, by_guid)
            if cust is None:
                results.append(ArchiveResult(id=rid, status=ArchiveStatus.NOT_FOUND))
                continue
            if not cust.GetActive():
                results.append(ArchiveResult(id=rid, guid=rguid,
                                             status=ArchiveStatus.ALREADY_ARCHIVED))
                continue
            n = _count_invoices_for_owner(self.book, cust.GetID(), 2)
            cust.SetActive(False)
            results.append(ArchiveResult(id=rid, guid=rguid, status=ArchiveStatus.ARCHIVED,
                                         invoice_count=n))
        return results


class DeleteInvoiceStatus(Enum):
    DELETED = auto()
    FAILED_POSTED = auto()
    NOT_FOUND = auto()
    AMBIGUOUS_ID = auto()  # legacy data: multiple records share one id


@dataclass
class DeleteInvoiceResult:
    """Per-record result for delete-invoices / delete-bills.

    Separate type from the customer DeleteResult above because the
    refusal reason is different (posted vs has-linked-invoices) and
    overloading one enum across both would obscure that.
    """
    id: str             # matched record's id, or original input on a miss
    guid: str = ''      # matched record's GUID; empty on miss / ambiguous
    status: DeleteInvoiceStatus = None
    kind: str = 'invoice'  # 'invoice' or 'bill' — drives message wording

    def message(self) -> str:
        if self.status == DeleteInvoiceStatus.DELETED:
            return 'deleted'
        if self.status == DeleteInvoiceStatus.FAILED_POSTED:
            return (f'failed — posted; run unpost-{self.kind}s '
                    f'first, then delete-{self.kind}s')
        if self.status == DeleteInvoiceStatus.AMBIGUOUS_ID:
            return ('failed — multiple records share this id; '
                    'rerun with --by-guid')
        return 'not found'

    def label(self) -> str:
        if self.guid:
            return f'{self.id} ({self.guid})'
        return self.id


def _resolve_invoice_or_bill(book: Book, id_or_guid: str, by_guid: bool,
                             by_id_fn, by_guid_fn):
    """Look up exactly one invoice or bill.

    Returns (record, report_id, report_guid):
      - hit:        (Invoice, record.id, record.guid)
      - miss:       (None,    original_input, '')
      - ambiguous:  (None,    original_input, '__ambiguous__')

    Mirrors `unpost_business_objects._resolve_one` so legacy duplicates
    surface as AMBIGUOUS_ID rather than silently picking one record.
    """
    if by_guid:
        rec = by_guid_fn(book, id_or_guid)
        if rec is None:
            return None, id_or_guid, ''
        return rec, rec.GetID(), id_or_guid
    matches = by_id_fn(book, id_or_guid)
    if not matches:
        return None, id_or_guid, ''
    if len(matches) > 1:
        return None, id_or_guid, '__ambiguous__'
    rec = matches[0]
    return rec, rec.GetID(), _swig_invoice_guid_str(rec)


def _remove_all_entries(rec) -> None:
    """Detach + destroy every entry on an unposted invoice or bill, so
    that `Invoice.Destroy()` doesn't leave dangling entry-to-parent
    references that revive the parent in the XML backend on save.

    `rec` is the correctly-typed SWIG object — a `Bill` for a vendor bill,
    an `Invoice` for a customer invoice (see the `_find_*` lookups) — so
    `RemoveEntry` dispatches to the right `gncBill*` / `gncInvoice*` function.
    """
    for entry in list(rec.GetEntries()):
        rec.RemoveEntry(entry)
        entry.Destroy()


def _execute_delete_invoice_or_bill(book: Book, ids: List[str],
                                    by_guid: bool, by_id_fn, by_guid_fn,
                                    kind: str) -> List[DeleteInvoiceResult]:
    """Shared body for DeleteInvoicesUseCase and DeleteBillsUseCase.

    Refuses posted records (FAILED_POSTED) so that the destruction of
    the posting transaction is never a silent side effect of `delete-*`.

    For unposted records:
      1. Detach and destroy every line-item entry. The XML backend
         serialises entries from the gncEntry QofCollection; an entry
         with a parent-ref to a destroyed invoice could either revive
         the parent on save or segfault, depending on platform.
         We tear down the entries first (same pattern the importer's
         rebuild path uses).
      2. Call SWIG `Invoice.Destroy()`. Internally this calls
         `gncInvoiceDestroy`, which sets the destroying flag and trips
         `gncInvoiceCommitEdit`'s free path. No explicit `BeginEdit()`
         needed — SWIG's RemoveEntry-then-Destroy on each entry left
         the edit-level state in a balanced position; adding an
         explicit BeginEdit/CommitEdit pair on the invoice produces a
         "unbalanced call" qof.engine error and does not change the
         outcome.
    """
    results: List[DeleteInvoiceResult] = []
    for arg in ids:
        rec, rid, rguid = _resolve_invoice_or_bill(
            book, arg, by_guid, by_id_fn, by_guid_fn)
        if rec is None and rguid == '__ambiguous__':
            results.append(DeleteInvoiceResult(
                id=rid, status=DeleteInvoiceStatus.AMBIGUOUS_ID, kind=kind))
            continue
        if rec is None:
            results.append(DeleteInvoiceResult(
                id=rid, status=DeleteInvoiceStatus.NOT_FOUND, kind=kind))
            continue
        if rec.GetPostedTxn() is not None:
            results.append(DeleteInvoiceResult(
                id=rid, guid=rguid,
                status=DeleteInvoiceStatus.FAILED_POSTED, kind=kind))
            continue
        _remove_all_entries(rec)
        rec.Destroy()
        results.append(DeleteInvoiceResult(
            id=rid, guid=rguid, status=DeleteInvoiceStatus.DELETED, kind=kind))
    return results


class DeleteInvoicesUseCase:
    """Hard-delete one or more unposted customer invoices.

    Refuses posted invoices. The two-step `unpost-invoices` →
    `delete-invoices` path is the only way to delete a previously-
    posted record, by design — see Q-013 issue doc.
    """

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str],
                by_guid: bool = False) -> List[DeleteInvoiceResult]:
        return _execute_delete_invoice_or_bill(
            self.book, ids, by_guid,
            _find_invoices_by_id, _find_invoice_by_guid, kind='invoice')


class DeleteBillsUseCase:
    """Hard-delete one or more unposted vendor bills.

    Symmetric to DeleteInvoicesUseCase — same Destroy() call; GnuCash
    uses the same gncInvoice C type for both customer invoices and
    vendor bills, distinguished only by the owner type.
    """

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str],
                by_guid: bool = False) -> List[DeleteInvoiceResult]:
        return _execute_delete_invoice_or_bill(
            self.book, ids, by_guid,
            _find_bills_by_id, _find_bill_by_guid, kind='bill')


class ArchiveVendorsUseCase:
    """Set vendors inactive (SetActive(False)); informational bill count.

    Accepts vendor ids by default; pass by_guid=True to look up by GUID.
    """

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str], by_guid: bool = False) -> List[ArchiveResult]:
        """`ids` are vendor numbers (default) or GUIDs (when by_guid=True)."""
        results = []
        for arg in ids:
            vendor, rid, rguid = _resolve_vendor(self.book, arg, by_guid)
            if vendor is None:
                results.append(ArchiveResult(id=rid, status=ArchiveStatus.NOT_FOUND))
                continue
            if not vendor.GetActive():
                results.append(ArchiveResult(id=rid, guid=rguid,
                                             status=ArchiveStatus.ALREADY_ARCHIVED))
                continue
            n = _count_invoices_for_owner(self.book, vendor.GetID(), 4)
            vendor.SetActive(False)
            results.append(ArchiveResult(id=rid, guid=rguid, status=ArchiveStatus.ARCHIVED,
                                         invoice_count=n))
        return results
