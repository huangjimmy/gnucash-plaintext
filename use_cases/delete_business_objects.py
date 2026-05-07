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

from infrastructure.gnucash.guid_lookup import (
    find_customer_by_guid,
    find_vendor_by_guid,
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
