"""
Use cases for deleting and archiving GnuCash customers and vendors.

delete-customers — hard-removes a customer via Destroy(); blocked if any
                   invoices are linked (paid or unpaid, posted or unposted).
                   NOTE: vendor deletion is NOT supported — GnuCash's
                   gncVendorDestroy does not properly remove the entity from
                   the XML backend's serialization path, so the vendor
                   reappears after save/reload regardless of the in-memory
                   state. Use archive-vendors instead.

archive — sets SetActive(False); always succeeds for a found, currently-active
          entity; reports the linked invoice/bill count as informational context.

Both use cases accept a list of IDs and return one result per ID so callers
can display per-ID status lines and compute an overall exit code.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import List

import gnucash.gnucash_business as gb
from gnucash import Book, Query


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
    id: str
    status: DeleteStatus
    invoice_count: int = 0  # > 0 only for FAILED_HAS_INVOICES

    def message(self) -> str:
        if self.status == DeleteStatus.DELETED:
            return 'deleted'
        if self.status == DeleteStatus.FAILED_HAS_INVOICES:
            noun = 'invoice(s)' if self.invoice_count != 1 else 'invoice'
            return f'failed — cannot delete, {self.invoice_count} {noun} linked'
        return 'not found'


@dataclass
class ArchiveResult:
    id: str
    status: ArchiveStatus
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
        inv = gb.Invoice(instance=r)
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


class DeleteCustomersUseCase:
    """Hard-delete customers by ID; blocked if any invoices are linked."""

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str]) -> List[DeleteResult]:
        results = []
        for cid in ids:
            cust = self.book.CustomerLookupByID(cid)
            if cust is None or not cust.GetID():
                results.append(DeleteResult(id=cid, status=DeleteStatus.NOT_FOUND))
                continue
            n = _count_invoices_for_owner(self.book, cid, 2)
            if n > 0:
                results.append(DeleteResult(id=cid, status=DeleteStatus.FAILED_HAS_INVOICES, invoice_count=n))
                continue
            cust.Destroy()
            results.append(DeleteResult(id=cid, status=DeleteStatus.DELETED))
        return results


class ArchiveCustomersUseCase:
    """Set customers inactive (SetActive(False)); informational invoice count."""

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str]) -> List[ArchiveResult]:
        results = []
        for cid in ids:
            cust = self.book.CustomerLookupByID(cid)
            if cust is None or not cust.GetID():
                results.append(ArchiveResult(id=cid, status=ArchiveStatus.NOT_FOUND))
                continue
            if not cust.GetActive():
                results.append(ArchiveResult(id=cid, status=ArchiveStatus.ALREADY_ARCHIVED))
                continue
            n = _count_invoices_for_owner(self.book, cid, 2)
            cust.SetActive(False)
            results.append(ArchiveResult(id=cid, status=ArchiveStatus.ARCHIVED, invoice_count=n))
        return results


class ArchiveVendorsUseCase:
    """Set vendors inactive (SetActive(False)); informational bill count."""

    def __init__(self, book: Book):
        self.book = book

    def execute(self, ids: List[str]) -> List[ArchiveResult]:
        results = []
        for vid in ids:
            vendor = self.book.VendorLookupByID(vid)
            if vendor is None or not vendor.GetID():
                results.append(ArchiveResult(id=vid, status=ArchiveStatus.NOT_FOUND))
                continue
            if not vendor.GetActive():
                results.append(ArchiveResult(id=vid, status=ArchiveStatus.ALREADY_ARCHIVED))
                continue
            n = _count_invoices_for_owner(self.book, vid, 4)
            vendor.SetActive(False)
            results.append(ArchiveResult(id=vid, status=ArchiveStatus.ARCHIVED, invoice_count=n))
        return results
