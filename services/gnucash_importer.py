"""
Service for importing plaintext directives to GnuCash.

Converts PlaintextDirective objects from the parser into GnuCash objects
(commodities, accounts, transactions) with all metadata preserved.
"""

import ctypes
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import gnucash.gnucash_core_c as gc
from gnucash import Account, Book, GncCommodity, GncNumeric, Split, Transaction
from gnucash.gnucash_business import Customer, Entry, Invoice, TaxTable, TaxTableEntry, Vendor
from gnucash.gnucash_core_c import (
    ACCT_TYPE_ASSET,
    ACCT_TYPE_BANK,
    ACCT_TYPE_CASH,
    ACCT_TYPE_CREDIT,
    ACCT_TYPE_EQUITY,
    ACCT_TYPE_EXPENSE,
    ACCT_TYPE_INCOME,
    ACCT_TYPE_LIABILITY,
    ACCT_TYPE_MUTUAL,
    ACCT_TYPE_PAYABLE,
    ACCT_TYPE_RECEIVABLE,
    ACCT_TYPE_STOCK,
    gncTaxTableEntrySetAccount,
)

from infrastructure.gnucash.kvp import (
    KNOWN_ACCOUNT_METADATA_KEYS,
    KNOWN_BILL_METADATA_KEYS,
    KNOWN_CUSTOMER_METADATA_KEYS,
    KNOWN_INVOICE_METADATA_KEYS,
    KNOWN_SPLIT_METADATA_KEYS,
    KNOWN_TX_METADATA_KEYS,
    KNOWN_VENDOR_METADATA_KEYS,
    get_book_custom_metadata,
    get_book_string_option,
    get_custom_metadata,
    merge_book_custom_metadata,
    set_book_string_option,
    set_custom_metadata,
)
from infrastructure.gnucash.utils import find_account, get_account_full_name, string_to_gnc_numeric
from services.plaintext_parser import DirectiveType, PlaintextDirective

# Q-028: book-level `company` directive — plaintext key ↔ Business option slot.
# These land at `options → Business → <slot>`, the exact slots GnuCash's own
# File → Properties → Business dialog reads and writes (Company Name, Company
# Contact Person, Company Phone/Fax Number, Company Email Address, Company
# Website URL, Company ID) and that `read_book_company_info` reads for the
# seller block. The directive routes each plaintext key to GnuCash's native
# slot so the whole block round-trips — it does not invent storage for fields
# GnuCash already owns. The ONLY custom additions are `Company GST Number` /
# `Company PST Number`: GnuCash has no GST/PST field, so this tool stores them
# as extra string slots in the same Business frame, alongside `Company ID`.
# Address lines map to the single multi-line `Company Address` slot (joined on
# import, split on export).
COMPANY_FIELD_TO_SLOT = {
    'name':    'Company Name',
    'contact': 'Company Contact Person',
    'id':      'Company ID',
    'gst':     'Company GST Number',
    'pst':     'Company PST Number',
    'phone':   'Company Phone Number',
    'fax':     'Company Fax Number',
    'email':   'Company Email Address',
    'url':     'Company Website URL',
}
_COMPANY_ADDR_KEYS = ('addr1', 'addr2', 'addr3', 'addr4')

# Q-029: any `company` key that is not a known Business field (above) or an
# address line is book-level custom metadata — e.g. `fiscal_year_end`,
# `province`, `entity_type`, `ledger_locale`. GnuCash has no slot for these
# (accounting period is an app preference, not stored in the file), so they are
# kept as our own book metadata under COMPANY_CUSTOM_SECTION/COMPANY_CUSTOM_SLOT
# (one JSON blob; see kvp.py). These keys round-trip but are never rendered on
# an invoice/bill — they are private book data (a customer has no business
# seeing the seller's fiscal year).


def string_to_gnc_numeric_quantity(s):
    from decimal import Decimal

    from gnucash import GncNumeric
    s = str(s)
    if '/' in s:
        return GncNumeric(s)
    else:
        # Assuming a precision of 1,000,000 for quantities and prices
        num = int(Decimal(s) * 1000000)
        den = 1000000
        return GncNumeric(num, den)


_FALSY_STRINGS = {'false', '0', 'no'}


@dataclass
class BusinessObjectImportResult:
    """Per-type create/update/unchanged/skip counts from `import_business_objects`.

    Status semantics (Q-010):
      - created:   directive produced a brand-new object
      - updated:   directive matched an existing object AND mutated it
      - unchanged: directive matched an existing object whose persisted state
                   already equals the directive, so no mutation was applied
      - skipped:   directive matched an immutable existing object (posted
                   invoice/bill, in-use tax table); the directive is honoured
                   only as an idempotent no-op refusal

    Customers and vendors are mutable on hit, so they use all four. Tax
    tables, posted invoices, and posted bills are immutable on hit so they
    skip rather than update; unposted invoices/bills follow the mutable
    model.
    """
    counts: Dict[str, Dict[str, int]] = field(default_factory=lambda: {
        'company':  {'created': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0},
        'customer': {'created': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0},
        'vendor':   {'created': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0},
        'taxtable': {'created': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0},
        'invoice':  {'created': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0},
        'bill':     {'created': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0},
    })

    def tally(self, kind: str, status: str) -> None:
        if status not in ('created', 'updated', 'unchanged', 'skipped'):
            raise ValueError(f"Unknown import status {status!r} for {kind}")
        self.counts[kind][status] += 1

    def total(self, kind: str) -> int:
        return sum(self.counts[kind].values())


def _find_transaction_by_guid(book, guid: str):
    """Return the Transaction matching guid, or None.

    Accepts 32-char hex or UUID-with-hyphens; normalises via string_to_guid
    so both forms resolve to the same canonical GUID before lookup.
    Raises ValueError for inputs that are not valid GUID/UUID strings.
    Returns None when the format is valid but no transaction has that GUID.
    """
    from gnucash import Transaction
    from gnucash.gnucash_core_c import GncGUID, string_to_guid, xaccTransLookup
    gnc_guid = GncGUID()
    if not string_to_guid(guid, gnc_guid):
        raise ValueError(f"Invalid GUID format: {guid!r}")
    raw = xaccTransLookup(gnc_guid, book.instance)
    if raw is None:
        return None
    return Transaction(instance=raw)


def _normalise_guid(guid) -> str:
    """Normalise a user-supplied GUID to GnuCash's canonical 32-char lowercase hex.

    Accepts:
      - quoted hex string ("b2b3…b4")
      - unquoted mixed hex (b2b3…b4) — the parser keeps it as a string
      - UUID-with-hyphens
    Rejects:
      - int / float — these slip in when a user writes an unquoted all-digit
        guid (e.g. `guid: 22222222222222222222222222222222`). The parser
        auto-converts to int and the original digit count is lost (so
        `0000…0022` would be indistinguishable from `22`). Force the user
        to quote so we keep the literal hex digits.
      - malformed strings ("hello") via `string_to_guid`
    """
    if isinstance(guid, (int, float, bool)):
        raise ValueError(
            f"guid must be a quoted string (got {type(guid).__name__} {guid!r}); "
            f"unquoted all-digit values are auto-converted to a number and "
            f"lose their digit count. Quote the guid: e.g. guid: \"{guid:032x}\""
            if isinstance(guid, int) and 0 <= guid < 2**128
            else f"guid must be a quoted string (got {type(guid).__name__} {guid!r})"
        )

    from gnucash.gnucash_core_c import GncGUID, string_to_guid
    if not string_to_guid(guid, GncGUID()):
        raise ValueError(f"Invalid GUID format: {guid!r}")
    return guid.replace('-', '').lower()


def _find_customers_by_id(book, id_: str):
    """Return all Customer records with the given user-facing id."""
    from gnucash import Query
    from gnucash.gnucash_business import Customer
    q = Query()
    q.search_for('gncCustomer')
    q.set_book(book)
    out = [Customer(instance=r) for r in q.run() if Customer(instance=r).GetID() == id_]
    q.destroy()
    return out


def _find_vendors_by_id(book, id_: str):
    from gnucash import Query
    from gnucash.gnucash_business import Vendor
    q = Query()
    q.search_for('gncVendor')
    q.set_book(book)
    out = [Vendor(instance=r) for r in q.run() if Vendor(instance=r).GetID() == id_]
    q.destroy()
    return out


def _find_customer_by_guid(book, guid_norm: str):
    from gnucash import Query
    from gnucash.gnucash_business import Customer
    q = Query()
    q.search_for('gncCustomer')
    q.set_book(book)
    found = None
    for r in q.run():
        c = Customer(instance=r)
        if c.GetGUID().to_string() == guid_norm:
            found = c
            break
    q.destroy()
    return found


def _find_vendor_by_guid(book, guid_norm: str):
    from gnucash import Query
    from gnucash.gnucash_business import Vendor
    q = Query()
    q.search_for('gncVendor')
    q.set_book(book)
    found = None
    for r in q.run():
        v = Vendor(instance=r)
        if v.GetGUID().to_string() == guid_norm:
            found = v
            break
    q.destroy()
    return found


# GnuCash's owner-type constants for gncInvoice. Customer invoices and
# vendor bills both live in the gncInvoice collection, distinguished by
# the owner type — 2 = Customer, 4 = Vendor.
_GNC_OWNER_CUSTOMER = 2
_GNC_OWNER_VENDOR = 4


def _find_invoices_by_id(book, id_: str):
    """All customer invoices with the given id.

    `book.InvoiceLookupByID` is unsuitable: it returns at most one record
    and (per Q-007 testing) does not return vendor bills at all. We use
    Query so we can detect legacy duplicates and so the bill side has the
    same lookup shape.
    """
    from gnucash import Query
    from gnucash.gnucash_business import Invoice
    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    out = []
    for r in q.run():
        inv = Invoice(instance=r)
        if inv.GetOwnerType() == _GNC_OWNER_CUSTOMER and inv.GetID() == id_:
            out.append(inv)
    q.destroy()
    return out


def _find_bills_by_id(book, id_: str):
    """All vendor bills with the given id."""
    from gnucash import Query
    from gnucash.gnucash_business import Invoice
    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    out = []
    for r in q.run():
        inv = Invoice(instance=r)
        if inv.GetOwnerType() == _GNC_OWNER_VENDOR and inv.GetID() == id_:
            out.append(inv)
    q.destroy()
    return out


def _find_invoice_by_guid(book, guid_norm: str):
    """Customer invoice with the given GUID, or None.

    SWIG `Invoice.GetGUID()` is missing on some platforms; use ctypes via
    qof_instance_get_guid + guid_to_string_buff (same pattern as the
    exporter's _guid_for_ptr_factory).
    """
    import ctypes

    from gnucash import Query
    from gnucash.gnucash_business import Invoice
    lib = ctypes.CDLL(None)
    lib.qof_instance_get_guid.argtypes = [ctypes.c_void_p]
    lib.qof_instance_get_guid.restype = ctypes.c_void_p
    lib.guid_to_string_buff.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.guid_to_string_buff.restype = ctypes.c_char_p
    buf = ctypes.create_string_buffer(40)

    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    found = None
    for r in q.run():
        inv = Invoice(instance=r)
        if inv.GetOwnerType() != _GNC_OWNER_CUSTOMER:
            continue
        guid_ptr = lib.qof_instance_get_guid(int(inv.instance))
        if not guid_ptr:
            continue
        lib.guid_to_string_buff(guid_ptr, buf)
        if buf.value.decode('ascii') == guid_norm:
            found = inv
            break
    q.destroy()
    return found


def _find_bill_by_guid(book, guid_norm: str):
    """Vendor bill with the given GUID, or None."""
    import ctypes

    from gnucash import Query
    from gnucash.gnucash_business import Invoice
    lib = ctypes.CDLL(None)
    lib.qof_instance_get_guid.argtypes = [ctypes.c_void_p]
    lib.qof_instance_get_guid.restype = ctypes.c_void_p
    lib.guid_to_string_buff.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.guid_to_string_buff.restype = ctypes.c_char_p
    buf = ctypes.create_string_buffer(40)

    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    found = None
    for r in q.run():
        inv = Invoice(instance=r)
        if inv.GetOwnerType() != _GNC_OWNER_VENDOR:
            continue
        guid_ptr = lib.qof_instance_get_guid(int(inv.instance))
        if not guid_ptr:
            continue
        lib.guid_to_string_buff(guid_ptr, buf)
        if buf.value.decode('ascii') == guid_norm:
            found = inv
            break
    q.destroy()
    return found


def _iter_taxtables(book):
    """Yield raw ctypes pointers to all tax tables in `book`.

    Tax tables are stored in a per-book hash via `qof_book_get_data` and are
    *not* enumerable through QofQuery — `gncTaxTableGetTables` (ctypes) is
    the only way to list them. Once a pointer enters this codepath it stays
    in ctypes (per the "once ctypes, stay ctypes" rule in CLAUDE.md).
    """
    from infrastructure.gnucash.engine import iterate_glist, load_gnc_engine
    lib = load_gnc_engine()
    glist_ptr = lib.gncTaxTableGetTables(int(book.instance))
    return iterate_glist(lib, glist_ptr, lambda lib, ptr: ptr)


def _taxtable_guid_str(tt_ptr) -> str:
    """Read a tax-table's GUID via ctypes given its raw pointer."""
    import ctypes

    from infrastructure.gnucash.engine import load_gnc_engine
    lib = load_gnc_engine()
    lib.qof_instance_get_guid.argtypes = [ctypes.c_void_p]
    lib.qof_instance_get_guid.restype = ctypes.c_void_p
    lib.guid_to_string_buff.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.guid_to_string_buff.restype = ctypes.c_char_p
    buf = ctypes.create_string_buffer(40)
    guid_ptr = lib.qof_instance_get_guid(tt_ptr)
    if not guid_ptr:
        return ''
    lib.guid_to_string_buff(guid_ptr, buf)
    return buf.value.decode('ascii')


def _taxtable_name_str(tt_ptr) -> str:
    """Read a tax-table's name via ctypes given its raw pointer."""
    from infrastructure.gnucash.engine import load_gnc_engine, safe_ctypes_string
    lib = load_gnc_engine()
    return safe_ctypes_string(lib.gncTaxTableGetName, tt_ptr)


def _find_taxtables_by_name(book, name: str):
    """Return list of tax-table ctypes pointers whose name == `name`.

    Returns a list (rather than a single pointer) so the resolver can detect
    pre-existing duplicates that would otherwise silently misroute tax onto
    whichever rate the lookup happened to pick first.
    """
    return [ptr for ptr in _iter_taxtables(book)
            if _taxtable_name_str(ptr) == name]


def _find_taxtable_by_guid(book, guid_norm: str):
    """Return the tax-table ctypes pointer whose GUID matches `guid_norm`,
    or None."""
    for ptr in _iter_taxtables(book):
        if _taxtable_guid_str(ptr) == guid_norm:
            return ptr
    return None


def _bill_remove_all_entries(book, bill) -> None:
    """Detach and destroy every entry on a vendor bill.

    SWIG `Invoice.RemoveEntry(entry)` wraps `gncInvoiceRemoveEntry` which is
    customer-invoice-specific and is a no-op (or worse) on vendor bills.
    Use the C `gncBillRemoveEntry` directly via ctypes so the bill's entry
    list is properly cleared before we rebuild from the directive. Without
    this, `gncInvoicePostToAccount` later iterates a list with dangling
    pointers from destroyed entries and segfaults on GnuCash 3.8.
    """
    import ctypes
    lib = ctypes.CDLL(None)
    lib.gncBillRemoveEntry.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gncBillRemoveEntry.restype = None
    bill_ptr = int(bill.instance)
    for old_entry in list(bill.GetEntries()):
        lib.gncBillRemoveEntry(bill_ptr, int(old_entry.instance))
        old_entry.Destroy()


def _swig_invoice_guid_str(invoice) -> str:
    """Read an Invoice's GUID via ctypes (qof_instance_get_guid + guid_to_string_buff).
    SWIG `Invoice.GetGUID()` is missing on some platforms; this works everywhere
    the invoice has been committed to the book."""
    import ctypes
    lib = ctypes.CDLL(None)
    lib.qof_instance_get_guid.argtypes = [ctypes.c_void_p]
    lib.qof_instance_get_guid.restype = ctypes.c_void_p
    lib.guid_to_string_buff.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.guid_to_string_buff.restype = ctypes.c_char_p
    buf = ctypes.create_string_buffer(40)
    guid_ptr = lib.qof_instance_get_guid(int(invoice.instance))
    if not guid_ptr:
        return ''
    lib.guid_to_string_buff(guid_ptr, buf)
    return buf.value.decode('ascii')


def _resolve_existing_or_none(kind: str, id_: str, guid_str: Optional[str],
                              find_by_id, find_by_guid,
                              get_guid_str=lambda r: r.GetGUID().to_string(),
                              get_id_str=lambda r: r.GetID()):
    """Apply Q-006 §2 resolution rules. Returns (existing, must_set_guid_str).

    `kind` is 'customer'/'vendor'/'invoice'/'bill'/'taxtable' for error messages.
    `existing` is the matched record or None (caller creates new).
    `must_set_guid_str` is the normalised guid to assign to a freshly-created
    record (for round-trip into a fresh book), or None.
    `get_guid_str(record) -> str` reads the guid from a matched record for
    error reporting. Defaults to SWIG `record.GetGUID().to_string()`, which
    works for Customer/Vendor; pass a ctypes-based callback for Invoice/Bill
    or for tax-table pointers where SWIG access is unavailable.
    `get_id_str(record) -> str` reads the user-facing id (or name, for tax
    tables) from a matched record. Defaults to SWIG `record.GetID()`.

    Raises ValueError on any contradiction the user must resolve manually.
    """
    matches_by_id = find_by_id(id_)
    if len(matches_by_id) > 1:
        raise ValueError(
            f'{kind} "{id_}": book already has {len(matches_by_id)} records '
            f'with this id; resolve in GnuCash GUI before re-importing'
        )

    if guid_str is None:
        # No guid in the directive — match by id alone, update or create.
        return (matches_by_id[0] if matches_by_id else None), None

    guid_norm = _normalise_guid(guid_str)
    by_guid = find_by_guid(guid_norm)

    if by_guid is None and matches_by_id:
        # GUID is unknown but id is taken — refuse to rebuild because we
        # cannot assign that guid without overwriting the existing record.
        existing = matches_by_id[0]
        raise ValueError(
            f'{kind} "{id_}": directive guid {guid_str!r} does not exist in '
            f'the book, but a {kind} with this id already exists '
            f'(guid {get_guid_str(existing)}). Refusing to rebuild — '
            f'either remove the guid: line to update the existing record, or '
            f'change the id to create a new {kind}.'
        )

    if by_guid is not None:
        existing_id = get_id_str(by_guid)
        if existing_id != id_:
            raise ValueError(
                f'{kind} "{id_}": directive guid {guid_str!r} resolves to a '
                f'{kind} with id {existing_id!r} — refusing to rename. '
                f'{kind} ids are immutable; fix the directive to match.'
            )
        return by_guid, None

    # No id match, no guid match → fresh create with the requested guid.
    return None, guid_norm


def _resolve_cross_reference(kind: str, id_val: Optional[str], guid_val: Optional[str],
                             find_by_id, find_by_guid):
    """Resolve an invoice→customer or bill→vendor reference.

    Q-006 §4 rules: id and guid (when both present) must resolve to the same
    record. Single-field lookups are allowed for hand-written files.

    Returns the resolved record. Raises ValueError on contradiction.
    """
    if id_val is None and guid_val is None:
        raise ValueError(f"missing {kind} reference (need _id or _guid)")

    by_guid = None
    if guid_val is not None:
        by_guid = find_by_guid(_normalise_guid(guid_val))
        if by_guid is None:
            raise ValueError(
                f"{kind}_guid {guid_val!r} does not resolve to any record"
            )
        if id_val is not None and by_guid.GetID() != id_val:
            raise ValueError(
                f"{kind}_guid {guid_val!r} resolves to {kind} with id "
                f"{by_guid.GetID()!r}, but {kind}_id says {id_val!r}"
            )
        return by_guid

    matches = find_by_id(id_val)
    if not matches:
        raise ValueError(f"{kind}_id {id_val!r} not found")
    if len(matches) > 1:
        raise ValueError(
            f"{kind}_id {id_val!r} matches {len(matches)} records — "
            f"specify {kind}_guid to disambiguate, or fix duplicates in GnuCash GUI"
        )
    return matches[0]


def _guid_in_use_anywhere(book, guid_norm: str) -> Optional[str]:
    """Return the kind of entity that already uses guid_norm, or None if free.

    GnuCash GUIDs are unique book-wide across every entity type. Before
    forcing a freshly-created object's GUID via qof_instance_set_guid, callers
    must ensure the target GUID is not already taken by another entity, or
    the book becomes corrupted.
    """
    import ctypes

    from gnucash.gnucash_core_c import GncGUID, string_to_guid, xaccTransLookup
    g = GncGUID()
    if not string_to_guid(guid_norm, g):
        return None
    if xaccTransLookup(g, book.instance) is not None:
        return 'transaction'

    lib = ctypes.CDLL(None)
    lib.xaccAccountLookup.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.xaccAccountLookup.restype = ctypes.c_void_p
    lib.string_to_guid.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
    lib.string_to_guid.restype = ctypes.c_int

    class QofGuid(ctypes.Structure):
        _fields_ = [("data", ctypes.c_uint8 * 16)]
    cguid = QofGuid()
    for i in range(16):
        cguid.data[i] = int(guid_norm[i*2:i*2+2], 16)
    if lib.xaccAccountLookup(ctypes.byref(cguid), int(book.instance)):
        return 'account'

    if _find_customer_by_guid(book, guid_norm) is not None:
        return 'customer'
    if _find_vendor_by_guid(book, guid_norm) is not None:
        return 'vendor'
    if _find_taxtable_by_guid(book, guid_norm) is not None:
        return 'taxtable'
    return None


def _set_object_guid(book, obj, kind: str, id_: str, guid_norm: str) -> None:
    """Force a freshly-created business object's GUID to a specific value.

    Errors if the requested GUID is already used by any other entity in the
    book — GnuCash GUIDs are unique across all object types, and a collision
    would corrupt the book.
    """
    in_use = _guid_in_use_anywhere(book, guid_norm)
    if in_use is not None:
        raise ValueError(
            f'{kind} "{id_}": guid {guid_norm} is already used by an existing '
            f'{in_use} in this book; pick a different guid or remove the guid: '
            f'line to let GnuCash assign one'
        )

    import ctypes
    class QofGuid(ctypes.Structure):
        _fields_ = [("data", ctypes.c_uint8 * 16)]
    lib = ctypes.CDLL(None)
    lib.qof_instance_set_guid.argtypes = [ctypes.c_void_p, ctypes.POINTER(QofGuid)]
    lib.qof_instance_set_guid.restype = None
    g = QofGuid()
    for i in range(16):
        g.data[i] = int(guid_norm[i*2:i*2+2], 16)
    lib.qof_instance_set_guid(int(obj.instance), ctypes.byref(g))


def _retarget_counter_split_to_lot(lib, existing_tx, bank_acct_name: str,
                                   ar_ap_account, lot) -> bool:
    """
    Modify existing_tx in-place: find the split whose account is NOT the
    bank account (the "counter-split"), retarget it to ar_ap_account, and
    link it to the invoice/bill lot.

    This closes the lot without calling ApplyPayment(), preserving all
    original transaction metadata (notes, description, split memos, KVP).

    xaccSplitSetAccount has a SWIG const-type mismatch — ctypes is required.
    See docs/DEBUGGING_GNUCASH_BINDINGS.md.
    """
    from infrastructure.gnucash.engine import safe_ctypes_string
    lib.xaccSplitGetAccount.argtypes = [ctypes.c_void_p]
    lib.xaccSplitGetAccount.restype  = ctypes.c_void_p
    lib.xaccSplitSetAccount.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.xaccSplitSetAccount.restype  = None
    lib.gnc_account_get_parent.argtypes = [ctypes.c_void_p]
    lib.gnc_account_get_parent.restype  = ctypes.c_void_p

    def _acct_name(acct_ptr):
        parts = []
        ptr = acct_ptr
        while ptr:
            name = safe_ctypes_string(lib.xaccAccountGetName, ptr)
            if name:
                parts.append(name)
            parent = lib.gnc_account_get_parent(ptr)
            if not parent:
                break
            if not lib.gnc_account_get_parent(parent):
                break
            ptr = parent
        parts.reverse()
        return ':'.join(parts)

    import gnucash.gnucash_core_c as _gc
    existing_tx.BeginEdit()
    for raw_sp in existing_tx.GetSplitList():
        sp_ptr = int(raw_sp.instance)
        acct_ptr = lib.xaccSplitGetAccount(sp_ptr)
        if not acct_ptr:
            continue
        if _acct_name(acct_ptr) != bank_acct_name:
            # This is the counter-split — retarget to AR/AP and close the lot
            lib.xaccSplitSetAccount(sp_ptr, int(ar_ap_account.instance))
            _gc.xaccSplitSetLot(raw_sp.instance, lot.instance)
            existing_tx.CommitEdit()
            return True
    existing_tx.CommitEdit()
    return False


def _parse_lot_owner(value: str):
    """Parse a `lot_owner:` value into (kind, owner_id, owner_guid).

    Forms (the trailing guid is authoritative and optional in hand-written
    files; always emitted on export):
      - `customer:C001`                       -> ('customer', 'C001', None)
      - `customer:C001:9f14a498…(32 hex)`     -> ('customer', 'C001', '9f14…')

    The guid is recognised only when the final colon-segment is a valid GUID,
    so an owner id containing colons is preserved as the middle segment(s).
    """
    if ':' not in value:
        return None, None, None
    kind, _, rest = value.partition(':')
    kind = kind.strip()
    guid = None
    if ':' in rest:
        head, _, tail = rest.rpartition(':')
        try:
            guid = _normalise_guid(tail.strip())
            rest = head
        except Exception:
            guid = None
    return kind, rest.strip(), guid


def _attach_lot_owner_split(book, split, split_account, kind, owner_id, owner_guid):
    """Attach an AR/AP split to its owner's business lot — the import side of
    the per-split `lot_owner:` marker.

    Join-or-create: if the owner has an open non-invoice lot on this account
    that this split *reduces* (opposite sign), join it — that settles a credit
    (refund / vendor bad debt / customer forfeit, decided by the counter split's
    account). Otherwise create a new lot and attach the owner — an orphan
    payment being reconstructed (Q-014) or a fresh credit origin.

    Done with primitive engine calls, NOT `gncOwnerApplyPaymentSecs(auto_pay=)`,
    whose lot-balancer segfaults on GnuCash 4.4/4.8.

    `lot_owner:` is authoritative, not informational: if `owner_guid` is given it
    MUST resolve to the same owner as `owner_id`, otherwise we raise — a guid
    mismatch is a hard error, never a warning.
    """
    import gnucash.gnucash_core_c as _gc

    from infrastructure.gnucash.engine import (
        GncNumericC,
        iterate_glist,
        load_gnc_engine,
    )

    # ACCT_TYPE_RECEIVABLE = 11 (customer), ACCT_TYPE_PAYABLE = 12 (vendor).
    if kind == 'customer':
        ref = book.CustomerLookupByID(owner_id) if owner_id else None
        want_type, side = 11, 'Accounts Receivable (customer)'
    else:
        ref = book.VendorLookupByID(owner_id) if owner_id else None
        want_type, side = 12, 'Accounts Payable (vendor)'

    if ref is None or not ref.GetID():
        raise Exception(
            f"lot_owner names {kind} {owner_id!r}, which does not exist in the book")
    if owner_guid and ref.GetGUID().to_string() != owner_guid:
        raise Exception(
            f"lot_owner {kind} id {owner_id!r} and guid {owner_guid!r} resolve to "
            f"different {kind}s — refusing (the guid is authoritative)")
    if split_account.GetType() != want_type:
        raise Exception(
            f"a `{kind}` lot_owner split must be on an {side} account; "
            f"{split_account.GetName()!r} is not")

    resolved_id = ref.GetID()

    lib = load_gnc_engine()
    for name, restype, argtypes in [
        ('xaccAccountGetLotList',       ctypes.c_void_p, [ctypes.c_void_p]),
        ('gnc_lot_get_balance',         GncNumericC,     [ctypes.c_void_p]),
        ('gnc_lot_is_closed',           ctypes.c_int,    [ctypes.c_void_p]),
        ('gncInvoiceGetInvoiceFromLot', ctypes.c_void_p, [ctypes.c_void_p]),
        ('gncOwnerGetOwnerFromLot',     ctypes.c_int,    [ctypes.c_void_p, ctypes.c_void_p]),
        ('gncOwnerGetID',               ctypes.c_char_p, [ctypes.c_void_p]),
        ('gnc_lot_get_earliest_split',  ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccSplitGetParent',          ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccTransGetDate',            ctypes.c_int64,  [ctypes.c_void_p]),
        ('xaccSplitGetAmount',          GncNumericC,     [ctypes.c_void_p]),
        ('gnc_lot_add_split',           ctypes.c_int,    [ctypes.c_void_p, ctypes.c_void_p]),
        ('gnc_lot_new',                 ctypes.c_void_p, [ctypes.c_void_p]),
        ('xaccAccountInsertLot',        None,            [ctypes.c_void_p, ctypes.c_void_p]),
        ('gncOwnerAttachToLot',         None,            [ctypes.c_void_p, ctypes.c_void_p]),
        ('gncOwnerInitCustomer',        None,            [ctypes.c_void_p, ctypes.c_void_p]),
        ('gncOwnerInitVendor',          None,            [ctypes.c_void_p, ctypes.c_void_p]),
    ]:
        f = getattr(lib, name)
        f.restype = restype
        f.argtypes = argtypes

    sa = lib.xaccSplitGetAmount(int(split.instance))
    split_positive = (sa.num > 0)

    owner_buf = ctypes.create_string_buffer(256)
    owner_p = ctypes.cast(owner_buf, ctypes.c_void_p)

    # Find the owner's oldest open non-invoice lot this split would REDUCE
    # (opposite sign). Same-sign or none -> a new lot (origin/orphan).
    best_lot, best_date = None, None
    glist = lib.xaccAccountGetLotList(int(split_account.instance))
    for lot_ptr in iterate_glist(lib, glist, lambda lib, p: p):
        if not lot_ptr or lib.gnc_lot_is_closed(lot_ptr):
            continue
        bal = lib.gnc_lot_get_balance(lot_ptr)
        bal_v = bal.num / bal.denom if bal.denom else 0.0
        if abs(bal_v) < 1e-9 or (bal_v > 0) == split_positive:
            continue  # closed/zero, or same sign (this split wouldn't reduce it)
        if lib.gncInvoiceGetInvoiceFromLot(lot_ptr):
            continue  # invoice/bill document lot, not a credit
        if not lib.gncOwnerGetOwnerFromLot(lot_ptr, owner_p):
            continue
        oid_raw = lib.gncOwnerGetID(owner_p)
        if (oid_raw.decode('utf-8', errors='replace') if oid_raw else '') != resolved_id:
            continue
        es = lib.gnc_lot_get_earliest_split(lot_ptr)
        when = lib.xaccTransGetDate(lib.xaccSplitGetParent(es)) if es else 0
        if best_lot is None or when < best_date:
            best_lot, best_date = lot_ptr, when

    if best_lot is not None:
        # JOIN: settle (part of) an existing credit.
        def _bal():
            b = lib.gnc_lot_get_balance(best_lot)
            return b.num / b.denom if b.denom else 0.0
        before = _bal()
        lib.gnc_lot_add_split(best_lot, int(split.instance))
        if abs(_bal() - before) < 1e-9:
            # gnc_lot_add_split silently refuses a membership it won't accept;
            # surface it rather than leave a credit the user believes settled.
            raise Exception(
                f"failed to attach the settlement split to {kind} "
                f"{resolved_id!r}'s lot (GnuCash refused the lot membership)")
        # Classify as a payment so GnuCash's register/reports treat it like an
        # ApplyPayment-created settlement (cosmetic; lot acceptance unaffected).
        _gc.xaccTransSetTxnType(split.GetParent().instance, _gc.TXN_TYPE_PAYMENT)
    else:
        # No open lot for this split to reduce. Create a new lot ONLY if the
        # split is itself a credit/payment origin — its sign matches the
        # account's credit direction (AR credits are negative, AP credits
        # positive). That covers an orphan payment being reconstructed (Q-014)
        # and a fresh credit origin. A clearing-shaped split (opposite sign)
        # with nothing to reduce is an error: we will not mint a phantom lot
        # for a refund/write-off that has no credit to apply against.
        origin_positive = (kind == 'vendor')
        if split_positive != origin_positive:
            raise Exception(
                f"{kind} {resolved_id!r} has no open credit for this split to "
                f"settle on {split_account.GetName()!r}; a clearing must target "
                f"an existing open credit (none found)")
        new_lot = lib.gnc_lot_new(int(book.instance))
        lib.xaccAccountInsertLot(int(split_account.instance), new_lot)
        lib.gnc_lot_add_split(new_lot, int(split.instance))
        attach_buf = ctypes.create_string_buffer(256)
        attach_p = ctypes.cast(attach_buf, ctypes.c_void_p)
        if kind == 'customer':
            lib.gncOwnerInitCustomer(attach_p, int(ref.instance))
        else:
            lib.gncOwnerInitVendor(attach_p, int(ref.instance))
        lib.gncOwnerAttachToLot(attach_p, new_lot)


def _attach_record_owner_to_lot(lib, record, lot_ptr):
    """Attach an invoice/bill record's owner (customer/vendor) to `lot_ptr`.

    A residual pre-payment credit lot MUST be owner-attached: otherwise
    gncOwnerGetOwnerFromLot can't resolve it and the `open_prepayment:` summary
    / find-prepayments lot-walk silently omit the credit, and the owner can
    never apply or be refunded it. An ownerless credit lot is not a valid state.

    `record.GetOwner()` returns the Customer/Vendor instance (the python-gnucash
    decorator unwraps the GncOwner), so a GncOwner is built from it via
    gncOwnerInit* before attaching — passing the raw Customer pointer straight to
    gncOwnerAttachToLot is a silent no-op. Mirrors the attach in
    `_attach_lot_owner_split`.
    """
    lib.gncOwnerInitCustomer.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gncOwnerInitCustomer.restype  = None
    lib.gncOwnerInitVendor.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gncOwnerInitVendor.restype  = None
    lib.gncOwnerAttachToLot.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gncOwnerAttachToLot.restype  = None
    ref = record.GetOwner()
    buf = ctypes.create_string_buffer(256)
    owner_p = ctypes.cast(buf, ctypes.c_void_p)
    if record.GetOwnerType() == _GNC_OWNER_VENDOR:
        lib.gncOwnerInitVendor(owner_p, int(ref.instance))
    else:
        lib.gncOwnerInitCustomer(owner_p, int(ref.instance))
    lib.gncOwnerAttachToLot(owner_p, lot_ptr)


def _retarget_with_prepayment_split(lib, book, record, existing_tx,
                                    bank_acct_name: str,
                                    post_account, invoice_lot,
                                    invoice_portion: float,
                                    prepayment_portion: float) -> bool:
    """Q-015 overpayment-retarget mechanic.

    The bank-side tx already exists (e.g. imported from QFX) and its
    counter-split (the non-bank side) is for more money than the invoice
    /bill's remaining balance. We split the counter-split into two:

      * the invoice-portion split: re-account to AR/AP, attach to the
        record's posted lot — closes the lot,
      * the prepayment-portion split (new): account = same AR/AP, attach
        to a freshly created lot on the same account — that lot stays
        open as a customer/vendor credit.

    Returns True iff the split was successful; False if no counter-split
    was found on `existing_tx`.

    Sign handling: the new prepayment split must match the counter-split's
    sign (same direction on AR/AP). For an invoice overpayment the
    counter-split is negative (e.g. -150 on AR); we split into -100 +
    -50. For a bill the counter-split is positive (+150 on AP) → +100 +
    +50.
    """
    from gnucash import GncNumeric, Split

    from infrastructure.gnucash.engine import safe_ctypes_string

    lib.xaccSplitGetAccount.argtypes = [ctypes.c_void_p]
    lib.xaccSplitGetAccount.restype  = ctypes.c_void_p
    lib.xaccSplitSetAccount.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.xaccSplitSetAccount.restype  = None
    lib.gnc_account_get_parent.argtypes = [ctypes.c_void_p]
    lib.gnc_account_get_parent.restype  = ctypes.c_void_p
    lib.gnc_lot_new.argtypes = [ctypes.c_void_p]
    lib.gnc_lot_new.restype  = ctypes.c_void_p
    lib.xaccAccountInsertLot.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.xaccAccountInsertLot.restype  = None
    lib.gnc_lot_add_split.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.gnc_lot_add_split.restype  = None

    def _acct_name(acct_ptr):
        parts = []
        ptr = acct_ptr
        while ptr:
            name = safe_ctypes_string(lib.xaccAccountGetName, ptr)
            if name:
                parts.append(name)
            parent = lib.gnc_account_get_parent(ptr)
            if not parent:
                break
            if not lib.gnc_account_get_parent(parent):
                break
            ptr = parent
        parts.reverse()
        return ':'.join(parts)

    import gnucash.gnucash_core_c as _gc

    existing_tx.BeginEdit()
    counter_split = None
    for raw_sp in existing_tx.GetSplitList():
        sp_ptr = int(raw_sp.instance)
        acct_ptr = lib.xaccSplitGetAccount(sp_ptr)
        if not acct_ptr:
            continue
        if _acct_name(acct_ptr) != bank_acct_name:
            counter_split = raw_sp
            break
    if counter_split is None:
        existing_tx.CommitEdit()
        return False

    # Reduce the existing counter-split to the invoice-portion (preserving
    # its sign), retarget it to AR/AP, link it to the invoice lot.
    sign = 1 if counter_split.GetAmount().to_double() >= 0 else -1
    invoice_signed = GncNumeric(sign * int(round(invoice_portion * 100)), 100)
    prepay_signed  = GncNumeric(sign * int(round(prepayment_portion * 100)), 100)

    counter_split.SetAmount(invoice_signed)
    counter_split.SetValue(invoice_signed)
    lib.xaccSplitSetAccount(int(counter_split.instance), int(post_account.instance))
    _gc.xaccSplitSetLot(counter_split.instance, invoice_lot.instance)

    # Create the prepayment split on the same tx, on the same AR/AP account,
    # in a brand-new lot on that account.
    new_split = Split(book)
    new_split.SetParent(existing_tx)
    new_split.SetAccount(post_account)
    new_split.SetAmount(prepay_signed)
    new_split.SetValue(prepay_signed)

    new_lot_ptr = lib.gnc_lot_new(int(book.instance))
    lib.xaccAccountInsertLot(int(post_account.instance), new_lot_ptr)
    lib.gnc_lot_add_split(new_lot_ptr, int(new_split.instance))

    # The residual is the record owner's credit; attach the owner so the lot is
    # owner-attached and visible to the open_prepayment summary / find-prepayments.
    _attach_record_owner_to_lot(lib, record, new_lot_ptr)

    existing_tx.CommitEdit()
    return True


def _datetime_to_time64(dt) -> int:
    """Convert a naive `datetime` (e.g. parsed via `strptime(%Y-%m-%d)`) to
    a GnuCash time64. Matches the SWIG `gncInvoicePostToAccount` path
    semantics so the link-based POSTED handler produces a byte-identical
    `date_posted` / `date_due` to the PostToAccount fallback on the same
    machine (both round-trip through Python's local-TZ `timestamp()`).
    Pinned in a single helper so a future SWIG-side change can be matched
    here in one place.
    """
    return int(dt.timestamp())


_ATTACH_API_VERIFIED = False


def _verify_attach_api():
    """Probe the GnuCash SWIG surface that `_attach_existing_tx_as_posted`
    depends on at first use. Failing fast with a named symbol is friendlier
    than a `module has no attribute` deep in the POSTED handler, and gives
    a clean signal if a future GnuCash version drops one of the setters.
    Runs once per process.
    """
    global _ATTACH_API_VERIFIED
    if _ATTACH_API_VERIFIED:
        return

    import gnucash.gnucash_core_c as _gc

    required_swig = [
        'gncInvoiceAttachToTxn', 'gncInvoiceAttachToLot',
        'gncInvoiceSetPostedAcc', 'gncInvoiceSetDatePosted',
        'xaccAccountInsertLot', 'xaccSplitSetLot',
        # gncInvoice has no public date_due setter; due_date is stored on
        # the posting transaction (gncInvoiceGetDateDue → xaccTransRetDateDue,
        # gncInvoicePostToAccount → xaccTransSetDateDue). We set it the same
        # way.
        'xaccTransSetDateDue',
    ]
    missing_swig = [s for s in required_swig if not hasattr(_gc, s)]
    if missing_swig:
        raise RuntimeError(
            'GnuCash SWIG bindings missing required symbols for '
            'posted-tx linkage: ' + ', '.join(missing_swig)
        )
    _ATTACH_API_VERIFIED = True


_BUSINESS_GENERATED_META = {'business_generated': 'true'}


def _attach_existing_tx_as_posted(invoice_or_bill, existing_tx, ar_ap_account,
                                   post_date, due_date, memo, accumulate,
                                   book, kind: str, id_: str) -> None:
    """Wire an already-imported transaction as the invoice/bill's posted tx,
    bypassing `PostToAccount`. Mirrors what `gncInvoicePostToAccount` does
    internally so the result is indistinguishable to the rest of GnuCash:

      1. Create a fresh GncLot on the AR/AP account.
      2. Override the tx description to the declared memo (matches what
         the existing PostToAccount path does immediately after posting)
         and mark the tx as business-generated in custom KVP.
      3. Attach the tx's single AR/AP-side split to the lot.
      4. gncInvoiceAttachToTxn / AttachToLot — bidirectional wiring of
         tx ↔ invoice and lot ↔ invoice KVP backrefs PLUS the invoice's
         posted_txn / posted_lot pointers (so explicit SetPostedTxn /
         SetPostedLot would trip `'invoice->posted_txn == NULL'` /
         `posted_lot == NULL` assertions and must NOT be called).
      5. gncInvoiceSetPostedAcc / gncInvoiceSetDatePosted /
         xaccTransSetDateDue populate the remaining posting fields.
         `gncInvoice` has no public date_due setter — `gncInvoiceGetDateDue`
         reads through to `xaccTransRetDateDue(posting_txn)`, so we set
         due-date on the *transaction* the same way
         `gncInvoicePostToAccount` does internally.

    Invariants:
      * Posting txs always have exactly ONE AR/AP-side split — GnuCash's
        `PostToAccount` collapses AR/AP into a single split regardless of
        the `accumulate` flag (`accumulate` only affects the income/expense
        side: True = one income split per income/expense account, False =
        one per entry). We assert this on the linked tx and refuse to
        attach a malformed one rather than silently leaving extra AR/AP
        splits orphan.
      * `accumulate` is accepted for API parity with PostToAccount but is
        not used here — the splits are already in the existing tx as
        authored by the user.
    """
    import gnucash.gnucash_core_c as _gc
    from gnucash import GncLot

    if existing_tx is None:
        raise ValueError(
            f'{kind} "{id_}": cannot attach posted tx (lookup returned None)'
        )

    _verify_attach_api()

    ar_ap_acct_inst = int(ar_ap_account.instance)
    ar_ap_splits = [
        sp for sp in existing_tx.GetSplitList()
        if (a := sp.GetAccount()) is not None
        and int(a.instance) == ar_ap_acct_inst
    ]
    if not ar_ap_splits:
        raise ValueError(
            f'{kind} "{id_}": linked posted tx '
            f'{existing_tx.GetGUID().to_string()} has no split for the '
            f'declared posting account {get_account_full_name(ar_ap_account)!r}'
        )
    if len(ar_ap_splits) > 1:
        raise ValueError(
            f'{kind} "{id_}": linked posted tx '
            f'{existing_tx.GetGUID().to_string()} has '
            f'{len(ar_ap_splits)} splits in {get_account_full_name(ar_ap_account)!r} '
            f'but a posting tx must have exactly one AR/AP-side split '
            f'(GnuCash collapses AR/AP into a single split regardless of '
            f'the `accumulate` flag). Author the tx with one AR/AP split '
            f'totalling the invoice/bill amount.'
        )
    ar_ap_split = ar_ap_splits[0]

    # Step 1: fresh lot in the AR/AP account (pure SWIG — keeps ctypes
    # ↔ SWIG bridging out of the lot lifecycle, which is sensitive on
    # Ubuntu per docs/DEBUGGING_GNUCASH_BINDINGS.md).
    lot = GncLot(book)
    _gc.xaccAccountInsertLot(ar_ap_account.instance, lot.instance)

    # Step 2-3: override description, plant business_generated marker in
    # custom KVP (not Notes — Notes is a user-visible field), set
    # due-date on the posting tx (where gncInvoiceGetDateDue reads it
    # from), attach AR/AP split to lot. Merge — don't replace — the KVP
    # so any user-authored custom keys on the standalone-imported tx
    # survive: set_custom_metadata overwrites the whole `plaintext_meta`
    # slot.
    existing_tx.BeginEdit()
    existing_tx.SetDescription(memo)
    existing_custom = get_custom_metadata(existing_tx) or {}
    existing_custom.update(_BUSINESS_GENERATED_META)
    set_custom_metadata(existing_tx, existing_custom)
    _gc.xaccTransSetDateDue(existing_tx.instance,
                            _datetime_to_time64(due_date))
    _gc.xaccSplitSetLot(ar_ap_split.instance, lot.instance)
    existing_tx.CommitEdit()

    # Step 4-5: wire invoice's posted_* properties and KVP backrefs.
    inv_inst = invoice_or_bill.instance
    invoice_or_bill.BeginEdit()
    _gc.gncInvoiceAttachToLot(inv_inst, lot.instance)
    _gc.gncInvoiceAttachToTxn(inv_inst, existing_tx.instance)
    _gc.gncInvoiceSetPostedAcc(inv_inst, ar_ap_account.instance)
    _gc.gncInvoiceSetDatePosted(inv_inst, _datetime_to_time64(post_date))
    invoice_or_bill.CommitEdit()


def _is_falsy(val: str) -> bool:
    """Return True if val is a recognised falsy string (case-insensitive)."""
    return val.strip().lower() in _FALSY_STRINGS


ACCT_TYPE_MAP = {
    "Asset": ACCT_TYPE_ASSET,
    "Bank": ACCT_TYPE_BANK,
    "Expense": ACCT_TYPE_EXPENSE,
    "Income": ACCT_TYPE_INCOME,
    "Equity": ACCT_TYPE_EQUITY,
    "Credit Card": ACCT_TYPE_CREDIT,
    "Liability": ACCT_TYPE_LIABILITY,
    "Mutual Fund": ACCT_TYPE_MUTUAL,
    "Accounts Payable": ACCT_TYPE_PAYABLE,
    "A/Payable": ACCT_TYPE_PAYABLE,          # GnuCash internal short form
    "Accounts Receivable": ACCT_TYPE_RECEIVABLE,
    "A/Receivable": ACCT_TYPE_RECEIVABLE,    # GnuCash internal short form
    "Stock": ACCT_TYPE_STOCK,
    "Cash": ACCT_TYPE_CASH,
}


def create_tax_table_entry(book, account, amount_percent):
    from gnucash.gnucash_core_c import (
        GNC_AMT_TYPE_PERCENT,
        gncTaxTableEntryCreate,
        gncTaxTableEntrySetAmount,
        gncTaxTableEntrySetType,
    )
    raw = gncTaxTableEntryCreate()
    gncTaxTableEntrySetType(raw, GNC_AMT_TYPE_PERCENT)
    amount = GncNumeric(round(amount_percent * 100000), 100000)
    gncTaxTableEntrySetAmount(raw, amount.instance)
    gncTaxTableEntrySetAccount(raw, account.instance)
    return TaxTableEntry(instance=raw)


def _customer_matches_directive(customer, directive: 'PlaintextDirective') -> bool:
    """Return True if the customer's persisted state equals the directive.

    Used by Q-010 to distinguish 'unchanged' (no-diff re-import) from
    'updated' (a real mutation passed through). Compares only persisted
    fields — the same set that `import_customer` writes — so two views of
    the *same* on-disk customer (after a save+reload cycle) compare equal.
    """
    md = directive.metadata
    if customer.GetName() != md['name']:
        return False
    addr = customer.GetAddr()
    if addr.GetAddr1() != md.get('addr1', ''):
        return False
    if addr.GetAddr2() != md.get('addr2', ''):
        return False
    if addr.GetAddr3() != md.get('addr3', ''):
        return False
    if addr.GetAddr4() != md.get('addr4', ''):
        return False
    if addr.GetEmail() != md.get('email', ''):
        return False
    desired_active = not _is_falsy(md.get('active', 'true'))
    if bool(customer.GetActive()) != desired_active:
        return False
    desired_custom = {k: v for k, v in md.items()
                      if k not in KNOWN_CUSTOMER_METADATA_KEYS and v is not None}
    existing_custom = get_custom_metadata(customer) or {}
    return existing_custom == desired_custom


def _vendor_matches_directive(vendor, directive: 'PlaintextDirective') -> bool:
    """Return True if the vendor's persisted state equals the directive (Q-010)."""
    md = directive.metadata
    if vendor.GetName() != md['name']:
        return False
    desired_active = not _is_falsy(md.get('active', 'true'))
    if bool(vendor.GetActive()) != desired_active:
        return False
    desired_custom = {k: v for k, v in md.items()
                      if k not in KNOWN_VENDOR_METADATA_KEYS and v is not None}
    existing_custom = get_custom_metadata(vendor) or {}
    return existing_custom == desired_custom


def _gnc_numeric_equals(num, value_str: str) -> bool:
    """Compare a GncNumeric against a string-form value (e.g. '100', '2.5').

    Uses GncNumeric.equal() to compare exactly. The directive value is
    parsed with `string_to_gnc_numeric_quantity` so the precision matches
    what the importer would write.
    """
    return num.equal(string_to_gnc_numeric_quantity(value_str))


def _entry_matches_invoice_directive(entry, ed: 'PlaintextDirective') -> bool:
    """Compare an existing customer-invoice Entry to an INVOICE_ENTRY directive."""
    md = ed.metadata
    if entry.GetDate().strftime("%Y-%m-%d") != md['date']:
        return False
    if entry.GetDescription() != md['description']:
        return False
    if entry.GetAction() != md.get('action', ''):
        return False
    acct = entry.GetInvAccount()
    if acct is None or get_account_full_name(acct) != md['account']:
        return False
    if not _gnc_numeric_equals(entry.GetQuantity(), md['quantity']):
        return False
    if not _gnc_numeric_equals(entry.GetInvPrice(), md['price']):
        return False
    if bool(entry.GetInvTaxable()) != (md['taxable'] == 'true'):
        return False
    if bool(entry.GetInvTaxIncluded()) != (md['tax_included'] == 'true'):
        return False
    desired_tt = md.get('tax_table')
    actual_tt_obj = entry.GetInvTaxTable() if entry.GetInvTaxable() else None
    actual_tt = actual_tt_obj.GetName() if actual_tt_obj is not None else None
    return (desired_tt or None) == (actual_tt or None)


def _entry_matches_bill_directive(entry, ed: 'PlaintextDirective') -> bool:
    """Compare an existing vendor-bill Entry to a BILL_ENTRY directive.

    NOTE on `taxable`: GnuCash does not persist `bill_taxable: false` to XML
    (CLAUDE.md §8); a bill entry always reads back as taxable=True after a
    save+reload. We treat both directive values as equivalent on the bill
    side to avoid spurious 'updated' on every re-import. If a future GnuCash
    version starts persisting it, this comparison can be tightened.
    """
    md = ed.metadata
    if entry.GetDate().strftime("%Y-%m-%d") != md['date']:
        return False
    if entry.GetDescription() != md['description']:
        return False
    acct = entry.GetBillAccount()
    if acct is None or get_account_full_name(acct) != md['account']:
        return False
    if not _gnc_numeric_equals(entry.GetQuantity(), md['quantity']):
        return False
    if not _gnc_numeric_equals(entry.GetBillPrice(), md['price']):
        return False
    desired_tt = md.get('tax_table')
    actual_tt_obj = entry.GetBillTaxTable() if entry.GetBillTaxable() else None
    actual_tt = actual_tt_obj.GetName() if actual_tt_obj is not None else None
    return (desired_tt or None) == (actual_tt or None)


def _posted_matches_directive(invoice, posted_dir: 'PlaintextDirective',
                              ar_or_ap_key: str) -> bool:
    """Compare an existing posted invoice/bill's posting state to a POSTED directive."""
    md = posted_dir.metadata
    posting_acct = invoice.GetPostedAcc()
    if posting_acct is None or get_account_full_name(posting_acct) != md[ar_or_ap_key]:
        return False
    posted_date = invoice.GetDatePosted()
    if posted_date.strftime("%Y-%m-%d") != md['date']:
        return False
    due_date = invoice.GetDateDue()
    if due_date.strftime("%Y-%m-%d") != md['due']:
        return False
    posting_txn = invoice.GetPostedTxn()
    if posting_txn is None:
        return False
    if posting_txn.GetDescription() != md['memo']:
        return False
    declared_posted_guid = md.get('posted_txn_guid')
    return not (declared_posted_guid and posting_txn.GetGUID().to_string() != _normalise_guid(declared_posted_guid))


def _lot_payment_splits(record):
    """Return the AR/AP-side splits in the record's posted lot, in
    GnuCash's iteration order, excluding the posting tx's own split AND
    any split whose parent tx is a credit-consumption tx (Q-015
    `auto_apply_credit`).

    Used by both `_payments_match_directive` (strict count + field equality)
    and `_payments_only_added_diff` (prefix-equal-superset check). In both
    cases, auto-applied credit-consumption splits don't represent
    user-declared `payment:` blocks — they're tracked via the
    `auto_apply_credit: true` flag on the invoice/bill header.
    """
    import gnucash.gnucash_core_c as _gc
    from gnucash import Split
    lot = record.GetPostedLot()
    if lot is None:
        return []
    posting_txn = record.GetPostedTxn()
    posting_txn_guid = posting_txn.GetGUID().to_string() if posting_txn else None
    this_lot_id = int(lot.instance)
    out = []
    for raw in lot.get_split_list():
        s = Split(instance=raw)
        tx = s.GetParent()
        if tx is None:
            continue
        if posting_txn_guid is not None and tx.GetGUID().to_string() == posting_txn_guid:
            continue
        # Q-015 / Q-016: skip splits that came from
        # `gncInvoiceAutoApplyPayments`. Auto-apply signature: the
        # parent tx has AR/AP splits in BOTH another invoice lot (the
        # original-closure lot) AND a prepay lot (the residual). Q-015
        # overpayment has only the prepay lot; Q-016 multi-invoice has
        # only other invoice lots; both must NOT be classified as
        # credit consumption — their splits ARE real payments.
        has_other_invoice_lot = False
        has_prepay_lot = False
        for i in range(tx.CountSplits()):
            other = tx.GetSplit(i)
            other_acct = other.GetAccount()
            if other_acct is None:
                continue
            other_type = other_acct.GetType()
            if other_type not in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
                continue
            other_lot = other.GetLot()
            if other_lot is None:
                continue
            if int(other_lot) == this_lot_id:
                continue
            if _gc.gncInvoiceGetInvoiceFromLot(other_lot):
                has_other_invoice_lot = True
            else:
                has_prepay_lot = True
        if has_other_invoice_lot and has_prepay_lot:
            continue
        out.append(s)
    return out


def _prepayment_amount_for(in_lot_split):
    """Sum of absolute amounts of AR/AP-side splits on `in_lot_split`'s
    parent transaction OTHER than `in_lot_split` itself.

    Returns 0 (as a `Decimal`-castable float) when the payment tx has
    exactly one AR/AP split — the normal full-or-partial-payment case.
    Returns the residual amount (as `float`) when GnuCash split the
    payment across multiple AR/AP lots (overpayment → in-invoice lot +
    one or more prepayment lots).
    """
    tx = in_lot_split.GetParent()
    in_lot_guid = in_lot_split.GetGUID().to_string()
    total = 0.0
    for s in tx.GetSplitList():
        if s.GetGUID().to_string() == in_lot_guid:
            continue
        acct = s.GetAccount()
        if acct is None:
            continue
        if acct.GetType() in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
            total += abs(s.GetAmount().to_double())
    return total


def _single_payment_matches(split, pd) -> bool:
    """Compare one AR/AP-side payment split against one PAYMENT directive.

    Returns True iff the directive's fields match the underlying bank-side
    transaction. Two directive flavours:
      - **Normal**: bank_account, date, amount, memo, num all compared.
      - **Retarget (txn_guid)**: only bank_account and the tx GUID itself
        — date/amount/memo on the directive aren't authoritative.

    Memo lives on the bank-side split (see `_format_payment` in the
    exporter), not on the transaction description.

    Identifying the bank-side split: an overpayment tx has THREE splits —
    bank + AR/AP-in-lot + AR/AP-in-prepayment-lot. We must find the
    bank-side split by account match (the directive declares
    `bank_account` authoritatively), not by exclusion against the
    AR/AP-side split we were passed — the latter would pick the
    other AR/AP split when iteration order put it first.
    """
    md = pd.metadata
    tx = split.GetParent()
    bank_acct_name = _payment_xfer_account_name(md)
    bank_split = next(
        (s for s in tx.GetSplitList()
         if (a := s.GetAccount()) is not None
         and get_account_full_name(a) == bank_acct_name),
        None,
    )
    if bank_split is None:
        return False
    directive_txn_guid = (md.get('txn_guid') or '').strip()
    if directive_txn_guid:
        return tx.GetGUID().to_string() == directive_txn_guid
    if tx.GetDate().strftime("%Y-%m-%d") != md['date']:
        return False
    if not _gnc_numeric_equals(bank_split.GetAmount().abs(), md['amount']):
        return False
    if (bank_split.GetMemo() or '') != md.get('memo', ''):
        return False
    if (tx.GetNum() or '') != md.get('num', ''):
        return False
    # Q-015: compare prepayment portion (sum of AR/AP-side splits OTHER
    # than the in-lot one) against the directive's `prepayment:` field.
    # Missing on the directive ⇔ 0 in the book.
    actual_prepay = _prepayment_amount_for(split)
    raw_prepay = md.get('prepayment')
    if raw_prepay is None or str(raw_prepay).strip() == '':
        expected_prepay = 0.0
    else:
        try:
            expected_prepay = float(str(raw_prepay).strip())
        except ValueError:
            return False
    return not abs(actual_prepay - expected_prepay) > 1e-06


def _payments_match_directive(record, payment_dirs) -> bool:
    """True iff the record's posted-lot payments match the directives
    one-for-one (same count, same field values). Used by the strict
    `_invoice_matches_directive` / `_bill_matches_directive`.
    """
    pay_splits = _lot_payment_splits(record)
    if len(pay_splits) != len(payment_dirs):
        return False
    return all(_single_payment_matches(s, pd) for s, pd in zip(pay_splits, payment_dirs))


def _emit_orphan_warning_before_unpost(record, kind: str, ident: str,
                                       on_orphan_warning):
    """Q-015: every importer-side `Unpost(False)` on a paid record must
    surface the resulting orphan(s) to the user. Call this *before*
    `record.Unpost(False)` — once unposted, the lot's invoice association
    is destroyed and the orphans can no longer be enumerated from `record`.

    `on_orphan_warning(kind, ident, orphans)` is invoked only when the
    record has at least one payment-class transaction attached to its
    posted lot. If the callback is None (library callers that don't want
    the warning surfaced) the helper is a no-op aside from the
    `find_lot_payment_transactions` call, which is safe.
    """
    if on_orphan_warning is None:
        return
    if record.GetPostedTxn() is None:
        return
    from use_cases.unpost_business_objects import find_lot_payment_transactions
    orphans = find_lot_payment_transactions(record)
    if orphans:
        on_orphan_warning(kind, ident, orphans)


# Account-type categories for a payment's transfer (non-AR/AP) account.
_ASSET_ACCT_TYPES = {0, 1, 2, 5, 6}   # BANK, CASH, ASSET, STOCK, MUTUAL
_EXPENSE_ACCT_TYPE = 9                 # EXPENSE
_EQUITY_ACCT_TYPE = 10                 # EQUITY


def _payment_xfer_account_name(md):
    """The payment block's transfer account, accepting `account:` (canonical)
    or the legacy `bank_account:` alias. Despite the legacy name the account
    need not be a bank — an expense routes an invoice payment to a bad-debt
    write-off. If both keys are present they must name the same account."""
    acct = md.get('account')
    bank = md.get('bank_account')
    if acct and bank and acct != bank:
        raise Exception(
            f"payment declares both account: {acct!r} and bank_account: "
            f"{bank!r} — they must name the same account")
    name = acct or bank
    if not name:
        raise Exception("payment block has no account: (or bank_account:)")
    return name


def _validate_payment_account_type(account, is_bill, name):
    """Constrain a payment's transfer account by side. The account where a
    payment lands may be:

    - an **asset** (bank / cash received or paid) — the ordinary payment, either
      side;
    - **owner's equity** — an entity-aware deposit / clearing account, either
      side. A Canadian sole proprietor has no separate business bank: the
      business tax return reports only income and expense, so customer receipts
      (and bills paid from personal funds) flow through `Equity:Owner equity`
      rather than a bank. (A corporation that routes through a shareholder loan
      models "due from director" as an *asset*, which the asset case already
      covers.)
    - an **expense** — a bad-debt write-off, **invoices only**. An unpaid bill we
      owe is debt forgiveness (a gain booked to income), out of scope, so an
      expense on a bill is rejected.

    Other types are rejected: income on an invoice double-counts the revenue
    already recognised at posting; AR/AP itself, the root, trading, etc. are
    never a payment counter account."""
    t = account.GetType()
    if t in _ASSET_ACCT_TYPES or t == _EQUITY_ACCT_TYPE:
        return
    if not is_bill and t == _EXPENSE_ACCT_TYPE:
        return  # invoice bad-debt write-off
    if is_bill:
        raise Exception(
            f"a bill payment must use an asset or owner's-equity account; "
            f"{name!r} is neither (an unpaid bill is debt forgiveness — a gain "
            f"— so an expense is out of scope)")
    raise Exception(
        f"an invoice payment must use an asset account (cash received), an "
        f"owner's-equity deposit account, or an expense account (bad-debt "
        f"write-off); {name!r} is none of these")


def _apply_payment_directive(record, pay_dir, book, is_bill):
    """Apply one PAYMENT directive to an already-posted invoice or bill.

    Used by both the normal rebuild path (after entries/posted have been
    re-applied) and the Q-015 add-payment fast path (the record is still
    posted and is mutated in-place).

    For invoices, `ApplyPayment(+amount)` closes the AR lot. For bills,
    AP has the opposite sign convention so we pass `-amount`; see Q-014
    notes in `CLAUDE.md` for the accounting reasoning.
    """
    bank_acct_name = _payment_xfer_account_name(pay_dir.metadata)
    bank_account = find_account(book.get_root_account(), bank_acct_name)
    if bank_account is None:
        kind = 'bill' if is_bill else 'invoice'
        raise Exception(f'Payment account {bank_acct_name!r} not found when applying {kind} payment')
    _validate_payment_account_type(bank_account, is_bill, bank_acct_name)

    # Q-016: the field carrying the bank-tx-split pointer was renamed
    # from `payment_split_guid:` to `txn_split_guid:` so the prefix
    # mirrors `txn_guid:`. Fail loudly on the legacy name rather than
    # silently fall through to the iterative-retarget path — that path
    # is fragile/wrong in multi-invoice and same-amount cases, and a
    # silent fallback would erode the round-trip identity guarantee.
    if pay_dir.metadata.get('payment_split_guid'):
        raise Exception(
            'payment_split_guid: is no longer accepted — rename to '
            'txn_split_guid: (the field points at a split on the bank '
            'tx named by txn_guid:, so the prefix matches)'
        )

    txn_guid = pay_dir.metadata.get('txn_guid', '').strip()
    if txn_guid:
        # Retarget: existing bank tx is retargeted into the AR/AP lot
        # without `ApplyPayment` (no new tx, preserves original tx GUID
        # and KVP). Counter-split retargeting closes the lot when the
        # AR/AP-side split sum hits zero.
        existing_tx = _find_transaction_by_guid(book, txn_guid)
        if existing_tx is None:
            raise Exception(f'txn_guid {txn_guid!r} not found in book')
        post_acct = record.GetPostedAcc()
        lot = record.GetPostedLot()
        if lot is None:
            kind = 'Bill' if is_bill else 'Invoice'
            raise Exception(f'{kind} has no posted lot — must be posted before payment')
        from infrastructure.gnucash.engine import load_gnc_engine
        lib = load_gnc_engine()

        # Q-016: if `txn_split_guid:` is declared, the directive
        # identifies the exact AR/AP-side split on the bank tx (named
        # by `txn_guid:` above) to attach to this invoice/bill's lot.
        # No retargeting math, no counter-split splitting — just
        # attach. This is the multi-invoice-1-bank-tx mechanism and
        # also the deterministic single-invoice path. Composes with
        # `prepayment:` for the overpayment-via-retarget case: the
        # specified split closes the invoice/bill, and the remaining
        # AR/AP-side splits stay in their prepay lot.
        declared_split_guid = pay_dir.metadata.get('txn_split_guid', '').strip()
        if declared_split_guid:
            try:
                target_split_guid = _normalise_guid(declared_split_guid)
            except Exception as exc:
                raise Exception(
                    f'txn_split_guid {declared_split_guid!r} is not a valid GUID'
                ) from exc
            target_split = None
            for raw_sp in existing_tx.GetSplitList():
                if raw_sp.GetGUID().to_string().replace('-', '').lower() == target_split_guid:
                    target_split = raw_sp
                    break
            if target_split is None:
                raise Exception(
                    f'txn_split_guid {declared_split_guid!r} not found on '
                    f'tx {txn_guid!r}'
                )
            target_acct = target_split.GetAccount()
            if target_acct is None or target_acct.GetType() not in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
                raise Exception(
                    f'txn_split_guid {declared_split_guid!r} on tx {txn_guid!r} '
                    f'does not live on an AR/AP account'
                )
            # Q-016 defensive check: the named split's account must match
            # the invoice/bill's posted AR/AP account. A typo in
            # `txn_split_guid:` pointing at a split on a DIFFERENT
            # AR account would otherwise attach to the wrong lot silently.
            if get_account_full_name(target_acct) != get_account_full_name(post_acct):
                raise Exception(
                    f'txn_split_guid {declared_split_guid!r} on tx {txn_guid!r} '
                    f'lives on {get_account_full_name(target_acct)!r} but the '
                    f'invoice/bill\'s posted account is {get_account_full_name(post_acct)!r}'
                )
            import gnucash.gnucash_core_c as _gc
            _gc.xaccSplitSetLot(target_split.instance, lot.instance)

            # If `prepayment:` is also declared, the user is composing
            # explicit-split routing with an overpayment residual. The
            # standalone tx import created the residual as a loose AR/AP
            # split (no lot membership); we need to park it in a fresh
            # prepay lot here. (In the multi-invoice case there is no
            # `prepayment:` — the sibling AR splits belong to OTHER
            # invoices' lots and their own directives will attach them.)
            raw_prepay = pay_dir.metadata.get('prepayment')
            declared_prepay_str = '' if raw_prepay is None else str(raw_prepay).strip()
            if declared_prepay_str:
                try:
                    declared_prepay = float(declared_prepay_str)
                except ValueError as exc:
                    raise Exception(
                        f'prepayment field must be a number, got {declared_prepay_str!r}'
                    ) from exc
                # Find sibling splits on the same AR/AP account, not the
                # target, that are still loose. Each becomes its own
                # prepay lot. Their absolute amounts must sum to the
                # declared prepayment (defensive check).
                loose_siblings = []
                actual_prepay = 0.0
                for raw_sp in existing_tx.GetSplitList():
                    if raw_sp.GetGUID().to_string().replace('-', '').lower() == target_split_guid:
                        continue
                    sp_acct = raw_sp.GetAccount()
                    if sp_acct is None:
                        continue
                    if get_account_full_name(sp_acct) != get_account_full_name(post_acct):
                        continue
                    # A residual prepayment split on this tx. Count it toward the
                    # declared prepayment whether it is still loose (a legacy
                    # export) or already parked in its owner lot: an export that
                    # carries `lot_owner:` on the residual has the standalone-tx
                    # import attach it first, so by now it is no longer loose.
                    # Park only the loose ones; already-parked siblings keep the
                    # owner lot the lot_owner import gave them.
                    actual_prepay += abs(raw_sp.GetAmount().to_double())
                    if raw_sp.GetLot() is None:
                        loose_siblings.append(raw_sp)
                if abs(actual_prepay - declared_prepay) > 1e-6:
                    raise Exception(
                        f'declared `prepayment: {declared_prepay}` does not '
                        f'match the residual AR/AP splits on tx {txn_guid!r} '
                        f'(sum of loose siblings = {actual_prepay:.2f})'
                    )
                lib.gnc_lot_new.argtypes = [ctypes.c_void_p]
                lib.gnc_lot_new.restype  = ctypes.c_void_p
                lib.xaccAccountInsertLot.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                lib.xaccAccountInsertLot.restype  = None
                lib.gnc_lot_add_split.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                lib.gnc_lot_add_split.restype  = None
                existing_tx.BeginEdit()
                for sib in loose_siblings:
                    new_lot_ptr = lib.gnc_lot_new(int(book.instance))
                    lib.xaccAccountInsertLot(int(post_acct.instance), new_lot_ptr)
                    lib.gnc_lot_add_split(new_lot_ptr, int(sib.instance))
                    # The residual is the record owner's credit — attach the
                    # owner so the parked lot is visible to the open_prepayment
                    # summary / find-prepayments, not a silent ownerless credit.
                    _attach_record_owner_to_lot(lib, record, new_lot_ptr)
                existing_tx.CommitEdit()
            return

        # Q-015: detect overpayment via retarget. The counter-split's
        # absolute amount = bank-side amount. If it exceeds the lot's
        # remaining balance the user is asking us to overpay; that
        # requires the `prepayment:` field on the directive (we will not
        # silently leave the lot in an overpaid state).
        counter_amount_abs = None
        for raw_sp in existing_tx.GetSplitList():
            acct = raw_sp.GetAccount()
            if acct is None:
                continue
            if get_account_full_name(acct) != bank_acct_name:
                counter_amount_abs = abs(raw_sp.GetAmount().to_double())
                break
        invoice_remaining_abs = abs(lot.get_balance().to_double())

        if counter_amount_abs is not None and \
                counter_amount_abs > invoice_remaining_abs + 1e-6:
            expected_prepay = counter_amount_abs - invoice_remaining_abs
            raw_declared = pay_dir.metadata.get('prepayment')
            declared_str = '' if raw_declared is None else str(raw_declared).strip()
            kind = 'bill' if is_bill else 'invoice'
            if not declared_str:
                raise Exception(
                    f'tx {txn_guid!r} amount {counter_amount_abs:.2f} '
                    f'exceeds {kind} remaining {invoice_remaining_abs:.2f}; '
                    f'add `prepayment: {expected_prepay:.2f}` to the payment '
                    f'block to accept the residual as a pre-payment credit, '
                    f'or retarget a bank tx whose counter-split matches the '
                    f'{kind}\'s outstanding amount exactly.'
                )
            try:
                declared = float(declared_str)
            except ValueError as exc:
                raise Exception(
                    f'prepayment field must be a number, got {declared_str!r}'
                ) from exc
            if abs(declared - expected_prepay) > 1e-6:
                raise Exception(
                    f'declared `prepayment: {declared}` does not match the '
                    f'computed residual {expected_prepay:.2f} (tx counter-split '
                    f'{counter_amount_abs:.2f} − {kind} remaining '
                    f'{invoice_remaining_abs:.2f}).'
                )
            if not _retarget_with_prepayment_split(
                    lib, book, record, existing_tx, bank_acct_name,
                    post_acct, lot, invoice_remaining_abs, expected_prepay):
                raise Exception(
                    f'Could not find counter-split in tx {txn_guid!r} — '
                    f'expected a non-{bank_acct_name!r} split'
                )
            return

        # Exact or partial retarget: original whole-split move.
        if not _retarget_counter_split_to_lot(
                lib, existing_tx, bank_acct_name, post_acct, lot):
            raise Exception(
                f'Could not find counter-split in tx {txn_guid!r} — '
                f'expected a non-{bank_acct_name!r} split'
            )
        return

    pay_date = datetime.strptime(pay_dir.metadata['date'], "%Y-%m-%d")
    amount_str = pay_dir.metadata['amount']
    memo = pay_dir.metadata['memo']
    num = pay_dir.metadata.get('num', '')
    if is_bill:
        amount = string_to_gnc_numeric_quantity(f'-{amount_str}')
    else:
        amount = string_to_gnc_numeric_quantity(amount_str)
    # Pass txn=None: GnuCash creates the payment transaction internally.
    # Passing a manually-allocated Transaction causes a segfault on
    # GnuCash 3.8 (ubuntu20) because the tx is not initialised before
    # ApplyPayment uses it.
    record.ApplyPayment(None, bank_account, amount, GncNumeric(1, 1), pay_date, memo, num)


def _payments_only_added_diff(record, payment_dirs):
    """Q-015 classifier helper.

    Return (True, added_directives) iff the directive's PAYMENT list is a
    strict prefix-equal superset of the record's existing lot payments:
    every existing payment matches the corresponding directive 1:1, and
    the directive has additional payment directives at the tail.

    Return (False, []) for any other shape — equal count, directive has
    fewer payments, or any in-place modification of an existing payment.
    """
    pay_splits = _lot_payment_splits(record)
    if len(pay_splits) >= len(payment_dirs):
        return False, []
    for s, pd in zip(pay_splits, payment_dirs[:len(pay_splits)]):
        if not _single_payment_matches(s, pd):
            return False, []
    return True, list(payment_dirs[len(pay_splits):])


def _record_consumed_credit(record) -> bool:
    """Q-015: True iff the record's posted lot contains splits that came
    from `gncInvoiceAutoApplyPayments` (i.e. a payment tx attached to
    another invoice/bill's lot for the same owner). Mirrors the exporter's
    `_payment_is_credit_consumption` heuristic — see use_cases/export_business_objects.py.
    """
    import gnucash.gnucash_core_c as _gc
    lot = record.GetPostedLot()
    if lot is None:
        return False
    this_lot_id = int(lot.instance)
    posting_txn = record.GetPostedTxn()
    posting_txn_guid = posting_txn.GetGUID().to_string() if posting_txn else None
    from gnucash import Split
    for raw in lot.get_split_list():
        s = Split(instance=raw)
        tx = s.GetParent()
        if tx is None:
            continue
        if posting_txn_guid is not None and tx.GetGUID().to_string() == posting_txn_guid:
            continue
        has_other_invoice_lot = False
        has_prepay_lot = False
        for i in range(tx.CountSplits()):
            other = tx.GetSplit(i)
            other_acct = other.GetAccount()
            if other_acct is None:
                continue
            if other_acct.GetType() not in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
                continue
            other_lot = other.GetLot()
            if other_lot is None or int(other_lot) == this_lot_id:
                continue
            if _gc.gncInvoiceGetInvoiceFromLot(other_lot):
                has_other_invoice_lot = True
            else:
                has_prepay_lot = True
        # Q-015 / Q-016: auto-apply consumption requires BOTH another
        # invoice lot (original closure) AND a prepay lot (residual).
        # Q-015 overpayment lacks the former; Q-016 multi-invoice lacks
        # the latter — neither is credit consumption.
        if has_other_invoice_lot and has_prepay_lot:
            return True
    return False


def _invoice_non_payment_matches(invoice, directive: 'PlaintextDirective') -> bool:
    """True iff every non-payment field of an existing customer invoice
    matches the directive: date_opened, billing_id, notes, custom KVP,
    entries (positional by field), and the posted block (or its absence).
    Used by both the strict-equality classifier and the Q-015 add-only
    classifier — payments are checked separately."""
    md = directive.metadata
    if invoice.GetDateOpened().strftime("%Y-%m-%d") != md['date_opened']:
        return False
    if invoice.GetBillingID() != md.get('billing_id', ''):
        return False
    if invoice.GetNotes() != md.get('notes', ''):
        return False
    desired_custom = {k: v for k, v in md.items()
                      if k not in KNOWN_INVOICE_METADATA_KEYS and v is not None}
    existing_custom = get_custom_metadata(invoice) or {}
    if existing_custom != desired_custom:
        return False

    # Q-015: auto_apply_credit flag must match the book's effective state.
    desired_auto = not _is_falsy(str(md.get('auto_apply_credit', 'false')))
    if desired_auto != _record_consumed_credit(invoice):
        return False

    entry_dirs = [c for c in directive.children if c.type == DirectiveType.INVOICE_ENTRY]
    existing_entries = list(invoice.GetEntries())
    if len(existing_entries) != len(entry_dirs):
        return False
    for entry, ed in zip(existing_entries, entry_dirs):
        if not _entry_matches_invoice_directive(entry, ed):
            return False

    posted_dirs = [c for c in directive.children if c.type == DirectiveType.POSTED]
    has_posted_none = md.get('posted') == 'none'
    is_posted = invoice.GetPostedTxn() is not None
    if has_posted_none and is_posted:
        return False
    if posted_dirs and not is_posted:
        return False
    return not (posted_dirs and is_posted and not _posted_matches_directive(invoice, posted_dirs[0], 'ar_account'))


def _invoice_matches_directive(invoice, directive: 'PlaintextDirective', book) -> bool:
    """Return True iff an existing customer invoice equals the directive (Q-010).

    Compared fields: date_opened, billing_id, notes, custom KVP, entries
    (positional, by field), the posted block (or absence thereof), and
    payments (count + per-payment fields). Mismatch on ANY field returns
    False so the importer falls through to the rebuild + repost path.
    """
    if not _invoice_non_payment_matches(invoice, directive):
        return False
    payment_dirs = [c for c in directive.children if c.type == DirectiveType.PAYMENT]
    return _payments_match_directive(invoice, payment_dirs)


def _is_only_added_payment_diff_invoice(invoice, directive):
    """Q-015 classifier for customer invoices.

    Return (True, added_directives) iff the only difference between the
    existing posted invoice and the directive is that the directive
    appends additional `payment:` blocks at the tail (entries + posted +
    metadata all match; the existing payments are a prefix-equal subset
    of the directive's payments).

    When True, the caller can apply just the additional payments via
    `ApplyPayment` on the still-posted invoice — no Unpost, no rebuild,
    posting/entry/existing-payment GUIDs preserved.

    Return (False, []) for any other shape — falls through to the
    destructive rebuild path the test suite already covers.
    """
    if invoice.GetPostedTxn() is None:
        return False, []
    if not _invoice_non_payment_matches(invoice, directive):
        return False, []
    payment_dirs = [c for c in directive.children if c.type == DirectiveType.PAYMENT]
    return _payments_only_added_diff(invoice, payment_dirs)


def _is_only_unpost_diff(invoice_or_bill, directive: 'PlaintextDirective',
                         is_bill: bool) -> bool:
    """Return True iff the *only* difference between the existing record and
    the directive is that existing is posted and the directive says
    `posted: none` — entries, payments, and the rest of the metadata are
    otherwise identical.

    When this holds, the importer can call `Unpost(False)` and stop, instead
    of running the full destroy-and-rebuild path. The win:
    **entry GUIDs are preserved**. A cross-tool external reference to an
    entry by GUID still resolves after the re-import; with the rebuild path
    the entry is destroyed and a brand-new one created.

    Strictly defensive: if the directive has any `posted:` block (rather
    than `posted: none`), or has any other field difference, returns False
    and the caller falls through to the full unpost-rebuild-repost path.
    """
    md = directive.metadata
    is_posted = invoice_or_bill.GetPostedTxn() is not None
    if not is_posted:
        return False
    if md.get('posted') != 'none':
        return False
    posted_dirs = [c for c in directive.children if c.type == DirectiveType.POSTED]
    if posted_dirs:
        return False
    payment_dirs = [c for c in directive.children if c.type == DirectiveType.PAYMENT]
    if payment_dirs:
        # Directive declares payments but invoice will be unposted — invalid
        # combination caught later as a real error; here we just refuse the
        # short-circuit and let the normal flow surface the validation.
        return False

    # Compare every non-posted field: entries, date_opened, billing_id (inv
    # only), notes, custom KVP. We skip the actual posted/payment portion of
    # the comparison since we already know those differ in the expected way.
    if invoice_or_bill.GetDateOpened().strftime("%Y-%m-%d") != md['date_opened']:
        return False
    if not is_bill and invoice_or_bill.GetBillingID() != md.get('billing_id', ''):
        return False
    if invoice_or_bill.GetNotes() != md.get('notes', ''):
        return False
    known_keys = KNOWN_BILL_METADATA_KEYS if is_bill else KNOWN_INVOICE_METADATA_KEYS
    desired_custom = {k: v for k, v in md.items()
                      if k not in known_keys and v is not None}
    existing_custom = get_custom_metadata(invoice_or_bill) or {}
    if existing_custom != desired_custom:
        return False

    entry_type = DirectiveType.BILL_ENTRY if is_bill else DirectiveType.INVOICE_ENTRY
    entry_dirs = [c for c in directive.children if c.type == entry_type]
    existing_entries = list(invoice_or_bill.GetEntries())
    if len(existing_entries) != len(entry_dirs):
        return False
    matcher = _entry_matches_bill_directive if is_bill else _entry_matches_invoice_directive
    return all(matcher(entry, ed) for entry, ed in zip(existing_entries, entry_dirs))


def _bill_non_payment_matches(bill, directive: 'PlaintextDirective') -> bool:
    """Bill-side counterpart of `_invoice_non_payment_matches` — same
    shape, uses the bill entry getters and AP account."""
    md = directive.metadata
    if bill.GetDateOpened().strftime("%Y-%m-%d") != md['date_opened']:
        return False
    if bill.GetNotes() != md.get('notes', ''):
        return False
    desired_custom = {k: v for k, v in md.items()
                      if k not in KNOWN_BILL_METADATA_KEYS and v is not None}
    existing_custom = get_custom_metadata(bill) or {}
    if existing_custom != desired_custom:
        return False

    desired_auto = not _is_falsy(str(md.get('auto_apply_credit', 'false')))
    if desired_auto != _record_consumed_credit(bill):
        return False

    entry_dirs = [c for c in directive.children if c.type == DirectiveType.BILL_ENTRY]
    existing_entries = list(bill.GetEntries())
    if len(existing_entries) != len(entry_dirs):
        return False
    for entry, ed in zip(existing_entries, entry_dirs):
        if not _entry_matches_bill_directive(entry, ed):
            return False

    posted_dirs = [c for c in directive.children if c.type == DirectiveType.POSTED]
    has_posted_none = md.get('posted') == 'none'
    is_posted = bill.GetPostedTxn() is not None
    if has_posted_none and is_posted:
        return False
    if posted_dirs and not is_posted:
        return False
    return not (posted_dirs and is_posted and not _posted_matches_directive(bill, posted_dirs[0], 'ap_account'))


def _bill_matches_directive(bill, directive: 'PlaintextDirective', book) -> bool:
    """Return True iff an existing vendor bill equals the directive (Q-010).

    Same shape as `_invoice_matches_directive` but uses the bill-side
    entry getters and AP account.
    """
    if not _bill_non_payment_matches(bill, directive):
        return False
    payment_dirs = [c for c in directive.children if c.type == DirectiveType.PAYMENT]
    return _payments_match_directive(bill, payment_dirs)


def _is_only_added_payment_diff_bill(bill, directive):
    """Q-015 classifier for vendor bills. Symmetric to
    `_is_only_added_payment_diff_invoice`."""
    if bill.GetPostedTxn() is None:
        return False, []
    if not _bill_non_payment_matches(bill, directive):
        return False, []
    payment_dirs = [c for c in directive.children if c.type == DirectiveType.PAYMENT]
    return _payments_only_added_diff(bill, payment_dirs)


class GnuCashImporter:
    """Service for importing plaintext directives to GnuCash"""



    @staticmethod
    def create_commodity(directive: PlaintextDirective, book: Book):
        """
        Create commodity from directive.

        Args:
            directive: PlaintextDirective of type CREATE_COMMODITY
            book: GnuCash book
        """
        if directive.type != DirectiveType.CREATE_COMMODITY:
            raise ValueError(f"Expected CREATE_COMMODITY but got {directive.type}")

        mnemonic = directive.metadata['mnemonic']
        fullname = directive.metadata['fullname']
        namespace = directive.metadata['namespace']
        fraction = int(directive.metadata['fraction'])

        commodity_table = book.get_table()
        commodity = commodity_table.lookup(namespace, mnemonic)
        if commodity is None:
            commodity = GncCommodity(book, fullname, namespace, mnemonic, f'{namespace}.{mnemonic}', fraction)
            commodity_table.insert(commodity)
            logging.debug(f"Created commodity {namespace}.{mnemonic}")
        else:
            # Honor the user's declared fraction even when the commodity is
            # already in the book. This matters for non-CURRENCY commodities
            # the user has fully under their control (stocks, points, custom
            # units) and for re-imports that adjust the fraction. For ISO
            # 4217 CURRENCY commodities, GnuCash 5.15+ subsequently
            # normalises the fraction back to its ISO value on save (e.g.
            # KRW → 1) — that is upstream behaviour, not ours; the in-memory
            # value still matches the user during the import session.
            if commodity.get_fraction() != fraction:
                commodity.set_fraction(fraction)
            logging.debug(f"Commodity {namespace}.{mnemonic} already exists")

    @staticmethod
    def create_account(directive: PlaintextDirective, book: Book):
        """
        Create account from directive.

        Args:
            directive: PlaintextDirective of type OPEN_ACCOUNT
            book: GnuCash book
        """
        if directive.type != DirectiveType.OPEN_ACCOUNT:
            raise ValueError(f"Expected OPEN_ACCOUNT but got {directive.type}")

        root_account = book.get_root_account()
        account = Account(book)
        account_fullname = directive.props['account']
        account_type_str = directive.metadata['type']
        account_names = account_fullname.split(':')
        account_name = account_names[-1]
        parent_account_names = account_names[0:-1]

        commodity_table = book.get_table()

        placeholder = directive.metadata.get('placeholder', False)
        code = directive.metadata.get('code', "")
        description = directive.metadata.get('description', "")
        tax_related = directive.metadata.get('tax_related', False)
        namespace = directive.metadata['commodity.namespace']
        mnemonic = directive.metadata['commodity.mnemonic']

        commodity = commodity_table.lookup(namespace, mnemonic)
        if commodity is None:
            raise Exception(f'Cannot find commodity ({namespace}, {mnemonic}) '
                          f'when trying to create account {account_fullname}')
        account.SetCommodity(commodity)

        parent = root_account
        for name in parent_account_names:
            parent = parent.lookup_by_name(name)
            if parent is None:
                raise Exception(f'Cannot find parent account {name} of {account_fullname}')

        # Idempotency check: skip if an account with this name already exists
        # under the same parent.  create_account may be called twice for the
        # same file (once from import_cmd pre-pass, once from ImportTransactionsUseCase).
        if parent.lookup_by_name(account_name) is not None:
            logging.debug(f"Account {account_fullname} already exists, skipping")
            return

        parent.append_child(account)
        account.SetName(account_name)
        account.SetType(ACCT_TYPE_MAP[account_type_str])
        account.SetPlaceholder(placeholder)
        account.SetCode(code)
        account.SetDescription(description)
        account.SetTaxRelated(tax_related)

        # Preserve the account's GUID across export → import, like the
        # transaction/split/business-object paths already do. The exporter
        # emits `guid:` on every `open` directive for external cross-reference;
        # without honouring it the importer would mint a fresh GUID, so account
        # GUIDs would drift on every roundtrip. Only applies to a freshly
        # created account (existing ones return above).
        declared_guid = directive.metadata.get('guid')
        if declared_guid:
            _set_object_guid(book, account, 'account', account_fullname,
                             _normalise_guid(declared_guid))

        custom_meta = {k: v for k, v in directive.metadata.items()
                       if k not in KNOWN_ACCOUNT_METADATA_KEYS and v is not None}
        if custom_meta:
            set_custom_metadata(account, custom_meta)

        if 'commodity_scu' in directive.metadata:
            commodity_scu = directive.metadata['commodity_scu']
            account.SetCommoditySCU(commodity_scu)

        logging.debug(f"Created account {account_fullname}")

    @staticmethod
    def create_transaction(directive: PlaintextDirective, book: Book) -> 'Transaction':
        """
        Create transaction from directive.

        Args:
            directive: PlaintextDirective of type TRANSACTION
            book: GnuCash book

        Returns:
            The newly created GnuCash Transaction object (after CommitEdit).
            Raises on any error (e.g. missing account) — never returns None.
        """
        if directive.type != DirectiveType.TRANSACTION:
            raise ValueError(f"Expected TRANSACTION but got {directive.type}")

        root_account = book.get_root_account()
        transaction = Transaction(book)
        transaction.BeginEdit()

        commodity_table = book.get_table()

        # Get transaction currency
        namespace = directive.metadata.get('currency.namespace', 'CURRENCY')
        if 'currency.mnemonic' in directive.metadata:
            mnemonic = directive.metadata['currency.mnemonic']
            commodity = commodity_table.lookup(namespace, mnemonic)
        else:
            # Get currency from first split account
            split_directive: PlaintextDirective = directive.children[0]
            split_account_name = split_directive.props['account']
            split_account = find_account(root_account, split_account_name)
            if split_account is None:
                raise Exception(f'Account {split_account_name!r} not found '
                              f'when trying to determine currency for transaction {directive.line}')
            commodity = split_account.GetCommodity()
            mnemonic = commodity.get_mnemonic()

        if commodity is None:
            raise Exception(f'Cannot find commodity ({namespace}, {mnemonic}) '
                          f'when trying to create transaction {directive.line}')
        transaction.SetCurrency(commodity)

        date_str = directive.props['date']
        tx_num = directive.props['tx_num']
        tx_desc = directive.props['tx_desc']

        if tx_num is not None:
            transaction.SetNum(tx_num)
        if tx_desc is not None:
            transaction.SetDescription(tx_desc)

        if 'doc_link' in directive.metadata:
            doc_link = directive.metadata['doc_link']
            # SetAssociation was renamed to SetDocLink in GnuCash 4.x
            try:
                transaction.SetDocLink(doc_link)
            except AttributeError:
                # Fall back to older GnuCash API (< 4.0)
                transaction.SetAssociation(doc_link)

        if 'notes' in directive.metadata:
            notes = directive.metadata['notes']
            transaction.SetNotes(notes)

        transaction.SetDateEnteredSecs(datetime.now())
        date = datetime.strptime(date_str, '%Y-%m-%d')
        transaction.SetDatePostedSecsNormalized(date)

        # Create splits
        for child in directive.children:
            split_directive: PlaintextDirective = child
            split_account_str = split_directive.props['account']
            split_account = find_account(root_account, split_account_str)

            if split_account is None:
                raise Exception(f'Account {split_account_str!r} not found '
                              f'when trying to create transaction split {directive.line}')

            split_account_currency = split_account.GetCommodity()

            split_amount_str = split_directive.props['amount']
            amount = string_to_gnc_numeric(split_amount_str, split_account_currency)

            split = Split(book)
            split.SetParent(transaction)
            split.SetAccount(split_account)
            split.SetAmount(amount)

            if 'share_price' in split_directive.metadata:
                share_price = string_to_gnc_numeric(split_directive.metadata['share_price'], commodity)
                split.SetSharePrice(share_price)

            if 'value' in split_directive.metadata:
                value_str = split_directive.metadata['value']
                value = string_to_gnc_numeric(value_str, commodity)
                split.SetValue(value)
            else:
                split.SetValue(amount)

            if 'action' in split_directive.metadata:
                action = split_directive.metadata['action']
                if action is not None:
                    split.SetAction(action)

            if 'memo' in split_directive.metadata:
                memo = split_directive.metadata['memo']
                if memo is not None:
                    split.SetMemo(memo)

            # Q-016: a split that declares its own GUID uses `guid:`
            # (the same convention used at the transaction, customer,
            # invoice, vendor, and taxtable level). The previous Q-016
            # prerelease used `split_guid:` here; reject the legacy name
            # loudly rather than let it silently become a custom KVP slot
            # while the split is auto-assigned a fresh GUID.
            if split_directive.metadata.get('split_guid'):
                raise Exception(
                    'split_guid: is no longer accepted on a split — '
                    'rename to guid: (a split identifies itself with '
                    '`guid:`, matching the transaction-level `guid:`)'
                )

            # Q-016: honour declared `guid:` on the split so business-
            # object payment blocks (or any other downstream reference)
            # can look this split up by GUID — critical for the
            # multi-invoice-1-bank-tx case.
            split_declared_guid = split_directive.metadata.get('guid')
            if split_declared_guid:
                try:
                    normalised_split_guid = _normalise_guid(split_declared_guid)
                except Exception:
                    normalised_split_guid = None
                if normalised_split_guid:
                    _set_object_guid(book, split, 'split',
                                     split_account_str, normalised_split_guid)

            # Per-split owner marker `lot_owner: kind:id[:guid]`. An AR/AP split
            # sitting in an owner's business lot (no invoice) carries it. On
            # import we JOIN the owner's open lot this split reduces (a credit
            # clearing — refund / vendor bad debt / customer forfeit, decided by
            # the counter split's account) or CREATE a new lot (an orphan payment
            # reconstructed — restoring the GnuCash txn-type heuristic's 'P' arm
            # of "lot with owner, no invoice" — or a fresh credit origin). The
            # trailing guid, when present, is authoritative: a mismatch is a hard
            # error. Runs before CommitEdit; the lot only needs the split
            # parented + valued, both already done above. See
            # _attach_lot_owner_split / _parse_lot_owner.
            _lot_owner_str = split_directive.metadata.get('lot_owner', '')
            if _lot_owner_str:
                _lo_kind, _lo_id, _lo_guid = _parse_lot_owner(_lot_owner_str)
                if _lo_kind in ('customer', 'vendor') and _lo_id:
                    _attach_lot_owner_split(
                        book, split, split_account, _lo_kind, _lo_id, _lo_guid)

            # Store any non-standard split metadata as KVP slots
            custom_split_meta = {
                k: v for k, v in split_directive.metadata.items()
                if k not in KNOWN_SPLIT_METADATA_KEYS and v is not None
            }
            if custom_split_meta:
                set_custom_metadata(split, custom_split_meta)

        # Store any non-standard metadata as KVP slots
        custom_tx_meta = {
            k: v for k, v in directive.metadata.items()
            if k not in KNOWN_TX_METADATA_KEYS and v is not None
        }
        if custom_tx_meta:
            set_custom_metadata(transaction, custom_tx_meta)

        transaction.CommitEdit()

        # Q-016: honour the declared `guid:` on a standalone tx so a
        # subsequent invoice/bill `payment: txn_guid:` block can find
        # this tx by GUID. Without this, GnuCash auto-assigns a fresh
        # GUID and roundtrip-into-fresh-book is broken.
        declared_guid = directive.metadata.get('guid')
        if declared_guid:
            try:
                guid_norm = _normalise_guid(declared_guid)
            except Exception:
                guid_norm = None
            if guid_norm:
                _set_object_guid(book, transaction, 'transaction',
                                 directive.metadata.get('tx_desc', '<tx>'),
                                 guid_norm)

        logging.debug(f"Created transaction on {date_str}")
        return transaction

    @staticmethod
    def update_transaction(existing_tx, directive: PlaintextDirective, book: Book) -> None:
        """
        Update an existing GnuCash transaction in-place from a plaintext directive.

        The transaction's GUID is preserved — the transaction object is modified,
        not replaced. This makes the export→edit-plaintext→re-import cycle stable
        across multiple runs: the same GUID is always present, so subsequent imports
        with UPDATE strategy will keep updating the same transaction instead of
        creating duplicates.

        All scalar fields (description, date, num, doc_link, notes, currency) and
        splits are updated to match the directive. Split matching is by account
        full-name. Splits for accounts absent from the directive are removed; splits
        for new accounts are created.

        Note: When two splits in the directive share the same account (e.g. meal + tip
        both on Expenses:Dining), all of them are applied positionally — each directive
        entry is matched to the corresponding existing split at the same index for that
        account. Extra existing splits are removed; extra desired splits are created.

        Args:
            existing_tx: GnuCash Transaction object to update
            directive:   PlaintextDirective of type TRANSACTION containing new values
            book:        GnuCash Book (required to create new Split objects)

        Raises:
            ValueError: If a split account named in the directive cannot be found
        """
        if directive.type != DirectiveType.TRANSACTION:
            raise ValueError(f"Expected TRANSACTION but got {directive.type}")

        root_account = book.get_root_account()
        commodity_table = book.get_table()

        existing_tx.BeginEdit()
        try:
            # Update transaction-level scalar fields
            date_str = directive.props['date']
            date = datetime.strptime(date_str, '%Y-%m-%d')
            existing_tx.SetDatePostedSecsNormalized(date)

            tx_num = directive.props.get('tx_num')
            tx_desc = directive.props.get('tx_desc')
            if tx_num is not None:
                existing_tx.SetNum(tx_num)
            if tx_desc is not None:
                existing_tx.SetDescription(tx_desc)

            if 'doc_link' in directive.metadata:
                try:
                    existing_tx.SetDocLink(directive.metadata['doc_link'])
                except AttributeError:
                    existing_tx.SetAssociation(directive.metadata['doc_link'])

            if 'notes' in directive.metadata:
                existing_tx.SetNotes(directive.metadata['notes'])

            # Update currency if specified
            namespace = directive.metadata.get('currency.namespace', 'CURRENCY')
            if 'currency.mnemonic' in directive.metadata:
                mnemonic = directive.metadata['currency.mnemonic']
                commodity = commodity_table.lookup(namespace, mnemonic)
                if commodity is not None:
                    existing_tx.SetCurrency(commodity)

            # Update transaction-level custom metadata (merge: new values win)
            custom_tx_meta = {
                k: v for k, v in directive.metadata.items()
                if k not in KNOWN_TX_METADATA_KEYS and v is not None
            }
            if custom_tx_meta:
                existing_custom = get_custom_metadata(existing_tx)
                existing_custom.update(custom_tx_meta)
                set_custom_metadata(existing_tx, existing_custom)

            tx_currency = existing_tx.GetCurrency()

            # Build account-name → [splits] map for existing splits.
            # Using lists preserves multiple splits that share the same account
            # (e.g. meal + tip both posted to Expenses:Dining).
            existing_splits_by_account: dict[str, list] = {}
            for split in existing_tx.GetSplitList():
                acct_name = get_account_full_name(split.GetAccount())
                existing_splits_by_account.setdefault(acct_name, []).append(split)

            # Build account-name → [directives] map for desired splits.
            desired_by_account: dict[str, list] = {}
            for child in directive.children:
                desired_by_account.setdefault(child.props['account'], []).append(child)

            # Validate all desired accounts exist before making any changes
            for acct_name in desired_by_account:
                if find_account(root_account, acct_name) is None:
                    raise ValueError(f"Account not found: {acct_name}")

            # Remove splits for accounts no longer in the directive
            for acct_name, splits in list(existing_splits_by_account.items()):
                if acct_name not in desired_by_account:
                    for split in splits:
                        split.Destroy()

            # Update existing splits or create new ones, matched positionally
            # within each account group.
            for acct_name, split_directives in desired_by_account.items():
                split_account = find_account(root_account, acct_name)
                split_account_currency = split_account.GetCommodity()
                existing_splits = existing_splits_by_account.get(acct_name, [])

                # Destroy excess existing splits when directive has fewer
                for surplus in existing_splits[len(split_directives):]:
                    surplus.Destroy()

                for i, split_directive in enumerate(split_directives):
                    amount = string_to_gnc_numeric(split_directive.props['amount'], split_account_currency)

                    if 'value' in split_directive.metadata:
                        value = string_to_gnc_numeric(split_directive.metadata['value'], tx_currency)
                    else:
                        value = amount

                    if i < len(existing_splits):
                        split = existing_splits[i]
                    else:
                        split = Split(book)
                        split.SetParent(existing_tx)
                        split.SetAccount(split_account)

                    split.SetAmount(amount)
                    split.SetValue(value)

                    if 'share_price' in split_directive.metadata:
                        share_price = string_to_gnc_numeric(split_directive.metadata['share_price'], tx_currency)
                        split.SetSharePrice(share_price)

                    if 'action' in split_directive.metadata:
                        action = split_directive.metadata['action']
                        if action is not None:
                            split.SetAction(action)

                    if 'memo' in split_directive.metadata:
                        memo = split_directive.metadata['memo']
                        if memo is not None:
                            split.SetMemo(memo)

                    # Update split-level custom metadata (merge: new values win)
                    custom_split_meta = {
                        k: v for k, v in split_directive.metadata.items()
                        if k not in KNOWN_SPLIT_METADATA_KEYS and v is not None
                    }
                    if custom_split_meta:
                        existing_split_custom = get_custom_metadata(split)
                        existing_split_custom.update(custom_split_meta)
                        set_custom_metadata(split, existing_split_custom)

            existing_tx.CommitEdit()
            logging.debug(f"Updated transaction on {date_str}")

        except Exception:
            existing_tx.RollbackEdit()
            raise

    @staticmethod
    def import_company(directive: PlaintextDirective, book: Book):
        """Q-028: write the book-level `company` directive to the Business
        options. The directive is the source of truth for the fields it
        names; only those slots are touched (an absent field is left as-is).
        GST/PST land in the custom `Company GST Number` / `Company PST Number`
        slots; `pst` may carry several numbers in one string (split for
        rendering, stored verbatim).

        Q-029: any key that is not a known Business field or address line is
        kept as book-level custom metadata (e.g. `fiscal_year_end`, `province`,
        `entity_type`) — serialised together as one JSON blob in a dedicated
        book option slot. These round-trip but are not rendered.

        Status compares each field to the book's current value so a no-op
        re-import reports 'unchanged'. 'created' when the book had no company
        options before, else 'updated'."""
        if directive.type != DirectiveType.COMPANY:
            raise ValueError(f"Expected COMPANY but got {directive.type}")
        md = directive.metadata
        changed = False
        had_any = False

        for key, slot in COMPANY_FIELD_TO_SLOT.items():
            if key not in md:
                continue
            val = '' if md[key] is None else str(md[key])
            current = get_book_string_option(book, 'Business', slot) or ''
            if current:
                had_any = True
            if current != val:
                set_book_string_option(book, 'Business', slot, val)
                changed = True

        # Address lines → single multi-line `Company Address` slot, the inverse
        # of the `read_book_company_info` split-on-newline. Only rewritten when
        # the directive names at least one address line.
        if any(k in md for k in _COMPANY_ADDR_KEYS):
            addr_val = '\n'.join(
                ('' if md.get(k) is None else str(md.get(k, '')))
                for k in _COMPANY_ADDR_KEYS
            ).rstrip('\n')
            current = get_book_string_option(book, 'Business', 'Company Address') or ''
            if current:
                had_any = True
            if current != addr_val:
                set_book_string_option(book, 'Business', 'Company Address', addr_val)
                changed = True

        # Q-029 (fixed): any key that is not a known Business field or an address
        # line is book-level custom metadata. The directive is a partial UPSERT,
        # consistent with the known-field tier above and with the documented
        # contract that an absent field is left as-is — keys named here are set,
        # keys NOT named are preserved, and a key given the null value (`#None`)
        # is removed (JSON Merge Patch). It used to replace the whole blob, so a
        # partial company directive silently deleted any custom key it didn't
        # repeat; merge is shared with `set-book-key` so both behave the same.
        known = set(COMPANY_FIELD_TO_SLOT) | set(_COMPANY_ADDR_KEYS)
        custom = {k: v for k, v in md.items() if k not in known}
        if custom:
            if get_book_custom_metadata(book):
                had_any = True
            if merge_book_custom_metadata(book, custom):
                changed = True

        if not changed:
            return 'unchanged'
        return 'updated' if had_any else 'created'

    @staticmethod
    def import_customer(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.CUSTOMER:
            raise ValueError(f"Expected CUSTOMER but got {directive.type}")

        cid = directive.props['id']
        guid_str = directive.metadata.get('guid')
        existing, must_set_guid = _resolve_existing_or_none(
            'customer', cid, guid_str,
            lambda i: _find_customers_by_id(book, i),
            lambda g: _find_customer_by_guid(book, g),
        )

        # Q-010: short-circuit if the existing record is already byte-equal
        # to the directive. Reports 'unchanged' so users see clearly that
        # no mutation was applied (vs 'updated' which implies a write).
        if existing is not None and _customer_matches_directive(existing, directive):
            logging.debug(f"Customer {cid} already matches directive; unchanged")
            return 'unchanged'

        currency = book.get_table().lookup("CURRENCY", directive.metadata['currency'])
        if existing is None:
            customer = Customer(book, cid, currency)
            if must_set_guid is not None:
                _set_object_guid(book, customer, 'customer', cid, must_set_guid)
        else:
            customer = existing

        customer.BeginEdit()
        customer.SetName(directive.metadata['name'])
        addr = customer.GetAddr()
        addr.SetAddr1(directive.metadata.get('addr1', ''))
        addr.SetAddr2(directive.metadata.get('addr2', ''))
        addr.SetAddr3(directive.metadata.get('addr3', ''))
        addr.SetAddr4(directive.metadata.get('addr4', ''))
        addr.SetEmail(directive.metadata.get('email', ''))
        customer.CommitEdit()

        customer.SetActive(not _is_falsy(directive.metadata.get('active', 'true')))

        custom_meta = {k: v for k, v in directive.metadata.items()
                       if k not in KNOWN_CUSTOMER_METADATA_KEYS and v is not None}
        if custom_meta:
            set_custom_metadata(customer, custom_meta)
        logging.debug(f"{'Updated' if existing else 'Created'} customer {cid}")
        return 'updated' if existing else 'created'

    @staticmethod
    def import_vendor(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.VENDOR:
            raise ValueError(f"Expected VENDOR but got {directive.type}")

        vid = directive.props['id']
        guid_str = directive.metadata.get('guid')
        existing, must_set_guid = _resolve_existing_or_none(
            'vendor', vid, guid_str,
            lambda i: _find_vendors_by_id(book, i),
            lambda g: _find_vendor_by_guid(book, g),
        )

        # Q-010: short-circuit when existing matches directive byte-for-byte.
        if existing is not None and _vendor_matches_directive(existing, directive):
            logging.debug(f"Vendor {vid} already matches directive; unchanged")
            return 'unchanged'

        currency = book.get_table().lookup("CURRENCY", directive.metadata['currency'])
        if existing is None:
            vendor = Vendor(book, vid, currency)
            if must_set_guid is not None:
                _set_object_guid(book, vendor, 'vendor', vid, must_set_guid)
        else:
            vendor = existing

        vendor.BeginEdit()
        vendor.SetName(directive.metadata['name'])
        vendor.CommitEdit()

        vendor.SetActive(not _is_falsy(directive.metadata.get('active', 'true')))

        custom_meta = {k: v for k, v in directive.metadata.items()
                       if k not in KNOWN_VENDOR_METADATA_KEYS and v is not None}
        if custom_meta:
            set_custom_metadata(vendor, custom_meta)
        logging.debug(f"{'Updated' if existing else 'Created'} vendor {vid}")
        return 'updated' if existing else 'created'

    @staticmethod
    def import_taxtable(directive: PlaintextDirective, book: Book):
        if directive.type != DirectiveType.TAXTABLE:
            raise ValueError(f"Expected TAXTABLE but got {directive.type}")

        tt_name = directive.props['name']

        # Resolve identity (Q-008): apply id ⇔ guid agreement rules and
        # detect pre-existing duplicates. On a hit we SKIP rather than
        # update — tax tables are referenced by stored pointers from posted
        # invoices/bills, and mutating their entries would silently change
        # accounting on past posted invoices.
        existing, must_set_guid = _resolve_existing_or_none(
            'taxtable', tt_name, directive.metadata.get('guid'),
            lambda n: _find_taxtables_by_name(book, n),
            lambda g: _find_taxtable_by_guid(book, g),
            get_guid_str=_taxtable_guid_str,
            get_id_str=_taxtable_name_str,
        )
        if existing is not None:
            logging.debug(f"Tax table {tt_name!r} already exists, skipping")
            return 'skipped'

        first_entry_directive = None
        for d in directive.children:
            if d.type == DirectiveType.TAXTABLE_ENTRY:
                first_entry_directive = d
                break

        if not first_entry_directive:
            # A taxtable must have at least one entry — treat the directive
            # as a skip so the caller doesn't count it as a create.
            return 'skipped'

        acct_name = first_entry_directive.metadata['account']
        account = find_account(book.get_root_account(), acct_name)
        if account is None:
            raise Exception(f'Account {acct_name!r} not found when creating tax table {tt_name}')
        rate_str = first_entry_directive.metadata['rate']
        rate = float(rate_str.replace("%", ""))
        first_entry = create_tax_table_entry(book, account, rate)

        taxtable = TaxTable(book, tt_name, first_entry)
        if must_set_guid is not None:
            _set_object_guid(book, taxtable, 'taxtable', tt_name, must_set_guid)

        for entry_directive in directive.children[1:]:
            if entry_directive.type == DirectiveType.TAXTABLE_ENTRY:
                acct_name = entry_directive.metadata['account']
                account = find_account(book.get_root_account(), acct_name)
                if account is None:
                    raise Exception(f'Account {acct_name!r} not found when creating tax table {tt_name}')
                rate_str = entry_directive.metadata['rate']
                rate = float(rate_str.replace("%", ""))
                entry = create_tax_table_entry(book, account, rate)
                taxtable.AddEntry(entry)

        logging.debug(f"Created taxtable {directive.props['name']}")
        return 'created'

    @staticmethod
    def import_invoice(directive: PlaintextDirective, book: Book,
                       on_orphan_warning=None):
        if directive.type != DirectiveType.INVOICE:
            raise ValueError(f"Expected INVOICE but got {directive.type}")

        inv_id = directive.props['id']

        # Resolve identity (Q-007): id ⇔ guid agreement, duplicate detection.
        existing, must_set_guid = _resolve_existing_or_none(
            'invoice', inv_id, directive.metadata.get('guid'),
            lambda i: _find_invoices_by_id(book, i),
            lambda g: _find_invoice_by_guid(book, g),
            get_guid_str=_swig_invoice_guid_str,
        )

        # Validate: posted: none and a real posted: block are contradictory
        has_posted_none = directive.metadata.get('posted') == 'none'
        posted_children = [c for c in directive.children if c.type == DirectiveType.POSTED]
        if has_posted_none and posted_children:
            raise ValueError(f'Invoice {inv_id}: contradictory "posted: none" and posted: block')
        if len(posted_children) > 1:
            raise ValueError(f'Invoice {inv_id}: multiple posted: blocks are not allowed')

        # Validate: payment: none and a real payment: block are contradictory;
        # also, an unposted invoice cannot have payments
        has_payment_none = directive.metadata.get('payment') == 'none'
        payment_children = [c for c in directive.children if c.type == DirectiveType.PAYMENT]
        if has_payment_none and payment_children:
            raise ValueError(f'Invoice {inv_id}: contradictory "payment: none" and payment: block')
        if has_posted_none and payment_children:
            raise ValueError(f'Invoice {inv_id}: cannot have payment: blocks on an unposted invoice (posted: none)')

        # Q-010 / Q-015: classify the existing record before any mutation.
        #   - matches directive byte-for-byte → 'unchanged' (no-op)
        #   - only difference is `posted → posted: none` → minimal Unpost,
        #     skip the destroy-and-rebuild (preserves entry GUIDs)
        #   - only difference is the directive appends payment(s) at the
        #     tail → apply just those new payments via ApplyPayment on
        #     the still-posted invoice (preserves posting/entry GUIDs and
        #     does NOT orphan existing payment bank txs)
        #   - existing is posted, directive differs in other ways
        #     → full Unpost-rebuild-repost cycle (mirrors GnuCash UI)
        #   - existing is unposted → fall through to rebuild
        # Q-007's old behaviour ("posted is immutable, return skipped")
        # is gone — that left a permanent dead-end that contradicted the
        # GnuCash UI itself.
        status_on_success = 'created'
        if existing is not None:
            if _invoice_matches_directive(existing, directive, book):
                logging.debug(f"Invoice {inv_id} already matches directive; unchanged")
                return 'unchanged'
            if _is_only_unpost_diff(existing, directive, is_bill=False):
                logging.debug(
                    f"Invoice {inv_id}: only difference is posted→posted:none; "
                    f"minimal unpost (entry GUIDs preserved)"
                )
                _emit_orphan_warning_before_unpost(
                    existing, 'invoice', inv_id, on_orphan_warning)
                existing.Unpost(False)
                return 'updated'
            added, added_pays = _is_only_added_payment_diff_invoice(existing, directive)
            if added:
                logging.debug(
                    f"Invoice {inv_id}: only difference is +{len(added_pays)} "
                    f"appended payment(s); applying incrementally (posting/entry/"
                    f"existing-payment GUIDs preserved)"
                )
                for pay_dir in added_pays:
                    _apply_payment_directive(existing, pay_dir, book, is_bill=False)
                return 'updated'
            status_on_success = 'updated'
            if existing.GetPostedTxn() is not None:
                logging.debug(f"Invoice {inv_id} is posted but differs; unposting for rebuild")
                _emit_orphan_warning_before_unpost(
                    existing, 'invoice', inv_id, on_orphan_warning)
                existing.Unpost(False)

        if existing is None:
            customer = _resolve_cross_reference(
                'customer',
                directive.metadata.get('customer_id'),
                directive.metadata.get('customer_guid'),
                lambda i: _find_customers_by_id(book, i),
                lambda g: _find_customer_by_guid(book, g),
            )
            invoice = Invoice(book, inv_id, book.get_table().lookup("CURRENCY", directive.metadata['currency']), customer)
            if must_set_guid is not None:
                _set_object_guid(book, invoice, 'invoice', inv_id, must_set_guid)
        else:
            # Existing invoice (unposted now, after the Unpost above if needed):
            # reuse it, drop its current entries so we can rebuild from the
            # directive. RemoveEntry is essential before Destroy: gncEntryDestroy
            # only sets the do_free flag and drops the entry from the
            # QofCollection — it does NOT detach the entry from the invoice's
            # internal entry list. Without RemoveEntry, `gncInvoicePostToAccount`
            # later iterates a list that still contains the now-dangling pointer
            # and segfaults (reproduced on GnuCash 3.8 / ubuntu20).
            invoice = existing
            for old_entry in list(invoice.GetEntries()):
                invoice.RemoveEntry(old_entry)
                old_entry.Destroy()
        invoice.BeginEdit()
        invoice.SetDateOpened(datetime.strptime(directive.metadata['date_opened'], "%Y-%m-%d"))

        if 'billing_id' in directive.metadata:
            invoice.SetBillingID(directive.metadata['billing_id'])
        if 'notes' in directive.metadata:
            invoice.SetNotes(directive.metadata['notes'])

        entry_index = 0
        for entry_directive in directive.children:
            if entry_directive.type == DirectiveType.INVOICE_ENTRY:
                entry_index += 1
                entry = Entry(book)
                entry.BeginEdit()
                entry.SetDate(datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d"))
                entry.SetDescription(entry_directive.metadata['description'])
                # Q-011: `action` is optional. Omitting the directive line
                # is equivalent to `action: ""` — the entry's action is set
                # to empty. To preserve a non-empty action across re-imports
                # the user must include `action: "<value>"` explicitly; the
                # importer treats each directive as the full source of truth
                # for its fields, not a partial patch.
                entry.SetAction(entry_directive.metadata.get('action', ''))
                inv_acct_name = entry_directive.metadata['account']
                inv_acct = find_account(book.get_root_account(), inv_acct_name)
                if inv_acct is None:
                    raise Exception(f'Account {inv_acct_name!r} not found when creating invoice entry')
                entry.SetInvAccount(inv_acct)
                entry.SetQuantity(string_to_gnc_numeric_quantity(entry_directive.metadata['quantity']))
                entry.SetInvPrice(string_to_gnc_numeric_quantity(entry_directive.metadata['price']))
                entry.SetInvTaxable(entry_directive.metadata['taxable'] == 'true')
                entry.SetInvTaxIncluded(entry_directive.metadata['tax_included'] == 'true')
                if 'tax_table' in entry_directive.metadata:
                    tt_ptr = gc.gncTaxTableLookupByName(book.instance, entry_directive.metadata['tax_table'])
                    if tt_ptr:
                        entry.SetInvTaxTable(TaxTable(instance=tt_ptr))
                invoice.AddEntry(entry)
                entry.CommitEdit()

                # Q-017: validate informational fields against recompute
                # (entry_amount, entry_tax, and any `breakdown:` sub-blocks).
                # Renderer emits these; if a user tampered with the rendered
                # file before re-import, fail loudly here.
                breakdown_declared = [
                    dict(child.metadata.items())
                    for child in entry_directive.children
                    if child.type == DirectiveType.TAX_BREAKDOWN
                ]
                informational = {
                    k: entry_directive.metadata[k]
                    for k in ('entry_amount', 'entry_tax')
                    if k in entry_directive.metadata
                }
                if informational or breakdown_declared:
                    from infrastructure.gnucash.engine import (
                        load_gnc_engine as _load,
                    )
                    from services.invoice_renderer import (
                        validate_entry_informational,
                    )
                    validate_entry_informational(
                        _load(), int(entry.instance),
                        informational, breakdown_declared,
                        entry_label=(
                            f'invoice {directive.props["id"]!r} entry '
                            f'#{entry_index}'
                        ),
                    )
            elif entry_directive.type == DirectiveType.POSTED:
                ar_acct_name = entry_directive.metadata['ar_account']
                ar_account = find_account(book.get_root_account(), ar_acct_name)
                if ar_account is None:
                    raise Exception(f'AR account {ar_acct_name!r} not found when posting invoice {directive.props["id"]}')
                post_date = datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d")
                due_date = datetime.strptime(entry_directive.metadata['due'], "%Y-%m-%d")
                memo = entry_directive.metadata['memo']
                accumulate = entry_directive.metadata['accumulate'] == 'true'

                # If the directive links an existing tx as the posted tx
                # (mirrors Q-016's payment `txn_guid:` linkage), attach
                # it instead of calling PostToAccount — PostToAccount
                # always mints a fresh tx, so calling both would leave
                # the standalone-imported tx orphan with no lot and the
                # AR account double-counted.
                declared_posted_guid = entry_directive.metadata.get('posted_txn_guid')
                linked_tx = None
                if declared_posted_guid:
                    guid_norm = _normalise_guid(declared_posted_guid)
                    linked_tx = _find_transaction_by_guid(book, guid_norm)
                if linked_tx is not None:
                    _attach_existing_tx_as_posted(
                        invoice, linked_tx, ar_account,
                        post_date, due_date, memo, accumulate,
                        book, 'invoice', inv_id,
                    )
                else:
                    invoice.PostToAccount(ar_account, post_date, due_date, memo, accumulate, False)
                    # Override the transaction description GnuCash set automatically,
                    # so the roundtrip preserves the memo field exactly.
                    posting_txn = invoice.GetPostedTxn()
                    if posting_txn:
                        posting_txn.BeginEdit()
                        posting_txn.SetDescription(memo)
                        set_custom_metadata(posting_txn, _BUSINESS_GENERATED_META)
                        posting_txn.CommitEdit()
            elif entry_directive.type == DirectiveType.PAYMENT:
                _apply_payment_directive(invoice, entry_directive, book, is_bill=False)

        # Q-015: auto_apply_credit consumes the customer's open prepayment
        # lots toward this invoice via gncInvoiceAutoApplyPayments. Cash
        # payments above are applied first; auto-apply then fills any
        # remaining balance from existing credit.
        if not _is_falsy(str(directive.metadata.get('auto_apply_credit', 'false'))):
            if invoice.GetPostedTxn() is None:
                raise Exception(
                    f'Invoice {inv_id}: auto_apply_credit requires a posted: '
                    f'block (cannot apply credit to an unposted invoice)'
                )
            invoice.AutoApplyPayments()

        invoice.CommitEdit()

        # Q-017: invoice-level informational totals. Recompute by summing
        # the entries' source-of-truth fields and compare against the
        # declared totals. Renderer emits these; mismatch is an error.
        declared_totals = {
            k: directive.metadata[k]
            for k in ('invoice_subtotal', 'invoice_tax_total', 'invoice_total')
            if k in directive.metadata
        }
        if declared_totals:
            from infrastructure.gnucash.engine import (
                load_gnc_engine as _load,
            )
            from services.invoice_renderer import (
                compute_entry_informational,
                validate_invoice_informational,
            )
            _lib = _load()
            subtotal = 0.0
            tax_total = 0.0
            for raw_entry in invoice.GetEntries():
                amount, tax, _ = compute_entry_informational(
                    _lib, int(raw_entry.instance)
                )
                subtotal += amount
                tax_total += tax
            validate_invoice_informational(
                declared_totals, subtotal, tax_total,
                invoice_label=f'invoice {directive.props["id"]!r}',
            )

        custom_meta = {k: v for k, v in directive.metadata.items()
                       if k not in KNOWN_INVOICE_METADATA_KEYS and v is not None}
        if custom_meta:
            set_custom_metadata(invoice, custom_meta)
        logging.debug(
            f"{'Updated' if status_on_success == 'updated' else 'Created'} "
            f"invoice {directive.props['id']}"
        )
        return status_on_success

    @staticmethod
    def import_bill(directive: PlaintextDirective, book: Book,
                    on_orphan_warning=None):
        if directive.type != DirectiveType.BILL:
            raise ValueError(f"Expected BILL but got {directive.type}")

        bill_id = directive.props['id']

        # Resolve identity (Q-007): id ⇔ guid agreement, duplicate detection.
        # `book.InvoiceLookupByID` is unsuitable here: it returns None for
        # vendor bills (only customer invoices), so we use a Query filtered
        # by owner-type 4 — see _find_bills_by_id.
        existing, must_set_guid = _resolve_existing_or_none(
            'bill', bill_id, directive.metadata.get('guid'),
            lambda i: _find_bills_by_id(book, i),
            lambda g: _find_bill_by_guid(book, g),
            get_guid_str=_swig_invoice_guid_str,
        )

        # Validate: posted: none and a real posted: block are contradictory
        has_posted_none = directive.metadata.get('posted') == 'none'
        posted_children = [c for c in directive.children if c.type == DirectiveType.POSTED]
        if has_posted_none and posted_children:
            raise ValueError(f'Bill {bill_id}: contradictory "posted: none" and posted: block')
        if len(posted_children) > 1:
            raise ValueError(f'Bill {bill_id}: multiple posted: blocks are not allowed')

        # Validate: payment: none and a real payment: block are contradictory;
        # also, an unposted bill cannot have payments
        has_payment_none = directive.metadata.get('payment') == 'none'
        payment_children = [c for c in directive.children if c.type == DirectiveType.PAYMENT]
        if has_payment_none and payment_children:
            raise ValueError(f'Bill {bill_id}: contradictory "payment: none" and payment: block')
        if has_posted_none and payment_children:
            raise ValueError(f'Bill {bill_id}: cannot have payment: blocks on an unposted bill (posted: none)')

        # Q-010 / Q-015: same classification as import_invoice. Posted
        # bills are mutable via Unpost-edit-repost; identical re-imports
        # are unchanged; bare unpost (posted → posted: none, no other
        # change) skips the destroy-and-rebuild and preserves entry
        # GUIDs; appended payments hit the Q-015 fast path.
        status_on_success = 'created'
        if existing is not None:
            if _bill_matches_directive(existing, directive, book):
                logging.debug(f"Bill {bill_id} already matches directive; unchanged")
                return 'unchanged'
            if _is_only_unpost_diff(existing, directive, is_bill=True):
                logging.debug(
                    f"Bill {bill_id}: only difference is posted→posted:none; "
                    f"minimal unpost (entry GUIDs preserved)"
                )
                _emit_orphan_warning_before_unpost(
                    existing, 'bill', bill_id, on_orphan_warning)
                existing.Unpost(False)
                return 'updated'
            added, added_pays = _is_only_added_payment_diff_bill(existing, directive)
            if added:
                logging.debug(
                    f"Bill {bill_id}: only difference is +{len(added_pays)} "
                    f"appended payment(s); applying incrementally (posting/entry/"
                    f"existing-payment GUIDs preserved)"
                )
                for pay_dir in added_pays:
                    _apply_payment_directive(existing, pay_dir, book, is_bill=True)
                return 'updated'
            status_on_success = 'updated'
            if existing.GetPostedTxn() is not None:
                logging.debug(f"Bill {bill_id} is posted but differs; unposting for rebuild")
                _emit_orphan_warning_before_unpost(
                    existing, 'bill', bill_id, on_orphan_warning)
                existing.Unpost(False)

        if existing is None:
            # Bills are Invoice objects whose owner is a Vendor (no separate Bill class)
            vendor = _resolve_cross_reference(
                'vendor',
                directive.metadata.get('vendor_id'),
                directive.metadata.get('vendor_guid'),
                lambda i: _find_vendors_by_id(book, i),
                lambda g: _find_vendor_by_guid(book, g),
            )
            bill = Invoice(book, bill_id, book.get_table().lookup("CURRENCY", directive.metadata['currency']), vendor)
            if must_set_guid is not None:
                _set_object_guid(book, bill, 'bill', bill_id, must_set_guid)
        else:
            # Existing bill (unposted now, after the Unpost above if needed):
            # reuse it, drop its current entries.
            # NOTE: SWIG `Invoice.RemoveEntry` wraps `gncInvoiceRemoveEntry`
            # which only handles customer invoices. For vendor bills we
            # need `gncBillRemoveEntry` via ctypes — see _bill_remove_entry.
            bill = existing
            _bill_remove_all_entries(book, bill)
        bill.BeginEdit()
        bill.SetDateOpened(datetime.strptime(directive.metadata['date_opened'], "%Y-%m-%d"))

        for entry_directive in directive.children:
            if entry_directive.type == DirectiveType.BILL_ENTRY:
                entry = Entry(book)
                entry.BeginEdit()
                entry.SetDate(datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d"))
                entry.SetDescription(entry_directive.metadata['description'])
                bill_acct_name = entry_directive.metadata['account']
                bill_acct = find_account(book.get_root_account(), bill_acct_name)
                if bill_acct is None:
                    raise Exception(f'Account {bill_acct_name!r} not found when creating bill entry')
                entry.SetBillAccount(bill_acct)
                entry.SetQuantity(string_to_gnc_numeric_quantity(entry_directive.metadata['quantity']))
                entry.SetBillPrice(string_to_gnc_numeric_quantity(entry_directive.metadata['price']))
                entry.SetBillTaxable(entry_directive.metadata['taxable'] == 'true')
                if 'tax_table' in entry_directive.metadata:
                    tt_ptr = gc.gncTaxTableLookupByName(book.instance, entry_directive.metadata['tax_table'])
                    if tt_ptr:
                        entry.SetBillTaxTable(TaxTable(instance=tt_ptr))
                bill.AddEntry(entry)
                entry.CommitEdit()
            elif entry_directive.type == DirectiveType.POSTED:
                ap_acct_name = entry_directive.metadata['ap_account']
                ap_account = find_account(book.get_root_account(), ap_acct_name)
                if ap_account is None:
                    raise Exception(f'AP account {ap_acct_name!r} not found when posting bill {directive.props["id"]}')
                post_date = datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d")
                due_date = datetime.strptime(entry_directive.metadata['due'], "%Y-%m-%d")
                memo = entry_directive.metadata['memo']
                accumulate = entry_directive.metadata['accumulate'] == 'true'

                declared_posted_guid = entry_directive.metadata.get('posted_txn_guid')
                linked_tx = None
                if declared_posted_guid:
                    guid_norm = _normalise_guid(declared_posted_guid)
                    linked_tx = _find_transaction_by_guid(book, guid_norm)
                if linked_tx is not None:
                    _attach_existing_tx_as_posted(
                        bill, linked_tx, ap_account,
                        post_date, due_date, memo, accumulate,
                        book, 'bill', bill_id,
                    )
                else:
                    bill.PostToAccount(ap_account, post_date, due_date, memo, accumulate, False)
                    # Override the transaction description GnuCash set automatically,
                    # so the roundtrip preserves the memo field exactly.
                    posting_txn = bill.GetPostedTxn()
                    if posting_txn:
                        posting_txn.BeginEdit()
                        posting_txn.SetDescription(memo)
                        set_custom_metadata(posting_txn, _BUSINESS_GENERATED_META)
                        posting_txn.CommitEdit()
            elif entry_directive.type == DirectiveType.PAYMENT:
                _apply_payment_directive(bill, entry_directive, book, is_bill=True)

        # Q-015: symmetric to invoice side — consume vendor credit lots.
        if not _is_falsy(str(directive.metadata.get('auto_apply_credit', 'false'))):
            if bill.GetPostedTxn() is None:
                raise Exception(
                    f'Bill {bill_id}: auto_apply_credit requires a posted: '
                    f'block (cannot apply credit to an unposted bill)'
                )
            bill.AutoApplyPayments()

        bill.CommitEdit()
        custom_meta = {k: v for k, v in directive.metadata.items()
                       if k not in KNOWN_BILL_METADATA_KEYS and v is not None}
        if custom_meta:
            set_custom_metadata(bill, custom_meta)
        logging.debug(
            f"{'Updated' if status_on_success == 'updated' else 'Created'} "
            f"bill {directive.props['id']}"
        )
        return status_on_success

    def import_business_objects(self, directives: List[PlaintextDirective], book: Book,
                                 on_directive_status=None,
                                 on_orphan_warning=None):
        """Import every business-object directive and report per-record status.

        `on_directive_status(kind, id, status)` is invoked once per directive
        with kind ∈ {'customer','vendor','taxtable','invoice','bill'} and
        status ∈ {'created','updated','unchanged','skipped'} (Q-010).
        Default is no-op for library callers; the CLI passes a callback
        that prints '<kind> "<id>": <status>' lines so the user sees
        activity inline.

        `on_orphan_warning(kind, id, orphans)` is invoked when a re-import
        of a *paid* invoice/bill is about to call `Unpost(False)`
        (Q-015): the helper captures the still-attached payment-class
        transactions before the unpost destroys the lot, and the callback
        gets the list so the CLI can render the same orphan-payment
        warning block that `unpost-invoices` / `unpost-bills` emit.
        `orphans` is a `List[OrphanPayment]`.

        Returns a `BusinessObjectImportResult` with per-type counts so the
        caller can render an aggregate summary at the end of the import.
        """
        cb = on_directive_status or (lambda *_: None)
        result = BusinessObjectImportResult()

        # Book-level company identity first — independent of everything else.
        for directive in directives:
            if directive.type == DirectiveType.COMPANY:
                cname = directive.metadata.get('name', '?')
                try:
                    status = self.import_company(directive, book)
                except Exception as e:
                    raise ValueError(f'company "{cname}": {e}') from e
                result.tally('company', status)
                cb('company', cname, status)

        # Customers and vendors first (invoices/bills depend on them)
        for directive in directives:
            if directive.type == DirectiveType.CUSTOMER:
                cid = directive.props.get('id', '?')
                try:
                    status = self.import_customer(directive, book)
                except Exception as e:
                    raise ValueError(f'customer "{cid}": {e}') from e
                result.tally('customer', status)
                cb('customer', cid, status)
            elif directive.type == DirectiveType.VENDOR:
                vid = directive.props.get('id', '?')
                try:
                    status = self.import_vendor(directive, book)
                except Exception as e:
                    raise ValueError(f'vendor "{vid}": {e}') from e
                result.tally('vendor', status)
                cb('vendor', vid, status)

        # Then tax tables
        for directive in directives:
            if directive.type == DirectiveType.TAXTABLE:
                tname = directive.props.get('name', '?')
                try:
                    status = self.import_taxtable(directive, book)
                except Exception as e:
                    raise ValueError(f'taxtable "{tname}": {e}') from e
                result.tally('taxtable', status)
                cb('taxtable', tname, status)

        # Finally, invoices and bills
        for directive in directives:
            if directive.type == DirectiveType.INVOICE:
                iid = directive.props.get('id', '?')
                try:
                    status = self.import_invoice(directive, book,
                                                 on_orphan_warning=on_orphan_warning)
                except Exception as e:
                    raise ValueError(f'invoice "{iid}": {e}') from e
                result.tally('invoice', status)
                cb('invoice', iid, status)
            elif directive.type == DirectiveType.BILL:
                bid = directive.props.get('id', '?')
                try:
                    status = self.import_bill(directive, book,
                                              on_orphan_warning=on_orphan_warning)
                except Exception as e:
                    raise ValueError(f'bill "{bid}": {e}') from e
                result.tally('bill', status)
                cb('bill', bid, status)

        return result
