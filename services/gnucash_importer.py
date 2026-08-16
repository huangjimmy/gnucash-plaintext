"""
Service for importing plaintext directives to GnuCash.

Converts PlaintextDirective objects from the parser into GnuCash objects
(commodities, accounts, transactions) with all metadata preserved.
"""

import ctypes
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Dict, List, Optional

import gnucash.gnucash_core_c as gc
from gnucash import (
    Account,
    Book,
    GncCommodity,
    GncNumeric,
    GncPrice,
    Split,
    Transaction,
)
from gnucash.gnucash_business import Bill, Customer, Entry, Invoice, TaxTable, TaxTableEntry, Vendor
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
    xaccAccountGetTypeStr,
    xaccTransSetIsClosingTxn,
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
    held_value,
    merge_book_custom_metadata,
    set_book_string_option,
    set_custom_metadata,
)
from infrastructure.gnucash.utils import (
    exact_text,
    find_account,
    get_account_full_name,
    money_text,
    numeric_to_fraction,
    to_money,
    transaction_under_construction,
    wrap_invoice_or_bill,
)
from services.foreign_currency import (
    BASE_CURRENCY,
    COST_BASIS_BALANCE_KEY,
    COST_BASIS_COST_KEY,
    COST_BASIS_SPLIT_KEY,
    apply_cost_basis_picks,
    cost_basis_balance_of,
    cost_basis_guid_of,
    cost_basis_metadata,
    cost_of,
    establishes_cost_basis,
    give_back_to_cost_bases,
    has_a_stored_cost_basis_balance,
    lower_cost_basis_balance,
    note_stated_balance,
    open_cost_basis_balance_if_none_is_stored,
    parse_stated_cost,
    record_borrowed_basis,
    record_cost_bases,
    require_cost_basis_unused,
    split_guid,
    total_cost_basis_balance_in,
    write_cost_basis_balance,
)
from services.fx_rates import MissingFxRateError
from services.plaintext_addresses import (
    OWNER_ADDRESS_LINES,
    address_key,
    address_line_index,
    address_lines_beyond,
    address_lines_from,
    is_address_key,
    named_address_lines,
    refuse_an_index_on_a_key_that_has_no_list,
)
from services.plaintext_parser import (
    RESIDUAL_AMOUNT,
    DirectiveType,
    PlaintextDirective,
)

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
    # How the book's dates are to be written, as an `strftime` format.
    #
    # Nested, unlike its neighbours: GnuCash keeps this one at
    # `options/Business/Fancy Date Format/custom`, which is what
    # `gnc:fancy-date-info` reads — `(gnc:book-get-option-value book
    # "Business" '("Fancy Date Format" "custom"))`. The slot name carries the
    # extra level because `set_book_string_option` joins section and name with
    # a slash and `qof_book_set_string_option` splits the whole path, so a
    # name with a slash in it addresses a deeper frame. Measured on 5.10: the
    # saved XML holds the same `Fancy Date Format` → `custom` frames GnuCash's
    # own File → Properties → Business writes.
    #
    # Worth having because the fallback is not a property of the book at all.
    # A book with no format of its own is dated by `qof-date-format-get`, the
    # *application's* preference, which lives in GSettings — so the same
    # invoice printed on two machines came out dated two ways, and no ledger
    # could say otherwise.
    'date_format': 'Fancy Date Format/custom',
}

# The address is written one line per key, indexed — `addr[0]` upwards. See
# `services/plaintext_addresses.py` for why the index is in brackets and what
# the two spellings mean.

# Q-029: any `company` key that is not a known Business field (above) or an
# address line is book-level custom metadata — e.g. `fiscal_year_end`,
# `province`, `entity_type`, `ledger_locale`. GnuCash has no slot for these
# (accounting period is an app preference, not stored in the file), so they are
# kept as our own book metadata under COMPANY_CUSTOM_SECTION/COMPANY_CUSTOM_SLOT
# (one JSON blob; see kvp.py). These keys round-trip but are never rendered on
# an invoice/bill — they are private book data (a customer has no business
# seeing the seller's fiscal year).


def _split_value_fraction(split_directive: 'PlaintextDirective') -> Fraction:
    """A split directive's value in the transaction's currency, as an exact
    Fraction.

    `value:` states it outright and `share_price:` states the rate that
    converts the amount. A split that gives neither is worth its amount — the
    split is in the transaction's own currency, or the two are at par, which
    happens: CAD and USD have traded 1:1.
    """
    if 'value' in split_directive.metadata:
        return Fraction(str(split_directive.metadata['value']))
    amount = Fraction(str(split_directive.props['amount']))
    if 'share_price' in split_directive.metadata:
        return amount * Fraction(str(split_directive.metadata['share_price']))
    return amount


def _money_str(value: Fraction, commodity) -> str:
    """`value` written the way its own currency is written.

    The decimals come from the commodity's smallest unit — two for CAD, none
    for JPY — so a message about a yen amount reads 103 JPY rather than the
    103.00 that a hardcoded two-decimal denominator would produce.
    """
    return money_text(value, commodity.get_fraction())


def _account_money_str(value: Fraction, account) -> str:
    """`value` written the way the account holding it is written.

    An account may be kept finer than its currency — a receivable at a tenth of
    a cent, which this tool round-trips as `commodity_scu:` — and a message
    about a figure on that account has to say what it holds. Written at the
    currency's two places instead, a residual of 20.005 is asked for as
    `prepayment: 20.01`, the reader writes that, and the same import refuses it
    for not matching 20.005 — quoting the expected figure through the same
    formatter, so the refusal reads "declared `prepayment: 20.01` does not
    match the computed residual 20.01" and names no figure that would work.

    Used for every figure a message invites the reader to copy into a file.
    `_money_str` remains for amounts a *currency* owns rather than an account.
    """
    commodity = account.GetCommodity() if account is not None else None
    unit = (account.GetCommoditySCU() if account is not None else None)
    if not unit:
        unit = commodity.get_fraction() if commodity is not None else 100
    return money_text(value, unit)


def _resolve_residual(directive: PlaintextDirective, tx_currency, root_account) -> str:
    """The amount a `$residual$` split takes: whatever the other splits of the
    transaction leave over, in the transaction's currency.

    This is the arithmetic the transaction already determines — an FX gain or
    loss is the difference between what a currency cost and what it realized —
    so requiring the user to compute it by hand would be inviting a misstated
    tax figure. At most one residual per transaction, since two cannot be
    resolved; asking for one where the splits already balance is an error
    rather than a silent zero.
    """
    residual_children = [
        child for child in directive.children
        if child.type == DirectiveType.SPLIT
        and str(child.props.get('amount', '')) == RESIDUAL_AMOUNT
    ]
    if not residual_children:
        return None
    if len(residual_children) > 1:
        raise Exception(
            f'{len(residual_children)} splits ask for {RESIDUAL_AMOUNT} — only '
            f'one split per transaction can take the residual, because two '
            f'cannot be resolved')

    residual_child = residual_children[0]
    account_name = residual_child.props['account']
    account = find_account(root_account, account_name)
    if account is None:
        raise Exception(f'Account {account_name!r} not found for the '
                        f'{RESIDUAL_AMOUNT} split')
    account_commodity = account.GetCommodity()
    if account_commodity.get_mnemonic() != tx_currency.get_mnemonic():
        raise Exception(
            f'{RESIDUAL_AMOUNT} on {account_name!r} is a '
            f'{account_commodity.get_mnemonic()} account but the transaction is '
            f'in {tx_currency.get_mnemonic()} — the residual is a '
            f'{tx_currency.get_mnemonic()} figure, and writing it as an amount '
            f'in another currency would invent a 1:1 rate')

    # Sum the other splits as the book will hold them, not as the file's
    # arithmetic leaves them. A split's value can carry more decimals than its
    # currency has — `amount × share_price` is a multiplication, and 45.00 at
    # 1.405 is 63.225 — but GnuCash rounds that product to the currency's
    # smallest unit when it stores the value. Summing the unrounded products
    # instead hands the residual a half cent that exists nowhere in the book,
    # and the residual is then either refused or booked into an imbalance.
    #
    # Rounded first, the residual is a sum and a difference of figures the
    # currency can hold, so it is exact by construction: addition and
    # subtraction cannot introduce a decimal that neither operand had.
    tx_scu = tx_currency.get_fraction()
    others = Fraction(0)
    for child in directive.children:
        if child is residual_child or child.type != DirectiveType.SPLIT:
            continue
        others += numeric_to_fraction(
            to_money(_split_value_fraction(child), tx_scu))
    if others == 0:
        raise Exception(
            f'{RESIDUAL_AMOUNT} on {account_name!r} has nothing to take — the '
            f'other splits already balance')
    residual = -others
    return f'{residual.numerator}/{residual.denominator}'


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
    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    out = []
    for r in q.run():
        inv = wrap_invoice_or_bill(r)
        if inv.GetOwnerType() == _GNC_OWNER_CUSTOMER and inv.GetID() == id_:
            out.append(inv)
    q.destroy()
    return out


def _find_bills_by_id(book, id_: str):
    """All vendor bills with the given id."""
    from gnucash import Query
    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    out = []
    for r in q.run():
        inv = wrap_invoice_or_bill(r)
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
        inv = wrap_invoice_or_bill(r)
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
        inv = wrap_invoice_or_bill(r)
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


def _retarget_counter_split_to_lot(lib, existing_tx, counter_split,
                                   ar_ap_account, lot) -> None:
    """
    Modify existing_tx in-place: retarget `counter_split` — the split whose
    account is not the bank account — to ar_ap_account, and link it to the
    invoice/bill lot.

    This closes the lot without calling ApplyPayment(), preserving all
    original transaction metadata (notes, description, split memos, KVP).

    xaccSplitSetAccount has a SWIG const-type mismatch — ctypes is required.
    See docs/DEBUGGING_GNUCASH_BINDINGS.md.
    """
    existing_tx.BeginEdit()
    lib.xaccSplitSetAccount(int(counter_split.instance),
                            int(ar_ap_account.instance))
    _attach_split_to_lot(counter_split, lot)
    existing_tx.CommitEdit()


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
    the per-split `lot_owner:` KVP.

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
        # Exact: a lot balance is a rational, so "empty" is zero and the sign
        # is the sign — not a float that has to be tested against an epsilon.
        bal_v = numeric_to_fraction(bal) if bal.denom else Fraction(0)
        if bal_v == 0 or (bal_v > 0) == split_positive:
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
            return numeric_to_fraction(b) if b.denom else Fraction(0)
        before = _bal()
        lib.gnc_lot_add_split(best_lot, int(split.instance))
        if _bal() == before:
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
    ref = record.GetOwner()
    buf = ctypes.create_string_buffer(256)
    owner_p = ctypes.cast(buf, ctypes.c_void_p)
    if record.GetOwnerType() == _GNC_OWNER_VENDOR:
        lib.gncOwnerInitVendor(owner_p, int(ref.instance))
    else:
        lib.gncOwnerInitCustomer(owner_p, int(ref.instance))
    lib.gncOwnerAttachToLot(owner_p, lot_ptr)


# Lots this import has put a split into with `xaccSplitSetLot`, which does not
# add it to the lot's own split list — so for these, and only these, that list
# understates what the lot holds until the book is written and read back.
# Cleared at the start of each import by `begin_lot_attachments`.
_LOTS_HOLDING_UNLISTED_SPLITS = set()

# Written on a split left behind by an unpost. Unposting detaches the document
# but leaves the lot on the account holding whatever settled it, so nothing
# about the lot afterwards distinguishes it from an owner's parked credit —
# both are live, documentless and owner-attached (CLAUDE.md finding 10).
#
# On the split and not in memory, because the state it describes is in the
# file: the book is saved with the orphan still sitting in the abandoned lot,
# and the import that re-attaches it may be days later in another process. A
# note that lasted one import would have every later one read the orphan as a
# credit and strip the basis off a settlement the bank really paid.
#
# The value is the guid of the document that was unposted, not just `true`, so
# a rebuild can find the split that used to be its own. On a transaction
# carrying several — a deposit whose portions settled two documents, both since
# unposted — "which of these was mine" is answerable, and only that one is
# taken without the file naming it.
ORPHANED_BY_UNPOST_KEY = 'orphaned_by_unpost'


def begin_lot_attachments() -> None:
    """Forget what the previous import left in this module's run state.

    Called from `ImportTransactionsUseCase.import_from_file`, at the top —
    before the commodity step, which is what records the fraction below, and
    before the hook that imports owners. `execute` does not reset anything.
    The coupling is worth knowing about because it is not visible from either
    side, and the *position* is load-bearing rather than incidental: moved
    after the commodity step, this would clear the pre-restatement fraction
    the moment it was recorded, and a file could widen its way past the amount
    rule again.

    **Anything that creates commodities or applies payments has to come
    through here or through `begin_currency_declarations`.** The three sets
    below are process-wide, and one of them is load-bearing: `holdable_unit`
    reads `_PERSISTED_CURRENCY_FRACTION` to decide what figures a book can
    hold, so a reader that reaches `create_commodity` without a reset judges
    this file's amounts against the *previous* file's restated currency. The
    two entry points are the plaintext import (through this) and the beancount
    import (through the other); a third would have to say which it uses.

    Not a defensive check, because there is nowhere honest to put one — the
    state is legitimately empty on a first run and legitimately full a moment
    later. What keeps it true is that both readers are named here.

    The lot half is deliberately one-directional: forgetting to clear costs an
    account walk for a lot that no longer needs one, since a stale entry only
    sends `_still_owed` down the slower path that is right either way. Never
    clearing it *during* an import is what matters, and nothing does.
    """
    _LOTS_HOLDING_UNLISTED_SPLITS.clear()
    _PAYMENTS_THIS_RUN_MADE.clear()
    _PERSISTED_CURRENCY_FRACTION.clear()


def begin_currency_declarations() -> None:
    """Forget what the previous run's file restated a currency from.

    For readers that create commodities without going through
    `import_from_file` — the beancount import is one — since that is where the
    plaintext path clears it.
    """
    _PERSISTED_CURRENCY_FRACTION.clear()


#: What GnuCash held for an ISO currency before this run's file restated it.
#:
#: A declared `fraction:` is applied so a book carried between two GnuCash
#: versions stays the book it was — the yen and the won are shipped differently
#: across supported distros — but GnuCash writes an ISO currency by code and
#: looks its fraction up again when reading the book back, so a finer one never
#: survives the save. What the *book* will hold is this, and it is what a
#: booked amount has to fit: judged against the restated commodity instead, a
#: file could widen the rule and then write figures the reopened book could not
#: hold, which `export` then refuses with no way back out.
_PERSISTED_CURRENCY_FRACTION: dict = {}


#: Guids of payment transactions this import created. The duplicate-payment
#: refusal asks whether the book *already* holds the movement a block
#: describes, and "already" means before this run: a payment recorded moments
#: ago from an earlier block in the same file is not money the book had, it is
#: money this file is entering. Two installments of one document, same day and
#: same size and same memo, had the second refused against the first — naming
#: a transaction created seconds earlier that appears in no file, and telling
#: the reader to correct a guid to it.
_PAYMENTS_THIS_RUN_MADE: set = set()


def _everything_the_lot_holds(lot, account):
    """Every split the lot holds, including any this import put there.

    The lot's own list answers for everything GnuCash wrote, and is what a
    reader should ask: a receivable carries the whole history of the business,
    and walking its account instead costs a wrapper per split on it.

    But `xaccSplitSetLot` sets a split's lot pointer without appending to that
    list (CLAUDE.md finding 9), so for a lot this import attached to, the list
    is short by what it attached. Those are exactly the lots
    `_attach_split_to_lot` writes down, and only for those is the account
    walked — the splits themselves still say which lot they are in.
    """
    wanted = int(getattr(lot, 'instance', lot))
    if wanted not in _LOTS_HOLDING_UNLISTED_SPLITS or account is None:
        return [Split(instance=raw) for raw in lot.get_split_list()]
    return [split for split in account.GetSplitList()
            if (split_lot := split.GetLot()) is not None
            and int(getattr(split_lot, 'instance', split_lot)) == wanted]


def mark_splits_orphaned_by_unpost(record) -> None:
    """Note, on each split about to be orphaned, that an unpost orphaned it.

    Call immediately *before* `record.Unpost(False)`, while the lot still
    names the document and still lists what settled it. Afterwards neither is
    true: the lot holds no document, and a lot holding no document is what an
    owner's credit looks like.

    What turns on telling them apart is whether moving a split out spends the
    owner's money. Spending a credit takes the cost basis off the split, since
    the currency went with it; doing that to an orphaned settlement takes a
    basis off currency the bank really paid and the book still holds, and the
    export then writes that bank payment as `from_credit:` with no account and
    no date — the money's origin gone from the file.

    The value is this document's guid, so the rebuild that re-imports it can
    pick out the split that was settling *it* rather than one abandoned by
    some other document's unpost.
    """
    lot = record.GetPostedLot()
    if lot is None:
        return
    guid = _swig_invoice_guid_str(record)
    if not guid:
        return
    posting = record.GetPostedTxn()
    if posting is None:
        # Nothing to unpost, so nothing is about to be orphaned. Reached from
        # `_execute_unpost`, which does not check first; the importer's own
        # caller returns before this. Without it the comparison below is
        # `int(...) == None`, false for every split, and the posting's own
        # split gets marked along with the rest — a mark on a split that is
        # about to cease to exist.
        return
    posting_ptr = int(posting.instance)
    # Not the lot's own list: a settlement this same import attached is not on
    # it (finding 9), and that is the one most likely to be orphaned — the file
    # settled the document and then something else about it forced the rebuild.
    for split in _everything_the_lot_holds(lot, record.GetPostedAcc()):
        parent = split.GetParent()
        # The posting's own split goes with the posting, which unposting
        # deletes. Marking it would write to a split about to cease to exist.
        if parent is None or int(parent.instance) == posting_ptr:
            continue
        metadata = dict(get_custom_metadata(split))
        metadata[ORPHANED_BY_UNPOST_KEY] = guid
        parent.BeginEdit()
        set_custom_metadata(split, metadata)
        parent.CommitEdit()


def is_a_bank_paid_orphan(split) -> bool:
    """Whether an unpost left this split loose and no credit ever paid it.

    The one predicate the whole of Q-035's orphan handling turns on, exported
    so that every reader asks it the same way: the three settlement spellings
    here, and in `use_cases/` the two credit listings and
    `find-orphan-payments`. Spelled out separately in each, the copies drifted
    — one read the mark off a neighbouring transaction's splits and reported a
    bank payment's date and account against a credit's balance.

    Marked, and never `applied_from_credit`: a bank paid it, so it is a
    settlement waiting to be put back rather than the owner's money. A marked
    split that *did* come out of credit is credit still, loose again.
    """
    meta = get_custom_metadata(split)
    if not str(meta.get(ORPHANED_BY_UNPOST_KEY, '')).strip():
        return False
    return str(meta.get(APPLIED_FROM_CREDIT_KEY, '')).strip().lower() != 'true'


def _orphaned_from(split) -> str:
    """The guid of the document whose unpost left this split, or ''.

    The guid is what a rebuild matches on to find the settlement that was its
    own (`_retarget_choices`). Everything else asks only whether the key is
    there at all: whether the money is anybody's *credit* turns on how it was
    paid — `_split_came_from_credit` — and not on whose unpost loosened it. A
    bank-paid orphan is a settlement waiting to be put back for every document,
    not only the one it used to settle.
    """
    return str(get_custom_metadata(split).get(ORPHANED_BY_UNPOST_KEY, '')).strip()


def refuse_a_stated_orphan_mark(metadata, where: str) -> None:
    """Refuse a file stating the note an unpost writes for itself.

    The symmetric half of keeping it out of exports. Nothing this tool writes
    puts the key in a file, so a file carrying one is either hand-written or
    from a book edited elsewhere — and either way it asserts something only the
    book can know: that *this* document's unpost left *this* split loose.

    Asked of a transaction's own metadata as well as its splits'. Everything
    that reads the note reads it off a split, so a copy on the transaction
    changes no figure — but it is stored as ordinary metadata and written back
    out, so refusing it on the split alone let the key into a book from a file
    and made the next export produce a file this tool says no file may write.

    Believed, it does the damage the note exists to prevent, twice over. A
    split so marked reads as not an owner's credit, so a settlement genuinely
    spent from a credit keeps a basis for currency it no longer holds. Worse,
    a mark naming the document is preferred over everything else placeable —
    which is how a rebuild finds its own orphan — so a file could pick which of
    an owner's two credits a document spends, past the guard that exists to
    stop split order deciding that. On a foreign book the two carry different
    costs, so it would pick the gain as well.

    Those two blocks and no others, which is what the message says. Stated in
    an account, customer, vendor or invoice block the key is kept as ordinary
    metadata and written back out, and that is consistent rather than broken:
    nothing looks for it there, so it round-trips as the arbitrary text it is.
    A message promising more would send a reader hunting for a refusal they
    are never going to get.
    """
    if ORPHANED_BY_UNPOST_KEY in metadata:
        raise Exception(
            f'{where}: `{ORPHANED_BY_UNPOST_KEY}:` is not a key a file may '
            f'state on a transaction or a split. It is how unposting records '
            f'which document it detached a split from, true of one book and '
            f'only until that document is rebuilt, and no export writes it. '
            f'Remove the line; to say a split is an owner\'s money, name the '
            f'owner with `lot_owner:`.')


def _strip_a_settlements_basis(split) -> None:
    """Take the cost-basis keys off a split that is settling a document.

    A settlement holds no basis: the currency was spent on the document, and
    what the document is owed in is its own posting split's business. The same
    rule `_mark_spent_credit` states for a credit that was applied.
    """
    # Under the current name whichever the book kept it under: a basis written
    # before the rename would otherwise read as one with nothing to strip, and
    # the split would keep a balance it no longer has any claim to.
    metadata = cost_basis_metadata(split)
    if not (COST_BASIS_BALANCE_KEY in metadata
            or COST_BASIS_COST_KEY in metadata):
        return
    remaining = {key: val for key, val in metadata.items()
                 if key not in (COST_BASIS_BALANCE_KEY, COST_BASIS_COST_KEY)}
    transaction = split.GetParent()
    if transaction is None:
        return
    transaction.BeginEdit()
    set_custom_metadata(split, remaining)
    transaction.CommitEdit()


def _carry_the_orphan_mark(guid: str, residue) -> None:
    """Give the residue of a divided orphan the mark its source carried.

    What the source was, the part left over still is: money a bank paid,
    waiting to be put back. The engine's own carve is handled in
    `_carry_basis_across_applied_credit`; this is the division this tool makes
    itself, and the two have to answer alike or the same split gets two
    readings depending on which of them did the dividing.

    Takes the guid rather than the source split, because by the time the
    residue exists the source is in the document's lot and the mark has come
    off it — the caller reads it before dividing.
    """
    if not guid:
        return
    metadata = dict(get_custom_metadata(residue))
    metadata[ORPHANED_BY_UNPOST_KEY] = guid
    transaction = residue.GetParent()
    if transaction is None:
        return
    transaction.BeginEdit()
    set_custom_metadata(residue, metadata)
    transaction.CommitEdit()


def _forget_orphaned_by_unpost(split) -> None:
    """Take the note off a split that is in a lot again.

    Being in a lot is the whole of what makes it no longer an orphan: it is
    settling a document, or it is parked as somebody's credit, and either way
    the unpost that left it loose is answered. Left on, the key would outlive
    what it describes — and a stored key contradicting the book is what half
    this issue is about.
    """
    metadata = get_custom_metadata(split)
    if ORPHANED_BY_UNPOST_KEY not in metadata:
        return
    remaining = {key: val for key, val in metadata.items()
                 if key != ORPHANED_BY_UNPOST_KEY}
    transaction = split.GetParent()
    if transaction is None:
        return
    transaction.BeginEdit()
    set_custom_metadata(split, remaining)
    transaction.CommitEdit()


def _attach_split_to_lot(split, lot) -> None:
    """Put a split in a lot, and record that the lot's own list will not say so.

    The one way this module attaches a split to an existing lot. Not because
    the call needs wrapping — it is a single line — but because the note it
    leaves is what lets every reader of "what does this lot hold" stay cheap:
    without it they must walk the whole account, and a receivable carries the
    whole history of the business.

    A caller that reaches past this and calls `xaccSplitSetLot` itself leaves
    no note, and readers go on believing a lot list that is short by one split.
    `test_c_bindings_are_declared_once.py`'s sibling check refuses that, the
    same way the ctypes ratchet refuses a second declaration.

    It is also where an unpost's note comes off, and for the same reason it is
    where the other note goes on: being in a lot is exactly what stops a split
    being an orphan, so every path that ends one ends here. Clearing it at the
    four call sites instead left two of them — `txn_split_guid:` and the credit
    block — carrying a key that outlived what it described.
    """
    gc.xaccSplitSetLot(split.instance, lot.instance)
    _LOTS_HOLDING_UNLISTED_SPLITS.add(int(getattr(lot, 'instance', lot)))
    _forget_orphaned_by_unpost(split)


def _refuse_if_nothing_owed(owed: Fraction, kind: str, doc_id: str) -> None:
    """Refuse a payment on a document with nothing left to settle.

    Less than nothing counts as nothing: a lot can be past zero already —
    `txn_split_guid:` names a split outright and attaches it without comparing
    it to what is owed — and there is no more for a payment to take there than
    on one settled exactly. Asked before any figure is derived from what is
    owed, because a negative reads as less than nothing everywhere downstream:
    flooring it moves it *up* (`int()` truncates toward zero), so a residual
    computed from it comes out larger than the payment that produced it.
    """
    if owed > 0:
        return
    raise Exception(
        f'{kind} {doc_id}: owes nothing for this payment to settle — what '
        f'is already on it covers it in full. Applying it anyway would '
        f'take its lot past zero, leaving the {kind.lower()} neither '
        f'settled nor open and the money inside its lot where nothing can '
        f'spend it again.')


def _refuse_if_below_the_accounts_unit(owed: Fraction, post_account,
                                       kind: str, doc_id: str) -> Fraction:
    """What a payment can take, refusing when that is nothing. Returns it.

    Asked by both paths that divide a payment, so neither can offer a remedy
    the other then rejects: the bank path used to compute a residual from a
    figure that had floored to nothing, tell the reader to declare the whole
    payment as `prepayment:`, accept that — and then refuse for the sub-unit
    residue at the point of applying it. The two answers now come from one
    place, and the reader is told the real obstacle first.

    Reachable only for a book whose splits are finer than the account they are
    on. A posting and every payment this tool writes are held at the account's
    unit, so what is left between them is a whole number of those units; what
    leaves a finer split behind is a `commodity_scu:` tightened after the fact,
    or a book written by something other than this tool.
    """
    takeable = _takeable_from(owed, post_account)
    if takeable > 0:
        return takeable
    raise Exception(
        f'{kind} {doc_id}: '
        f'{_account_money_str(owed, post_account)} is still owed, '
        f'which is less than the unit this account is kept to, so a '
        f'payment can take nothing from it — settle the last of it '
        f'another way, or give the account a finer `commodity_scu:`')


def _takeable_from(owed: Fraction, post_account) -> Fraction:
    """How much of `owed` a payment can actually take, given its account.

    Floored to the unit the account is kept to, never rounded up: rounding up
    settles more than is owed and takes the lot past zero, where the document
    reads neither settled nor open and the owner's money is inside a lot they
    cannot spend from. What the account cannot hold stays owed.

    One function because two places need the same answer and a difference
    between them is invisible: what a payment applies, and what a `prepayment:`
    on that payment is checked against. Measured with them apart, on a
    receivable kept to the tenth — a document owed 30.05 and a 50.00
    transaction retargeted onto it — the file was made to declare a residual
    of 19.95, passed, and 20.00 was parked. The figure the file asserts and the
    figure the book holds differed by exactly the rounding the assertion exists
    to catch.
    """
    unit = post_account.GetCommoditySCU() or post_account.GetCommodity().get_fraction()
    return Fraction(int(owed * unit), unit)


def _settle_from_one_split(lib, book, record, existing_tx, counter_split,
                           post_account, lot, owed: Fraction, covering: Fraction,
                           kind: str, doc_id: str, from_credit: bool = False) -> None:
    """One split covering more than its document owes: settle, park the rest.

    The shape a payment takes whenever more money arrives than a document is
    owed — a bank transfer that overpays an invoice, and a credit spent on one
    smaller than itself. Both settle the document with exactly what it owes
    and leave the remainder as the owner's credit, in a lot of their own; each
    caller has already found the split that covers it, and hands it over.

    What the document owes is floored to the unit its account is kept to,
    never rounded up: rounding up settles more than is owed and takes the lot
    past zero, where the document reads neither settled nor open and the
    owner's money is inside a lot they cannot spend from. Where less than one
    unit is owed there is nothing to take, and that is said rather than
    written as a split of nothing.

    The credit left behind is currency the book holds and owes back, so it
    opens a basis — and where the money came from decides at what cost. A bank
    transfer states none, so the record's own carried cost prices it; a credit
    already carried one of its own, and what is left of it moves across.
    """
    # Nothing owed and something owed but less than a unit both floor to zero,
    # and they are not the same fault. A finer `commodity_scu:` is the remedy
    # for the second and no remedy at all for the first — told to change the
    # account, a reader whose document is simply paid would be changing it for
    # a reason that has nothing to do with what is wrong.
    _refuse_if_nothing_owed(owed, kind, doc_id)
    applied = _refuse_if_below_the_accounts_unit(owed, post_account, kind, doc_id)

    # Both halves land on the posted account, so both have to be figures it
    # holds — and what is left is a subtraction from `covering`, which is the
    # split's own amount and need not be a whole number of that account's
    # units. Off a bank feed the split being divided is an Imbalance one, so
    # 50.05 can meet a receivable kept to the tenth: 30.10 settles the
    # document and 19.95 is left, which `SetAmount` rounds to 20.00 on its way
    # in. The two halves then sum to 50.10 against the 50.05 that was there,
    # GnuCash answers the difference with an Imbalance split, and the credit
    # parked is not the figure the file asserted.
    #
    # There is no division of such a split that this account can express, so
    # it is refused rather than rounded into one. Moving it whole is
    # untouched: that changes no amount, and a split finer than its account is
    # a state the book already allows.
    unit = post_account.GetCommoditySCU() or post_account.GetCommodity().get_fraction()
    if (covering * unit).denominator != 1:
        raise Exception(
            f'{kind} {doc_id}: the transaction carries '
            f'{_account_money_str(covering, post_account)}, which '
            f'{get_account_full_name(post_account)} cannot hold — its smallest '
            f'unit is {_account_money_str(Fraction(1, unit), post_account)}. '
            f'Dividing it would leave a part this account rounds, so the two '
            f'halves would no longer sum to what the transaction holds. Name '
            f'the split with `txn_split_guid:` to attach it whole, or give the '
            f'account a finer `commodity_scu:`.')

    # Read before the division halves the split it is written on.
    carried = ({key: val for key, val in cost_basis_metadata(counter_split).items()
                if key in (COST_BASIS_BALANCE_KEY, COST_BASIS_COST_KEY)}
               if from_credit else None)

    # Read before the division too, and for the same reason as the basis keys
    # above: dividing puts the split into the document's lot, and being in a
    # lot is exactly what stops it being an orphan — `_attach_split_to_lot`
    # takes the mark off on the way. Asked afterwards, the answer is always no
    # and the branch below is unreachable.
    orphan_guid = _orphaned_from(counter_split) if not from_credit else ''
    was_a_bank_paid_orphan = (not from_credit
                              and is_a_bank_paid_orphan(counter_split))

    residue = _retarget_with_prepayment_split(
        lib, book, record, existing_tx, counter_split, post_account, lot,
        applied)

    if from_credit:
        _carry_basis_to_residue(residue, carried, covering - applied)
        _mark_spent_credit(counter_split)
    elif was_a_bank_paid_orphan:
        # Dividing a settlement an unpost loosened leaves the rest of that
        # settlement, not a credit. The same rule the engine's own carve
        # follows: the mark goes forward, and no basis opens, because a
        # bank-paid orphan carries none — the document it settled holds that on
        # its posting split.
        #
        # Left to the branch below, the residue landed in a fresh owner lot
        # with no mark — listed as a credit, spendable by a `from_credit:`
        # block, exportable as a credit applied with no account and no date —
        # and priced at *this* record's posting rate rather than the rate the
        # money arrived at, which is a gain the customer's money never made.
        _carry_the_orphan_mark(orphan_guid, residue)
    else:
        # The residue is money the book holds and owes back, so it opens a
        # basis — at the cost the record was carried at, since a payment made
        # in the record's own currency states no base-currency figure to
        # derive one from.
        #
        # Written onto the split this returned rather than found by walking
        # the record's lot, which is how the ApplyPayment path finds the
        # splits the engine made. Measured: `xaccSplitSetLot` sets the split's
        # lot pointer but does not add it to that lot's split list in memory,
        # so a retargeted payment is invisible to `gnc_lot_get_split_list`
        # until the book is written and read back. Searched for, it was never
        # found, and a foreign-currency document overpaid by retarget left its
        # residue with no basis at all — the book offering 100.00 USD while
        # its bank held 200.00, and a sale of the rest refused.
        carried_cost = _carried_cost_of(record)
        if carried_cost is not None:
            record_borrowed_basis(residue, carried_cost)


def _carry_basis_to_residue(residue, carried, remainder: Fraction) -> None:
    """Move a divided credit's basis onto the part of it that is left.

    A credit whose basis carries no stored balance keeps none: reading the
    residue's amount as its balance would re-open currency that may be long
    gone, and nothing recorded what was already sold from it.

    What is left of the *balance*, not the size of what is left of the split.
    A credit of 50.00 with 40.00 of it already sold has 10.00 available;
    writing the residue its own 20.00 would re-open 10.00 of basis for
    currency the book no longer holds, and every later sale would be measured
    against it.

    A balance that will not parse moves across as it reads. The key is present
    or this branch would not run, so a figure that does not parse is a broken
    one rather than a missing one, and writing the remainder over it would put
    the largest figure the division could produce onto a basis nobody can
    vouch for, while destroying the very text `--verify-costs` reports.
    `20,00` for `20.00` would come back as a clean bill of health.
    """
    if not carried:
        return
    metadata = dict(get_custom_metadata(residue))
    metadata.update(carried)
    # Opened and committed outright: the division commits before this runs, so
    # the transaction is always closed here and a guard on whether it is open
    # could only ever take one of its two paths.
    transaction = residue.GetParent()
    transaction.BeginEdit()
    set_custom_metadata(residue, metadata)
    transaction.CommitEdit()
    if COST_BASIS_BALANCE_KEY in carried:
        # Asked of the balance itself, not of whether it is malformed: an
        # empty string satisfies "the key is carried" and "it is not
        # malformed" both, while reading back as no balance at all — and
        # `min(None, remainder)` raises part-way through an import. Nothing
        # this tool writes leaves one, but a book another program wrote can.
        was = cost_basis_balance_of(residue)
        if was is not None:
            write_cost_basis_balance(residue, min(was, remainder))


def _mark_spent_credit(split) -> None:
    """Note that this split settled a document out of the owner's credit.

    Written down for the same reason the application that produced the block
    wrote it down: nothing about the split afterwards says it came out of
    credit rather than out of a bank.

    What it carried as a credit comes off. Its basis is gone — the currency
    was spent, and what survived the division took the balance with it — and
    `lot_owner` says a split belongs to an owner's lot, which this one no
    longer does. The export re-derives that line from live lot state, so a
    stale copy is invisible today; a stored key contradicting the book is what
    half this issue is about.
    """
    metadata = {key: val for key, val in cost_basis_metadata(split).items()
                if key not in (COST_BASIS_BALANCE_KEY, COST_BASIS_COST_KEY,
                               'lot_owner')}
    metadata[APPLIED_FROM_CREDIT_KEY] = 'true'
    # As above: both callers reach here with the transaction committed — after
    # a division, or after the whole split was moved into the document's lot.
    transaction = split.GetParent()
    transaction.BeginEdit()
    set_custom_metadata(split, metadata)
    transaction.CommitEdit()


def _retarget_with_prepayment_split(lib, book, record, existing_tx,
                                    counter_split,
                                    post_account, invoice_lot,
                                    invoice_portion: Fraction):
    """Q-015 overpayment-retarget mechanic.

    `counter_split` is for more money than the invoice/bill's remaining
    balance — a bank-side tx that already exists (e.g. imported from QFX) and
    overpays, or a credit named by a `from_credit:` block that is bigger than
    the document. We split it into two:

      * the invoice-portion split: re-account to AR/AP, attach to the
        record's posted lot — closes the lot,
      * the prepayment-portion split (new): account = same AR/AP, attach
        to a freshly created lot on the same account — that lot stays
        open as a customer/vendor credit.

    Only the invoice portion is taken as an argument. What is left is the
    split's own amount less that, derived here rather than passed in: two
    figures for one subtraction is one too many in a money path, and a reader
    would fairly assume the caller's was what got parked.

    Which split covers the document is the caller's to know — the bank path
    finds it as the side that is not the bank, and a `from_credit:` block
    names it by guid — so there is nothing to search for and no way to fail
    to find it.

    Returns the prepayment split it parked. Handing it back saves the caller
    searching the account for it: whatever basis the money carried belongs on
    that split, and it is the one split in the book nothing else can name yet.

    Sign handling: the new prepayment split must match the counter-split's
    sign (same direction on AR/AP). For an invoice overpayment the
    counter-split is negative (e.g. -150 on AR); we split into -100 +
    -50. For a bill the counter-split is positive (+150 on AP) → +100 +
    +50.
    """
    from gnucash import Split

    existing_tx.BeginEdit()

    # Reduce the existing counter-split to the invoice-portion (preserving
    # its sign), retarget it to AR/AP, link it to the invoice lot.
    #
    # The part that settles the document reaches the smallest unit of the
    # account it lands on — hundredths for CAD, whole units for JPY — through
    # GnuCash's own rounding, which sends a half away from zero. Going through
    # a float and Python's `round` instead lands an exact half-cent on the
    # nearest *even* cent and puts the difference into the prepayment credit,
    # where nothing later reconciles it.
    #
    # What is left is the exact difference, not that figure rounded again, so
    # the two halves sum to what was there whatever denominator the split was
    # stored at — an SCU tightened after the fact, or a value written at
    # thousandths. A split whose amount this account cannot express at all is
    # refused before reaching here, by `_settle_from_one_split`.
    post_scu = post_account.GetCommoditySCU() or post_account.GetCommodity().get_fraction()
    whole_amount = abs(numeric_to_fraction(counter_split.GetAmount()))
    invoice_signed = to_money(invoice_portion, post_scu)
    remainder = whole_amount - numeric_to_fraction(invoice_signed)
    prepay_signed = GncNumeric(int(remainder.numerator), int(remainder.denominator))
    if counter_split.GetAmount().negative_p():
        invoice_signed = invoice_signed.neg()
        prepay_signed  = prepay_signed.neg()

    # A value is not an amount wherever the split's commodity is not the
    # transaction's currency: 100.00 USD settled into a CAD book is worth
    # 137.00 CAD, and dividing 40/60 has to divide the value 54.80/82.20 or
    # the transaction stops balancing. The share the amounts take decides it,
    # and what is left takes the difference exactly, so the two halves always
    # sum to what was there.
    whole_value = abs(numeric_to_fraction(counter_split.GetValue()))
    if whole_amount and whole_value != whole_amount:
        currency = existing_tx.GetCurrency()
        value_unit = currency.get_fraction() if currency is not None else post_scu
        taken = numeric_to_fraction(to_money(
            whole_value * abs(numeric_to_fraction(invoice_signed)) / whole_amount,
            value_unit))
        left = whole_value - taken
        invoice_value = to_money(taken, value_unit)
        prepay_value = to_money(left, value_unit)
        if counter_split.GetAmount().negative_p():
            invoice_value = invoice_value.neg()
            prepay_value = prepay_value.neg()
    else:
        invoice_value, prepay_value = invoice_signed, prepay_signed

    counter_split.SetAmount(invoice_signed)
    counter_split.SetValue(invoice_value)
    lib.xaccSplitSetAccount(int(counter_split.instance), int(post_account.instance))
    _attach_split_to_lot(counter_split, invoice_lot)

    # Create the prepayment split on the same tx, on the same AR/AP account,
    # in a brand-new lot on that account.
    new_split = Split(book)
    new_split.SetParent(existing_tx)
    new_split.SetAccount(post_account)
    new_split.SetAmount(prepay_signed)
    new_split.SetValue(prepay_value)
    new_split.SetMemo(counter_split.GetMemo() or '')

    new_lot_ptr = lib.gnc_lot_new(int(book.instance))
    lib.xaccAccountInsertLot(int(post_account.instance), new_lot_ptr)
    lib.gnc_lot_add_split(new_lot_ptr, int(new_split.instance))

    # The residual is the record owner's credit; attach the owner so the lot is
    # owner-attached and visible to the open_prepayment summary / find-prepayments.
    _attach_record_owner_to_lot(lib, record, new_lot_ptr)

    existing_tx.CommitEdit()
    return new_split


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

    # Step 2-3: override description, plant the business_generated KVP in
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
    _attach_split_to_lot(ar_ap_split, lot)
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
    "Other Assets": ACCT_TYPE_ASSET,         # README wording for a plain asset
    "Bank": ACCT_TYPE_BANK,
    "Expense": ACCT_TYPE_EXPENSE,
    "Expenses": ACCT_TYPE_EXPENSE,           # natural plural
    "Income": ACCT_TYPE_INCOME,
    "Equity": ACCT_TYPE_EQUITY,
    "Credit Card": ACCT_TYPE_CREDIT,
    "Liability": ACCT_TYPE_LIABILITY,
    "Mutual Fund": ACCT_TYPE_MUTUAL,
    "Accounts Payable": ACCT_TYPE_PAYABLE,
    "A/Payable": ACCT_TYPE_PAYABLE,          # GnuCash internal short form
    "Payable": ACCT_TYPE_PAYABLE,            # natural form
    "Accounts Receivable": ACCT_TYPE_RECEIVABLE,
    "A/Receivable": ACCT_TYPE_RECEIVABLE,    # GnuCash internal short form
    "Receivable": ACCT_TYPE_RECEIVABLE,      # natural form
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
    # A rate reaches five decimal places through GnuCash's own rounding: `5.375`
    # is 43/8, stored as 537500/100000 rather than whatever the nearest binary
    # float happens to be.
    amount = to_money(Fraction(str(amount_percent)), 100000)
    gncTaxTableEntrySetAmount(raw, amount.instance)
    gncTaxTableEntrySetAccount(raw, account.instance)
    return TaxTableEntry(instance=raw)


def _write_named_address(owner, md: dict) -> None:
    """The address lines the block names, and only those.

    An absent key is not an instruction. This is the convention the
    transaction and split paths have always kept — `if 'notes' in metadata`
    before writing notes — and the owner paths did not: they wrote
    `SetAddr1(md.get('addr1', ''))`, so a block naming only what it was
    correcting emptied everything it did not name. Which is most blocks: a
    person editing a name writes the name, a printed invoice carries a partial
    owner block, an export taken before a field existed has none at all.

    Clearing is still possible and is said rather than implied: `addr[0]: ""`
    is present, and empties.

    A line past the fourth is refused. A `GncAddress` has four fields and no
    fifth, so there is nothing to set it on — and the alternative, which is
    what used to happen to any key the address did not claim, is that it
    becomes custom metadata: round-tripping through the ledger perfectly while
    never reaching the address, so the file says five lines and the printed
    invoice shows four. Only the book's own `company` address is free of the
    limit, its lines being one string rather than four fields.
    """
    addr = owner.GetAddr()
    setters = (addr.SetAddr1, addr.SetAddr2, addr.SetAddr3, addr.SetAddr4)
    for index, value in named_address_lines(md).items():
        if index >= OWNER_ADDRESS_LINES:
            raise ValueError(
                f'{address_key(index)!r} is beyond the address — a customer '
                f'or vendor address holds four lines, {address_key(0)!r} to '
                f'{address_key(OWNER_ADDRESS_LINES - 1)!r}. Only the book\'s '
                f'own `company` address takes more')
        setters[index](value)
    if 'email' in md:
        addr.SetEmail(md['email'] or '')


def _named_address_matches(owner, md: dict) -> bool:
    """Whether the address lines the block names are what the owner holds.

    Only the named ones, for the reason `_write_named_address` gives: what a
    block does not mention, it is not asking to change, so it cannot be a
    reason to call the owner out of date either.
    """
    addr = owner.GetAddr()
    getters = (addr.GetAddr1, addr.GetAddr2, addr.GetAddr3, addr.GetAddr4)
    for index, value in named_address_lines(md).items():
        if index >= OWNER_ADDRESS_LINES or value != getters[index]():
            return False
    return not ('email' in md and (md['email'] or '') != addr.GetEmail())


def _refuse_bracketed_keys(md: dict, known) -> None:
    """No block mints a bracketed key of its own.

    Every path that turns a block's keys into custom metadata passes through
    here, because the rule is the format's rather than any one block's: an
    index in brackets names a line of a list, the address is the only list,
    and a key outside it that wears one would take a name the next
    list-valued key needs. See `refuse_an_index_on_a_key_that_has_no_list`.
    """
    for key in md:
        if key not in known:
            refuse_an_index_on_a_key_that_has_no_list(key)


def _custom_keys_to_store(md: dict, known: frozenset) -> dict:
    """The custom keys a block names, ready to store on a new object.

    `key: ""` clears, and a cleared custom key is one that is not there —
    README's rule for every block, and there is no other reading available:
    nothing could tell a key holding the empty string from one nobody wrote.
    On a create there is nothing to remove, so such a key simply does not
    appear.

    Read as "not None", an empty value was stored as an empty key, and the
    create and update paths then answered the same line differently: a fresh
    book kept `department: ""` and a book that already held the transaction
    dropped it. The export writes back whatever is stored, so the file grew a
    line nobody typed, and the same ledger built two different books depending
    on which book it met — a create, export and re-import that never settled.

    `_merge_custom_metadata` is the same rule where there is something to
    remove.
    """
    _refuse_bracketed_keys(md, known)
    return {k: v for k, v in md.items()
            if k not in known and v is not None and str(v) != ''}


def _merge_slot_keys_named(obj, md: dict, known: frozenset) -> None:
    """Merge the custom keys a block names onto what `obj` already holds.

    As `_merge_custom_metadata` does for an owner or a document, without the
    `BeginEdit`/`CommitEdit` bracket: a split has neither, and is edited
    through the transaction that owns it — which the caller has open.
    """
    _refuse_bracketed_keys(md, known)
    named = {k: v for k, v in md.items() if k not in known and v is not None}
    if not named:
        return
    held = get_custom_metadata(obj) or {}
    for key, value in named.items():
        if str(value) == '':
            held.pop(key, None)
        else:
            held[key] = value
    set_custom_metadata(obj, held)


def _merge_custom_metadata(obj, md: dict, known: frozenset) -> None:
    """The custom keys the block names, merged onto what the object holds.

    Same rule as the address, and for the same reason: a block that names no
    custom key is not asking for the slot to be emptied — a printed document
    carries one, and so does a person correcting a name. Replacing the slot
    wholesale made every partial block a delete.

    A key is removed by naming it empty, which is what `addr[0]: ""` does one
    field over. Removing it by leaving the line out cannot be told from never
    having mentioned it.
    """
    _refuse_bracketed_keys(md, known)
    named = {k: v for k, v in md.items() if k not in known and v is not None}
    held = get_custom_metadata(obj) or {}
    # Only for the objects that *have* an address. This helper serves
    # transactions, invoices and bills too, and none of those owns an address
    # — their known-key sets name none — so on one of them `addr1` is an
    # ordinary custom key the reader chose, and reading it as a line of an
    # address deleted it when a block happened to name `addr[0]`, for an
    # object with no address at all. Parsing it at all was wrong there too: a
    # transaction key spelled with a wild index was refused for asking too
    # much of an address the transaction does not have.
    has_address = any(is_address_key(k) for k in known)
    named_lines = named_address_lines(md) if has_address else {}
    # A key that has since become a field of its own leaves the slot — but
    # only once the block has stated it, because until then the slot is the
    # only copy the book has. A book written before vendors had address
    # setters keeps `addr1` there and has nothing on the field; dropping it
    # unasked would lose the address outright, and writing the field from it
    # unasked would put back a line the reader had just deleted. Stated, the
    # writer above has set the field, so the slot copy is the stale one — and
    # it is the one the parser keeps when both are written, which is what
    # reverted an address changed in GnuCash.
    #
    # An address line is matched by the line it names rather than by the key,
    # because the two spellings name the same line: a block saying `addr[0]`
    # supersedes a slot still holding `addr1`, and matching the key alone left
    # the stale copy behind for every block written since the index moved into
    # brackets — which is every block this tool writes.
    def _superseded(key):
        if has_address and is_address_key(key):
            return address_line_index(key) in named_lines
        return key in known and key in md

    kept = {k: v for k, v in held.items() if not _superseded(k)}
    if not named and kept == held:
        return
    for key, value in named.items():
        if str(value) == '':
            kept.pop(key, None)
        else:
            kept[key] = value
    obj.BeginEdit()
    set_custom_metadata(obj, kept)
    obj.CommitEdit()


def _move_slot_keys_that_became_fields(obj, known: frozenset) -> bool:
    """Put a key the slot still holds onto the field it has since become.

    The shipped release filed a bill's `notes:` and `billing_id:` beside the
    object, because they had no setter then. They have one now, so every book
    written by it carries a stale copy — and a comparison that reads the field
    answers "different" on every run, whatever the file says.

    Migrated here rather than by rebuilding the document, which is what
    reporting the difference used to mean. A posted document judged different
    is unposted and built again, and unposting one whose settlement drew a cost
    basis down is refused outright: measured, `bill 'BILL-USD-FROM-HKD' cannot
    be unposted`, on the very ledger the book was built from — a file that
    could not be imported at all, with the only way out being to delete a line
    from it.

    Moving it is not a change to the document: the value is the one the book
    already held, put where this version keeps it. What the file says is
    compared afterwards, against the field, exactly as for a book this version
    wrote.
    """
    # Only the keys there is somewhere to move to. Taking every known key out
    # of the slot would delete one this has no setter for — the value gone
    # from where it was and never written where it belongs. `notes` and
    # `billing_id` are the two that became fields; a known key with no setter
    # is left exactly where it is, which is at worst the state before this
    # function existed.
    setters = {'notes': 'SetNotes', 'billing_id': 'SetBillingID'}
    held = get_custom_metadata(obj) or {}
    movable = {key: value for key, value in held.items()
               if key in known and key in setters and value}
    if not movable:
        return False
    obj.BeginEdit()
    for key, value in movable.items():
        getattr(obj, setters[key])(value)
    set_custom_metadata(obj, {k: v for k, v in held.items()
                              if k not in movable})
    obj.CommitEdit()
    # Said so, because it is a change to the book and the run has to save for
    # it. Reported as `unchanged` — which the document is, against its file —
    # the move happened in memory and was dropped on session end, so the next
    # run did it again and the migration never finished.
    return True


def _named_custom_metadata_matches(obj, md: dict, known: frozenset) -> bool:
    """Whether the custom keys the block names are what the object holds."""
    named = {k: v for k, v in md.items() if k not in known and v is not None}
    held = get_custom_metadata(obj) or {}
    # A slot still holding a key that has since become a field of its own is
    # out of date whatever the file says. `_move_slot_keys_that_became_fields`
    # puts it where it belongs before this is asked, so anything left here is
    # a key with no field to move to.
    if any(key in known and key in md for key in held):
        return False
    for key, value in named.items():
        if str(value) == '':
            if key in held:
                return False
        elif held.get(key) != value:
            return False
    return True


def _refuse_a_document_that_would_lose_its_lines(
        existing, directive: 'PlaintextDirective', entry_type, kind: str,
        oid: str) -> None:
    """A block with no lines, against a document that has some.

    A document is rebuilt from its block — the file is the source of truth for
    the lines, which is what lets a person correct one by editing it. What was
    missing is any way to tell "the writer restated one line" from "the
    writer's file stops here": a block truncated after the three fields read
    unconditionally still parses, and rebuilding from it unposted the document
    — destroying the posting transaction and orphaning its payments — and left
    it with no lines at all.

    Only when there is something to lose. Creating a document with no lines is
    still allowed, because nothing is destroyed by it, and a tax table has
    refused the same shape all along.
    """
    if existing is None:
        return
    if any(c.type == entry_type for c in directive.children):
        return
    held = list(existing.GetEntries())
    if not held:
        return
    raise Exception(
        f'{kind} {oid!r} has no lines in this file and {len(held)} '
        f'in the book. A {kind} is rebuilt from its block, so importing this '
        f'would unpost it and leave it empty — which is what a file cut short '
        f'looks like. State the lines, or remove the block to leave the '
        f'{kind} alone.')


def _refuse_a_changed_currency(existing, directive: 'PlaintextDirective',
                               kind: str, oid: str) -> None:
    """A `currency:` that is not the one the book has for this object.

    The key is required on every one of these blocks and written back by every
    export, so it reads as a field like any other — and it was neither
    compared nor applied on an object the book already held. The edit reported
    `unchanged`, the book kept the currency the object was created with, and
    the next export wrote that currency back over it: the ledger and the book
    disagreeing for good, with the ledger losing and nothing said.

    Refused rather than applied, because it is not a field. An owner's
    currency is what their documents are raised in and a posted invoice's is
    what its receivable splits are denominated in, so changing one means
    re-raising the documents — a decision, and one this tool will not take
    from a one-word edit.
    """
    if existing is None:
        return
    held = existing.GetCurrency()
    stated = (directive.metadata.get('currency') or '').strip()
    if held is None or not stated or held.get_mnemonic() == stated:
        return
    raise Exception(
        f'{kind} {oid!r} is in {held.get_mnemonic()} in this book and the '
        f'file says {stated}. A currency is what a {kind}\'s documents are '
        f'raised in, so it is not changed by editing the word: raise the new '
        f'ones under a {kind} in {stated}, or put {held.get_mnemonic()} back.')


def _document_text_matches(document, md: dict) -> bool:
    """Whether a document's `billing_id:` and `notes:` are what the block says.

    One function, because it is asked in three places — the invoice
    comparison, the bill comparison, and the unpost fast path — and written
    three times they disagreed: two read an absent key as the empty string
    while the writers set the field only when the block names it, so a block
    that omits `notes:` could never match a document that has them and never
    converge either. Every re-import then unposted the document, destroyed its
    posting, orphaned the payments, and built it again.

    `services/plaintext_blocks.document_text_lines` is the writing half of the
    same pair.

    Through `held_value`, which reads the field and falls back to the slot
    beside the object. The shipped release filed a *bill's* `notes:` and
    `billing_id:` there — they were not known bill keys, so `GetNotes()` on
    such a bill is empty — and reading the field alone answered "different" on
    every run for every book written by it. A posted bill judged different is
    rebuilt, rebuilding unposts it, and unposting one whose settlement drew a
    cost basis down is refused: measured, `bill 'BILL-USD-FROM-HKD' cannot be
    unposted`, on the ledger the book was built from. The way out was deleting
    a line from a file this tool wrote, and the message did not say so.

    The migration still happens — the writers set the field, so the first
    import that touches the document moves it — this only stops the move
    needing an unpost to get there. The address keys took this fallback first;
    the document's own text is twenty lines away in the same file and did not.
    """
    if 'billing_id' in md and held_value(
            document, document.GetBillingID(), 'billing_id') != md['billing_id']:
        return False
    return not ('notes' in md and held_value(
        document, document.GetNotes(), 'notes') != md['notes'])


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
    # Only what the block names, matching what `import_customer` writes: a
    # field the file does not mention is not a reason to call the customer out
    # of date, because nothing would be done about it.
    if not _named_address_matches(customer, md):
        return False
    if 'active' in md and bool(customer.GetActive()) != (
            not _is_falsy(md['active'])):
        return False
    return _named_custom_metadata_matches(
        customer, md, KNOWN_CUSTOMER_METADATA_KEYS)


def _vendor_matches_directive(vendor, directive: 'PlaintextDirective') -> bool:
    """Return True if the vendor's persisted state equals the directive (Q-010).

    The address included, as the customer comparison has always done: read
    without it, a vendor whose address the ledger had changed answered
    "already matches", so the run reported `unchanged` and the move was
    dropped.
    """
    md = directive.metadata
    if vendor.GetName() != md['name']:
        return False
    if not _named_address_matches(vendor, md):
        return False
    if 'active' in md and bool(vendor.GetActive()) != (
            not _is_falsy(md['active'])):
        return False
    return _named_custom_metadata_matches(
        vendor, md, KNOWN_VENDOR_METADATA_KEYS)


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
    # The table as the writer and the exporter see it: both act on the table
    # itself, not on the flag — `import_bill` sets it whenever the block names
    # one, and `_format_bill_entry` emits it whenever the entry has one. Read
    # only when the entry is taxable, the comparison answered `None` for a
    # line that is untaxed and names a table, while the file said `GST`: a
    # disagreement no import could settle, so the document was destroyed and
    # rebuilt on every run — and on a posted one that unposts it, orphaning
    # the payments each time.
    desired_tt = md.get('tax_table')
    actual_tt_obj = entry.GetInvTaxTable()
    actual_tt = actual_tt_obj.GetName() if actual_tt_obj is not None else None
    return (desired_tt or None) == (actual_tt or None)


def _entry_matches_bill_directive(entry, ed: 'PlaintextDirective') -> bool:
    """Compare an existing vendor-bill Entry to a BILL_ENTRY directive.

    The tax flags included. They were left out on the reasoning that GnuCash
    does not persist `bill_taxable: false`, so comparing them would report
    `updated` on every re-import of an untaxed line. That was true of a vendor
    bill handled as a customer invoice — the entry then carried an invoice
    pointer, and GnuCash writes the bill-side flags only for an entry that has
    a bill (CLAUDE.md §8). Handled as a bill, both flags round-trip, and
    leaving them out cost the other half: untaxing a line in the ledger and
    importing again reported `unchanged` and left it taxed.
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
    if bool(entry.GetBillTaxable()) != (md['taxable'] == 'true'):
        return False
    # `tax_included:` is optional on a bill line and defaults to false, which
    # is the default the writer above applies. Asked for outright, the
    # comparison raised `KeyError: 'tax_included'` on every bill line that
    # leaves it off — which is most of them.
    if bool(entry.GetBillTaxIncluded()) != (
            md.get('tax_included', 'false') == 'true'):
        return False
    # The table as the writer and the exporter see it: both act on the table
    # itself, not on the flag — `import_bill` sets it whenever the block names
    # one, and `_format_bill_entry` emits it whenever the entry has one. Read
    # only when the entry is taxable, the comparison answered `None` for a
    # line that is untaxed and names a table, while the file said `GST`: a
    # disagreement no import could settle, so the document was destroyed and
    # rebuilt on every run — and on a posted one that unposts it, orphaning
    # the payments each time.
    desired_tt = md.get('tax_table')
    actual_tt_obj = entry.GetBillTaxTable()
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


def _apply_owner_credit(record) -> None:
    """Have the engine apply the owner's credit to this document.

    What `auto_apply_credit: true` asks for: whichever of the owner's open
    credits the engine reaches for, in its own order. A `from_credit:` block
    does not come here — it names the credit to spend, and one bigger than the
    document goes through `_settle_from_one_split`, which takes no instruction
    from the engine about which credit it is. What the application does to the
    splits — carving a credit, copying stored figures onto everything it makes
    — is put right here, once, rather than at each caller.
    """
    account = record.GetPostedAcc()
    basis_before = _basis_splits_on(account)
    splits_before = _splits_on(account)
    lot_before = _splits_in_lot(record)
    record.AutoApplyPayments()
    _carry_basis_across_applied_credit(record, basis_before, splits_before)
    _mark_applied_from_credit(record, lot_before)


def _cash_before_credit(payment_dirs):
    """Payment blocks in the order they are applied: cash first, credit after.

    What a credit may take is what the document still owes, so it waits for
    every payment that moves money. The lot ends up holding them in this
    order too, which is why the comparison that decides whether a file
    changed anything reads them this way rather than as the file wrote them.
    """
    cash = [pay for pay in payment_dirs
            if _is_falsy(str(pay.metadata.get('from_credit', 'false')))]
    credit = [pay for pay in payment_dirs
              if not _is_falsy(str(pay.metadata.get('from_credit', 'false')))]
    return cash + credit


def _asks_for_credit(directive) -> bool:
    """True iff this file asks for the owner's credit to be applied.

    The header flag is a request, and a file that carries it accounts for
    whatever the request applied. An export describes the same settlement the
    other way round, as a payment block naming the credit it spent, and
    carries no flag.
    """
    return not _is_falsy(str(directive.metadata.get('auto_apply_credit', 'false')))


def _split_came_from_credit(split) -> bool:
    """True iff this split settled its document out of the owner's credit.

    Recorded on the split when the credit was applied, and read here and by
    the exporter alike. Nothing about the split says it otherwise: once
    applied, it sits in the document's lot exactly as a bank payment's split
    does.
    """
    return str(get_custom_metadata(split).get(APPLIED_FROM_CREDIT_KEY, '')
               ).strip().lower() == 'true'


def _looks_like_consumed_credit(split, this_lot_id: int) -> bool:
    """The reading for a book written before the fact was recorded.

    Every book `auto_apply_credit:` has ever produced has credits applied and
    nothing on the splits that applied them, so a book from an earlier
    version would otherwise read as differing from the very file that built
    it — and be unposted and rebuilt, which re-runs the application and
    leaves documents whose lot GnuCash discards on load.

    So where nothing is recorded, the old reading stands: the payment has
    splits in another document's lot (what it was made against) and in a lot
    no document owns (what it left over). It is the reading this replaced,
    with the faults that made it worth replacing — it says nothing of a
    credit consumed to the last cent — but for these books it is the only
    evidence there is, and it is what they were being read by before.
    """
    import gnucash.gnucash_core_c as _gc
    transaction = split.GetParent()
    if transaction is None:
        return False
    in_other_document = False
    in_a_credit_lot = False
    for index in range(transaction.CountSplits()):
        other = transaction.GetSplit(index)
        account = other.GetAccount()
        if account is None or account.GetType() not in (ACCT_TYPE_RECEIVABLE,
                                                        ACCT_TYPE_PAYABLE):
            continue
        lot = other.GetLot()
        if lot is None or int(lot) == this_lot_id:
            continue
        # A lot an unpost abandoned is documentless too, and is not evidence
        # that anything was left over as credit — the last reader of "no
        # document on the lot" to be brought to the same predicate as the
        # rest. Left out, a deposit settling three documents with one of them
        # unposted read the first document's bank settlement as credit
        # consumed, and the file disagreeing with the book forced an
        # unpost-and-rebuild that changed nothing.
        if is_a_bank_paid_orphan(other):
            continue
        if _gc.gncInvoiceGetInvoiceFromLot(lot):
            in_other_document = True
        else:
            in_a_credit_lot = True
    return in_other_document and in_a_credit_lot


def _credit_splits_in_lot(record) -> set:
    """The guids of the splits in this record's lot that came from credit.

    What the application recorded, where it recorded anything; the older
    reading of the lots where it did not, so a book written before this keeps
    being read the way it always was.
    """
    from gnucash import Split
    lot = record.GetPostedLot()
    if lot is None:
        return set()
    posting_txn = record.GetPostedTxn()
    posting_guid = posting_txn.GetGUID().to_string() if posting_txn else None
    this_lot_id = int(lot.instance)

    recorded, looks_like = set(), set()
    for raw in lot.get_split_list():
        split = Split(instance=raw)
        transaction = split.GetParent()
        if transaction is None:
            continue
        if posting_guid is not None and transaction.GetGUID().to_string() == posting_guid:
            continue
        if _split_came_from_credit(split):
            recorded.add(split.GetGUID().to_string())
        elif _looks_like_consumed_credit(split, this_lot_id):
            looks_like.add(split.GetGUID().to_string())
    return recorded or looks_like


def _lot_payment_splits(record, asked_for_credit: bool = False):
    """The AR/AP-side splits in the record's posted lot that the file must
    account for, in GnuCash's iteration order, excluding the posting tx's own.

    Used by both `_payments_match_directive` (strict count + field equality)
    and `_payments_only_added_diff` (every held payment is one the file
    states, and what it states besides is what is being added).

    A credit that settled this document is a payment like any other and the
    file says so, with a `from_credit: true` block — so its split is counted
    here and matched against that block. The exception is a file that asks
    for the credit instead of describing it, with `auto_apply_credit: true`
    on the header: the request accounts for whatever it applied, so those
    splits are left out and the header is what matches them.
    """
    from gnucash import Split
    lot = record.GetPostedLot()
    if lot is None:
        return []
    posting_txn = record.GetPostedTxn()
    posting_txn_guid = posting_txn.GetGUID().to_string() if posting_txn else None
    from_credit = _credit_splits_in_lot(record) if asked_for_credit else set()
    out = []
    for raw in lot.get_split_list():
        s = Split(instance=raw)
        tx = s.GetParent()
        if tx is None:
            continue
        if posting_txn_guid is not None and tx.GetGUID().to_string() == posting_txn_guid:
            continue
        if s.GetGUID().to_string() in from_credit:
            continue
        out.append(s)
    return out


def _bank_side_figure_of(md) -> Optional[Fraction]:
    """What a payment block says moved through the bank, or None.

    A block states two figures when the payment converts: `amount:` in the
    document's currency, and how much of the bank's currency that came to —
    `settled_amount:` outright, or `share_price:` as the rate to reach it.
    Both spellings are documented and the refusal that asks for one offers
    both, so reading only one makes an answer depend on which word was used.

    In one place because the two comparisons that need it drifted apart:
    `_single_payment_matches` compared `amount:` against the bank split and so
    judged every converting payment different from the file that wrote it —
    100 against 780.00 HKD — which made re-importing an unchanged
    third-currency ledger rebuild the document, and rebuilding a settled one is
    refused outright by `require_cost_basis_unused`. Measured on three shapes:
    `invoice 'INV-USD-INTO-HKD' cannot be unposted`, on the second read of the
    file the book was built from.

    And the residue, on a block that names a transaction. There `amount:` is
    this document's own slice and `prepayment:` what the movement left over,
    so the bank moved the two together — the same sum `_apply_payment_directive`
    makes when it rebuilds such a block into a book that has not got the money.
    Read as the slice alone, everything that asks "is this movement already
    here?" compared 100.00 against a 250.00 bank split and answered no: a
    printed overpayment read into a foreign book a second time found neither
    its own payment, nor its own unpost-marked orphan, nor the duplicate guard's
    match, and minted a second 250.00 — on every read after the first, exiting 0.

    Left out of the `settled_amount:` arm, which states the bank's own figure
    outright and needs no arithmetic to reach it.

    None where the block states no amount at all, which a bare retarget does
    not have to.
    """
    stated = str(md.get('amount', '')).strip()
    if not stated:
        return None
    try:
        figure = abs(Fraction(stated))
    except (ValueError, ZeroDivisionError):
        return None
    residue = str(md.get('prepayment') or '').strip()
    if residue and str(md.get('txn_guid') or '').strip():
        try:
            figure += abs(Fraction(residue))
        except (ValueError, ZeroDivisionError):
            return None
    settled = str(md.get('settled_amount') or '').strip()
    if settled:
        try:
            return abs(Fraction(settled))
        except (ValueError, ZeroDivisionError):
            return None
    rate = str(md.get('share_price') or '').strip()
    if rate:
        try:
            return abs(figure * Fraction(rate))
        except (ValueError, ZeroDivisionError):
            return None
    return figure


def _prepayment_amount_for(in_lot_split):
    """Sum of absolute amounts of AR/AP-side splits on `in_lot_split`'s
    parent transaction OTHER than `in_lot_split` itself.

    Returns 0 when the payment tx has exactly one AR/AP split — the normal
    full-or-partial-payment case. Returns the residual amount when GnuCash
    split the payment across multiple AR/AP lots (overpayment → in-invoice lot
    + one or more prepayment lots). Exact, as a `Fraction`: the figure is
    compared against a declared `prepayment:`, and a float sum of cents would
    make that comparison a matter of tolerance.
    """
    tx = in_lot_split.GetParent()
    in_lot_guid = in_lot_split.GetGUID().to_string()
    total = Fraction(0)
    for s in tx.GetSplitList():
        if s.GetGUID().to_string() == in_lot_guid:
            continue
        acct = s.GetAccount()
        if acct is None:
            continue
        if acct.GetType() in (ACCT_TYPE_RECEIVABLE, ACCT_TYPE_PAYABLE):
            total += abs(numeric_to_fraction(s.GetAmount()))
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
    if not _is_falsy(str(md.get('from_credit', 'false'))):
        # A credit block names no account, because nothing paid out of one.
        # The split it names is the whole of what it claims, so matching it
        # is matching that split — which is the one in this document's lot.
        # Through `_normalise_guid`, as everywhere else a guid is read: a
        # hyphenated or upper-case one names the same split, and reading it
        # raw here would send an identical file down the rebuild path.
        try:
            wanted_tx = _normalise_guid(md.get('txn_guid') or '')
            wanted_split = _normalise_guid(md.get('txn_split_guid') or '')
        except Exception:
            return False
        if _normalise_guid(tx.GetGUID().to_string()) != wanted_tx:
            return False
        # The split the file named is the split in the lot even where the
        # credit was bigger than the document: dividing one settles with the
        # named split and parks the rest as a new one, so what the file named
        # is what settled it.
        return _normalise_guid(split.GetGUID().to_string()) == wanted_split
    bank_acct_name = _payment_xfer_account_name(md)
    bank_split = next(
        (s for s in tx.GetSplitList()
         if (a := s.GetAccount()) is not None
         and get_account_full_name(a) == bank_acct_name),
        None,
    )
    if bank_split is None:
        return False
    # Normalised on both sides, as the `from_credit:` branch above already
    # does: a hyphenated or upper-case guid names the same transaction, and
    # compared raw it sent an otherwise identical file down the rebuild path.
    try:
        directive_txn_guid = _normalise_guid(md.get('txn_guid') or '')
    except Exception:
        directive_txn_guid = ''
    if directive_txn_guid:
        if _normalise_guid(tx.GetGUID().to_string()) == directive_txn_guid:
            return True
        # A guid the book does not hold is not authoritative here either.
        # `_apply_payment_directive` records such a payment from the block —
        # that is what makes a printed document readable in another book — so
        # the payment now in the book carries a guid GnuCash minted, and the
        # file still names the source book's. Read as a mismatch, the document
        # was out of date on every run: unposted, its posting destroyed and
        # its payment orphaned, and the rebuild then met the orphan it had
        # just made and refused. The file imported once and never again.
        #
        # Compared on what the block otherwise says, below, which is the same
        # reading that let it be created in the first place.
        book = bank_split.GetAccount().get_book()
        if _find_transaction_by_guid(book, directive_txn_guid) is not None:
            return False
    # And only where the block says enough to be compared that way. A retarget
    # names a movement the book already holds, so it restates none of it —
    # `bank_account:` and the guid are the whole block, which is what every
    # round-trip fixture here writes. Falling through regardless read keys it
    # never carried: with the named transaction since deleted and a second
    # payment's split left to be tried against, the run stopped at
    # `invoice "X": is missing the required field 'date'`, which is not true of
    # that block and not something its writer could act on.
    if 'date' not in md or 'amount' not in md:
        return False
    if tx.GetDate().strftime("%Y-%m-%d") != md['date']:
        return False
    # Against the bank's own figure, because the bank's split is what is being
    # compared. `amount:` alone is the document's currency, so a converting
    # payment never matched the transaction it had itself written.
    wanted = _bank_side_figure_of(md)
    if wanted is None or numeric_to_fraction(bank_split.GetAmount().abs()) != wanted:
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
        expected_prepay = Fraction(0)
    else:
        try:
            expected_prepay = Fraction(str(raw_prepay).strip())
        except (ValueError, ZeroDivisionError):
            return False
    # Both sides are exact, so they are equal or they are not — no tolerance.
    return actual_prepay == expected_prepay


def _pair_off_payments(pay_splits, payment_dirs):
    """Pair each payment the document holds with a block that describes it.

    Returns `(claimed, unclaimed)` — how many splits found a block, and the
    blocks left over in the order the file wrote them.

    Taking each split's first match is not the same question. Where one block
    names its transaction by guid and another describes the same amount, date
    and memo, the described block fits either payment while the named one fits
    only the payment it names: claiming the described block for the wrong split
    leaves the named block with nothing it can match, and a pairing that exists
    is reported as none. What follows is either a file that made a book reading
    as a change to it — unpost, rebuild, orphaned payments — or, on the
    add-a-payment path, a block that describes a payment already in the lot
    being treated as a new one and applied a second time.

    So a block is given up again when the split holding it can be paired
    elsewhere. That is Kuhn's augmenting-path search, which finds the largest
    pairing there is, so a pairing is missed only when there genuinely is none.
    Both lists are a document's payments — a handful — and the cost is the
    product of their lengths.
    """
    claimed_by = {}

    def find_a_block_for(split_index, tried):
        for block_index, block in enumerate(payment_dirs):
            if block_index in tried:
                continue
            if not _single_payment_matches(pay_splits[split_index], block):
                continue
            tried.add(block_index)
            holder = claimed_by.get(block_index)
            if holder is None or find_a_block_for(holder, tried):
                claimed_by[block_index] = split_index
                return True
        return False

    claimed = sum(1 for index in range(len(pay_splits))
                  if find_a_block_for(index, set()))
    unclaimed = [block for index, block in enumerate(payment_dirs)
                 if index not in claimed_by]
    return claimed, unclaimed


def _payments_match_directive(record, payment_dirs, asked_for_credit=False) -> bool:
    """True iff the record's posted-lot payments match the directives
    one-for-one (same count, same field values). Used by the strict
    `_invoice_matches_directive` / `_bill_matches_directive`.
    """
    pay_splits = _lot_payment_splits(record, asked_for_credit)
    if len(pay_splits) != len(payment_dirs):
        return False
    # Matched by searching, as the add-a-payment classifier does: two cash
    # blocks, or two credit blocks, sit in the lot in an order of the lot's
    # own choosing, and reading them off against the file position by
    # position calls an unchanged document changed and rebuilds it.
    claimed, _ = _pair_off_payments(pay_splits, payment_dirs)
    return claimed == len(pay_splits)


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

    Also marks the splits about to be orphaned, whether or not anyone wanted
    the warning — the warning is for the user, the mark is for
    `_sits_in_an_owners_credit`, which has no other way to tell an abandoned
    lot from an owner's credit. That is why every importer-side
    `Unpost(False)` calls this, including the ones with nothing to warn about.
    """
    if record.GetPostedTxn() is None:
        return
    mark_splits_orphaned_by_unpost(record)
    if on_orphan_warning is None:
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


def _require_posting_currency_match(record_currency: str, ar_ap_account,
                                    kind: str, ident: str, account_name: str):
    """Refuse to post a record to an A/R or A/P account in another currency.

    This is the rule GnuCash's own post dialog enforces — it builds the
    post-to picker from `gncOwnerGetCommoditiesList()`, so an account in
    another currency is never offered. The filter lives in the GUI;
    `gncInvoicePostToAccount` takes no exchange rate and validates nothing, so
    a tool driving the engine directly inherits no protection and the posting
    is written with an A/R amount of zero: the lot closes on its own posting
    date, the record reads as settled the day it was issued, and a later
    payment finds no open lot to join.
    """
    commodity = ar_ap_account.GetCommodity()
    account_currency = commodity.get_mnemonic() if commodity is not None else '?'
    if account_currency == record_currency:
        return
    side = 'A/P' if kind == 'bill' else 'A/R'
    raise Exception(
        f'{kind} {ident!r} is in {record_currency} but {side} account '
        f'{account_name!r} is in {account_currency} — a record posts only to an '
        f'{side} account denominated in its own currency. Post it to a '
        f'{record_currency} {side} account, or issue the {kind} in '
        f'{account_currency}.')


def _require_the_account_can_hold_the_total(record, ar_ap_account, kind: str,
                                            ident: str, account_name: str):
    """Refuse to post a total the receivable or payable cannot hold exactly.

    An amount this tool writes is one the account can express, or it is
    refused — never one rounded to fit. A price carries as many decimals as it
    needs; an amount does not, and the two have to reconcile: 1.819 a litre is
    an ordinary price, and it is a *quantity* of ten that makes the amount
    18.19 rather than a figure the book then rounds. Where they cannot both be
    true the file is saying something the book cannot record, and saying so is
    the answer.

    GnuCash rounds instead. Posting a 30.05 total to a receivable kept to the
    tenth writes 30.10, so the document is owed a figure it was never issued
    for, every payment afterwards is measured against the rounded one, and
    nothing in the book disagrees. An account may be kept to any unit — that is
    the user's to set, and this tool round-trips it — but a document whose
    total lands between two of them belongs to neither.
    """
    commodity = ar_ap_account.GetCommodity()
    unit = ar_ap_account.GetCommoditySCU() or (
        commodity.get_fraction() if commodity is not None else 100)
    total = abs(numeric_to_fraction(record.GetTotal()))
    if (total * unit).denominator == 1:
        return
    side = 'A/P' if kind == 'bill' else 'A/R'
    raise Exception(
        f'{kind} {ident!r} totals '
        f'{exact_text(total)}, which {side} account '
        f'{account_name!r} cannot hold — its smallest unit is '
        f'{money_text(Fraction(1, unit), unit)}. Posting it would round the '
        f'total, so the {kind} would be owed a figure it was not issued for. '
        f'Price the entries so the total lands on that unit, or give the '
        f'account a finer `commodity_scu:`.')


def _attach_posting_rate(record, book, directive, entry_type, post_date,
                         fx_rates, kind: str, ident: str):
    """Attach the rate that values entries booked to an account in another
    currency, so a foreign-currency record recognises income or expense in the
    book's own currency at its posting-date rate.

    GnuCash values such an entry from a price attached to the record itself —
    `gncInvoicePostAddSplit` looks the account's commodity up in the invoice's
    own price list and aborts the whole posting when it finds none ("Multiple
    commodities with no price"), writing nothing while still reporting the
    record created. So the rate is attached before posting, and a date no rate
    covers is refused here rather than silently dropped by the engine.
    """
    record_commodity = record.GetCurrency()
    record_currency = record_commodity.get_mnemonic()
    root = book.get_root_account()

    wanted = {}
    for entry_directive in directive.children:
        if entry_directive.type != entry_type:
            continue
        account = find_account(root, entry_directive.metadata['account'])
        if account is None:
            continue
        commodity = account.GetCommodity()
        if commodity is None or commodity.get_mnemonic() == record_currency:
            continue
        wanted.setdefault(commodity.get_mnemonic(), commodity)

    if not wanted:
        return

    as_of = post_date.date() if hasattr(post_date, 'date') else post_date
    for mnemonic, commodity in sorted(wanted.items()):
        if fx_rates is None:
            raise Exception(
                f'{kind} {ident!r} is in {record_currency} and books to a '
                f'{mnemonic} account, so posting it needs the '
                f'{record_currency}/{mnemonic} rate on '
                f'{as_of.isoformat()} — pass --fx-rates <file>')
        try:
            entry_rate = fx_rates.rate_fraction(mnemonic, as_of)
            record_rate = fx_rates.rate_fraction(record_currency, as_of)
        except MissingFxRateError as exc:
            raise Exception(
                f'{kind} {ident!r} posts on {as_of.isoformat()} and books to a '
                f'{mnemonic} account: {exc}') from exc
        # A GNCPrice reads "1 unit of commodity = value units of currency", and
        # the engine looks it up by the *entry account's* commodity, so this is
        # how many units of the record's currency one unit of that account's
        # commodity buys.
        value = entry_rate / record_rate
        price = GncPrice(book)
        price.set_commodity(commodity)
        price.set_currency(record_commodity)
        price.set_value(GncNumeric(value.numerator, value.denominator))
        try:
            price.set_time64(post_date)
        except AttributeError:                       # GnuCash 3.x
            price.set_time(post_date)
        price.set_source_string('user:xfer-dialog')
        price.set_typestr('transaction')
        record.AddPrice(price)


_OWNER_KINDS = {2: 'customer', 4: 'vendor'}


def _owner_of_a_credit_beside(lib, split, transaction):
    """The owner of a credit lot on this transaction, where exactly one names one.

    For the half of a divided credit that has no lot of its own. Dividing makes
    two splits of one transaction — the part that settled a document, which
    goes into that document's lot, and the credit left over, which goes into a
    lot of its owner's. Exported and read into a fresh book, the first arrives
    loose: the export writes no `lot_owner:` for it, because that line is
    derived from live lot state and a document's lot is not an owner's. So the
    book knows whose money it is and cannot say — until the credit beside it is
    asked. Without this, another owner's document could name that split by guid
    and settle out of it, which is the exact slip the guard exists to catch.

    Asked **only of a split that says it came out of a credit**. The import
    writes `applied_from_credit` on every split it moves out of one, and that
    is what separates the two halves of one divided credit from two owners'
    portions of one deposit. Without it the inference reaches too far: a
    deposit that is partly Alpha paying ahead and partly Beta's payment gives
    Alpha's credit lot a neighbour that was never Alpha's, and Beta naming
    their own portion — by guid, the documented spelling — was refused and
    told to check guids that were correct.

    Only a lot **no document owns** answers. A sibling in a document's lot says
    who that document is for and nothing about the loose split beside it.
    Several such lots disagreeing answer nothing either.
    """
    import gnucash.gnucash_core_c as _gc

    if not get_custom_metadata(split).get(APPLIED_FROM_CREDIT_KEY):
        return None

    named = set()
    live_lots = {}
    for index in range(transaction.CountSplits()):
        sibling = transaction.GetSplit(index)
        lot = sibling.GetLot()
        if lot is None:
            continue
        # Membership before dereference: a split can hold a pointer the book
        # has let go of (finding 9 plus `gnc_lot_remove_split`), and this walks
        # every sibling rather than one named split — so each account's lot
        # list is read once rather than once per sibling on it. Per account,
        # because the siblings are not all on one: a bank entry carrying a
        # customer's advance and a vendor's prepayment has a credit on the
        # receivable and one on the payable, and the two receivables of this
        # issue are two accounts as well. Measuring every credit against
        # whichever account came first drops the rest as lots the book has let
        # go of, and one owner is then named out of two — the loose half
        # refused to the owner whose money it may be, and given to the other.
        account = sibling.GetAccount()
        if account is None:
            continue
        account_ptr = int(account.instance)
        if account_ptr not in live_lots:
            live_lots[account_ptr] = _live_lot_pointers(account)
        if int(getattr(lot, 'instance', lot)) not in live_lots[account_ptr]:
            continue
        if _gc.gncInvoiceGetInvoiceFromLot(getattr(lot, 'instance', lot)):
            continue                    # a document's lot, not an owner's
        buffer = ctypes.create_string_buffer(256)
        owner_ptr = ctypes.cast(buffer, ctypes.c_void_p)
        if lib.gncOwnerGetOwnerFromLot(ctypes.c_void_p(int(lot)), owner_ptr) != 1:
            continue
        kind = _OWNER_KINDS.get(lib.gncOwnerGetType(owner_ptr))
        raw_id = lib.gncOwnerGetID(owner_ptr)
        owner_id = raw_id.decode('utf-8', errors='replace') if raw_id else ''
        if kind and owner_id:
            named.add((kind, owner_id))
    return named.pop() if len(named) == 1 else None


def _lot_is_still_on_its_account(split, lot) -> bool:
    """Whether the account still lists this lot — membership, not dereference.

    The one question it is safe to ask about a lot pointer a split is holding,
    since the answer comes from the account rather than from the pointer. See
    `_live_lot_pointers`, which every other reader here goes through.

    How a split comes to hold a pointer the book has let go of, within one
    import: this tool settles a document by attaching a split with
    `xaccSplitSetLot`, which does not add it to the lot's own split list
    (finding 9). If that same run then unposts the document — a later
    directive in the same file restating it — GnuCash sees a lot whose listed
    splits are only the posting's, empties it, and frees it, while the
    settlement goes on pointing there. It is the reason
    `mark_splits_orphaned_by_unpost` reads the account rather than the lot.

    Not directly tested: constructing it needs one file that both settles a
    document and restates it, since a save and reload between the two rebuilds
    every lot list from `split->lot` and the pointer stops dangling. The guard
    is one list walk, and what it guards against is a segfault in the middle of
    the money path.
    """
    account = split.GetAccount()
    if account is None:
        return False
    return int(getattr(lot, 'instance', lot)) in _live_lot_pointers(account)


def _recorded_owner_of(split):
    """Whose money a split is — ('customer'|'vendor', id) — or None.

    The lot first: an owner's credit sits in a lot of theirs, and a document's
    lot belongs to whoever the document is for.

    A split in no lot has no owner of its own, and its transaction answers for
    it only where that transaction carries a single receivable or payable
    split. One deposit settles documents of several owners at once, and the
    owner GnuCash records on it is whichever of them it happened to record —
    reading that for an unlotted split calls the second owner's money the
    first owner's. Where there is only one such split there is no ambiguity,
    and a payment GnuCash wrote for one owner is the shape a guid gets copied
    out of.

    A split that *has* a lot is answered by that lot or not at all — the
    transaction is not asked behind it. A lot carrying no owner is a book
    already in a state this tool treats as a defect: every path that makes one
    attaches the owner, `find-prepayments` reports the lots that have none, and
    `_ownerless_open_credit_lots` exists to find them. Reading the transaction
    for such a split would answer from some *other* lot on it, which is the
    shared-deposit misattribution this function exists to avoid, so the
    silence stands.

    None means the book says nothing, which is the ordinary case for a
    transaction off a bank feed, and nothing is refused on that silence. Where
    a file names a transaction and no split at all, the caller asks this of
    the split the retarget would move — `_refuse_another_owners_split` on the
    answer `_retarget_choices` gives — so one question is asked about one
    split whichever way the file addressed it.
    """
    from infrastructure.gnucash.engine import load_gnc_engine
    # Signatures are set in `_setup_lib_restypes` with every other one, and
    # the four names are in the list `load_gnc_engine` verifies — so an engine
    # without them fails before a book is opened rather than leaving this
    # check quietly doing nothing.
    lib = load_gnc_engine()
    buffer = ctypes.create_string_buffer(256)
    owner_ptr = ctypes.cast(buffer, ctypes.c_void_p)

    # The lot, and only the lot. A split in no lot is nobody's yet, and the
    # transaction cannot answer for it: one deposit settles documents of
    # several owners at once, so its owner is whichever of them GnuCash
    # recorded, and reading that for an unlotted split calls the second
    # owner's money the first owner's. Where the transaction is the whole of
    # what a file names — `txn_guid:` with no split — this is asked of the
    # split the retarget picked, not of the transaction.
    lot = split.GetLot()
    if lot is None:
        # Not lotted yet, so the lot cannot say. The transaction can, but only
        # where it carries one receivable or payable split: a deposit settling
        # several owners' documents records whichever owner GnuCash put on it,
        # and reading that for an unlotted split calls the second owner's
        # money the first owner's. With a single such split there is no
        # ambiguity, and a payment written by GnuCash for one owner is the
        # ordinary shape a guid can be copied out of.
        transaction = split.GetParent()
        if transaction is None:
            return None
        business_splits = 0
        for index in range(transaction.CountSplits()):
            account = transaction.GetSplit(index).GetAccount()
            if account is not None and account.GetType() in (ACCT_TYPE_RECEIVABLE,
                                                             ACCT_TYPE_PAYABLE):
                business_splits += 1
        if business_splits != 1:
            # Several, so the transaction cannot answer — but where this split
            # says it came out of a credit, the credit beside it can. See
            # `_owner_of_a_credit_beside`.
            return _owner_of_a_credit_beside(lib, split, transaction)
        if lib.gncOwnerGetOwnerFromTxn(
                ctypes.c_void_p(int(transaction.instance)), owner_ptr) != 1:
            return None
    elif not _lot_is_still_on_its_account(split, lot):
        # A pointer the account no longer lists is a lot the book has let go
        # of, and asking it anything is a question about freed memory. The
        # split can hold one: `gnc_lot_remove_split` frees a lot once its
        # *listed* splits run out, and a split attached with `xaccSplitSetLot`
        # is not on that list (CLAUDE.md finding 9). Same membership-before-
        # dereference rule the retarget readers follow, and this is reached
        # ahead of them — `_refuse_another_owners_split` runs first.
        return None
    elif lib.gncOwnerGetOwnerFromLot(ctypes.c_void_p(int(lot)), owner_ptr) != 1:
        return None

    kind = _OWNER_KINDS.get(lib.gncOwnerGetType(owner_ptr))
    raw_id = lib.gncOwnerGetID(owner_ptr)
    owner_id = raw_id.decode('utf-8', errors='replace') if raw_id else ''
    if not kind or not owner_id:
        return None
    return (kind, owner_id)


def _refuse_if_not_this_owner(record, theirs, kind: str, doc_id: str, what: str) -> None:
    """Refuse when the book records *theirs* as somebody else's money."""
    if theirs is None:
        return
    try:
        owner = record.GetOwner()
        mine = (_OWNER_KINDS.get(owner.GetType()), owner.GetID())
    except Exception:
        return
    # A document can be owned by a job or an employee, which a lot reports as
    # the customer or vendor behind it — so the two are not comparable and
    # this says nothing about whose money it is. Silence is not a refusal
    # anywhere else in this check, and it is not one here: a job-owned invoice
    # reaching the retarget path is ordinary work.
    if mine[0] is None or not mine[1] or theirs == mine:
        return
    # Kind as well as id: a customer and a vendor can be filed under the same
    # id, and `customer:C001` is not `vendor:C001`.
    raise Exception(
        f'{kind} {doc_id}: {what} is {theirs[0]} {theirs[1]}\'s money, and '
        f'this {kind.lower()} is {mine[0]} {mine[1]}\'s — one owner\'s '
        f'payment cannot settle another\'s {kind.lower()}. Check the guids '
        f'against the {theirs[0]} they belong to.')


def _same_commodity(one, other) -> bool:
    """Whether two accounts hold the same currency.

    True when the second is not given, which is the caller saying it has no
    second account to compare — the figures are then both the document's own.
    """
    if other is None or one is None:
        return True
    mine = one.GetCommodity()
    theirs = other.GetCommodity()
    if mine is None or theirs is None:
        return True
    return mine.get_mnemonic() == theirs.get_mnemonic()


def _refuse_a_payment_that_would_fall_short(md, carried: Fraction,
                                            outstanding: Fraction, account,
                                            kind: str, doc_id: str,
                                            txn_guid: str,
                                            split_account=None) -> None:
    """Refuse where the split found is smaller than both the stated payment
    and what the document still owes.

    A block naming only its transaction leaves the choice of split to the
    importer, and what that finds is not always the money the file was written
    about: a settlement can have been divided or spent since, leaving a
    different split of the same transaction in its place. Taking it settles
    the document by however much it happens to carry and stops, which is a
    quiet way to leave a document part-paid out of somebody else's money.

    Measured against *both* figures because a smaller split is ordinary on its
    own. A document settled by two blocks and then rebuilt meets its own money
    divided in two, and the block stating the whole 50.00 finds the 20.00 that
    is left — with the other 30.00 already back in the document's lot, so
    nothing falls short and nothing is refused. What is refused is the split
    that covers neither: the file says 100.00 arrived, 60.00 is all that is
    there, and the document is owed the whole 100.00 still.

    Silent where the file states no `amount:`. It is not a required field on
    this spelling, and a block that says nothing about the figure asserts no
    wrong one.
    """
    stated = (str(md.get('amount', '')) or '').strip()
    if not stated:
        return
    try:
        claimed = Fraction(stated)
    except (ValueError, ZeroDivisionError) as exc:
        raise Exception(
            f'{kind} {doc_id}: payment amount must be a number, got '
            f'{stated!r}') from exc
    # Only where the two figures are the same money. `amount:` is written in
    # the document's own currency; the split's figure is in the currency of the
    # account it sits on, and this spelling exists for bank-feed transactions
    # whose other side can be an Imbalance split in the bank's. Comparing a
    # USD document's 100 against a CAD split's 137 says nothing in either
    # direction, so nothing is said.
    if not _same_commodity(account, split_account):
        return
    if carried >= claimed or carried >= outstanding:
        return
    raise Exception(
        f'{kind} {doc_id}: this block says {_account_money_str(claimed, account)} '
        f'arrived, but the split it would move on tx {txn_guid!r} carries '
        f'{_account_money_str(carried, account)} and the {kind.lower()} is owed '
        f'{_account_money_str(outstanding, account)} — so taking it would leave '
        f'the {kind.lower()} part-paid out of money this file does not '
        f'describe. What it was written about has been divided or spent since. '
        f'Name the split meant with `txn_split_guid:`, or state what really '
        f'settles this {kind.lower()} now.')


def _why_nothing_can_move(transaction, bank_acct_name: str, txn_guid: str,
                          kind: str, doc_id: str) -> Exception:
    """The refusal for a `txn_guid:` with no split the retarget may take.

    Returned rather than raised, so the caller's `raise` is where the reading
    stops — a helper that refuses by raising reads, at the call site, like a
    check that might let you past.

    Two things bring a caller here and they are not the same. Usually the
    transaction's splits are all spoken for: each settles a document that
    reads as paid, and taking one would leave that document unpaid with every
    figure still balancing. Saying "no non-bank split" — the only thing this
    could report before it knew the difference — sends the reader looking for
    something plainly in front of them. The other is the literal absence,
    which is a different mistake with a different remedy.

    A split holding an owner's credit is not one of the two. It is a tier of
    the search (`_placeable_lotted_splits`), so a transaction carrying one
    never gets here, and naming it among the possible obstacles sent the
    reader looking for a credit they have not got.

    For the first, the remedy is the one the ambiguity refusal names, because
    the fact underneath is the same: a transaction says which document each of
    its splits settles only if the file says so, and `txn_split_guid:` says it.
    """
    takeable = [split for split in transaction.GetSplitList()
                if (account := split.GetAccount()) is not None
                and get_account_full_name(account) != bank_acct_name]
    if not takeable:
        return Exception(
            f'{kind} {doc_id}: tx {txn_guid!r} has no split outside '
            f'{bank_acct_name!r} to settle it with. Name a transaction whose '
            f'other side can be retargeted, or write a payment block with '
            f'`amount:` and `date:` to have one made.')
    return Exception(
        f'{kind} {doc_id}: every split of tx {txn_guid!r} outside '
        f'{bank_acct_name!r} already settles a document — retargeting one '
        f'would leave that document unpaid with no figure disagreeing. Name a '
        f'transaction that still has money to give, or, if one of these '
        f'splits really belongs to this {kind}, name it outright with '
        f'`txn_split_guid:` and unpick what it is settling now.')


def _retarget_candidates(transaction, bank_acct_name: str):
    """The splits a retarget could place: the sides that are not the bank's,
    and not already in a lot.

    Not filtered by account type. A transaction off a bank feed has an
    Imbalance split where the receivable will be, and re-accounting that one is
    what the mechanic is for — so what may move is "not the bank" rather than
    "a receivable or payable".

    Not the lotted ones, either. A transaction this tool has already divided
    carries the residue it parked, in a lot of the owner's, and that split has
    been placed: retargeting is about placing one that has not.
    """
    return [split for split in transaction.GetSplitList()
            if (account := split.GetAccount()) is not None
            and get_account_full_name(account) != bank_acct_name
            and split.GetLot() is None]


def _retarget_choices(transaction, bank_acct_name: str, own_lot, record):
    """Every split the mover would weigh, from the surest tier that has any.

    The caller takes the first of what comes back as the split to move, and
    hands the whole tier to `_refuse_an_ambiguous_retarget`. Worked out once
    per payment block: walking a receivable's lot list is walking one lot per
    document the book has ever posted there, and asking it for each question
    separately made an import cost the product of its documents and the book's
    history.

    The last tier covers two things a file may legitimately name. One is an
    owner's parked credit, which a document may spend. The other is the
    rebuild: re-importing a paid document unposts it, which detaches the
    document but leaves the lot on the account with the split still in it, so
    the split is neither loose nor in the record's new lot. Nothing about the
    two lots differs — both are live, documentless and owner-attached — and
    they do not have to differ here, because both answer the same question the
    same way. What turns on the difference is whether moving the split spends
    a credit; `_sits_in_an_owners_credit` is where that is decided, and it is
    decided by reading what the unpost wrote down rather than by asking the lot.

    A lot the account no longer lists belongs with those: the book has let go
    of it, so it holds no document either, and such a pointer is not one to ask
    anything of. It does not have to be asked — a live lot is in its account's
    lot list, so absence from that list is membership rather than dereference.

    What is left after those is a split settling *another* document, in a lot
    that is live and holds a document reading as paid. Moving it leaves that
    document silently unpaid with every figure still balancing, and no file
    asked for it, so nothing is returned and the caller refuses.

    The tiers, surest first: the split this record's own unpost abandoned;
    then splits in no lot; then one in this record's own lot; then whatever
    else is placeable — another document's orphan, or an owner's credit.

    The marked orphan leads because it is the only tier that says *this*
    document. A split in no lot is merely unclaimed, and where a transaction
    carries both — a deposit covering two documents, one of them being rebuilt
    while the other's portion has not been imported yet — taking the loose one
    settles this document out of the sibling's money and abandons its own
    settlement, with no ambiguity to refuse because only one split is loose.

    Returning a tier rather than a split is what lets `_refuse_an_ambiguous_
    retarget` count exactly what the mover would choose between. Counting
    something else is how both of this guard's failures happened: it counted
    receivable-typed splits while the mover took "the side that is not the
    bank", and then lot-less splits while the mover falls back to lotted ones.
    Two splits in a tier the mover never reaches are not an ambiguity, and one
    it does reach is.
    """
    # Worked out at most once, and only where a tier needs it: it walks the
    # account's whole lot list, which is one lot per document the book has ever
    # posted there. The ordinary block has a loose split waiting and never
    # reaches a tier that asks.
    computed = []

    def placeable():
        if not computed:
            computed.append(_placeable_lotted_splits(
                transaction, bank_acct_name, own_lot))
        return computed[0]

    # A rebuild's own orphan is not a choice between anything: this document
    # was settled by this split, and the unpost that separated them said so.
    # Without the tier, a document overpaid by retarget could not be edited —
    # its transaction carries the orphan *and* the residue it parked, which are
    # two placeable splits and so read as ambiguous, though only one of them
    # was ever this document's.
    #
    # The mark is a KVP read, so which splits could be this record's own is
    # answered before any lot list is walked; only if one is does placeability
    # get asked.
    # Compared only when there is a guid to compare: unmarked splits report ''
    # and a record with no readable guid would report '' too, which would make
    # every placeable split read as this document's own orphan.
    guid = _swig_invoice_guid_str(record)
    marked = [split for split in transaction.GetSplitList()
              if guid and _orphaned_from(split) == guid]
    if marked:
        wanted = {int(split.instance) for split in marked}
        mine = [split for split in placeable()
                if int(split.instance) in wanted]
        if mine:
            return mine

    loose = _retarget_candidates(transaction, bank_acct_name)
    if loose:
        return loose

    mine_ptr = (int(getattr(own_lot, 'instance', own_lot))
                if own_lot is not None else None)
    # The bank filter every other tier applies. A lot belongs to one account,
    # so a bank split cannot be in this record's receivable lot and the filter
    # can never fire — kept because dropping it would make the tiers disagree
    # about what "a split the mover could take" means, and the reader has to
    # be able to read one and know the rest.
    own = [split for split in transaction.GetSplitList()
           if (account := split.GetAccount()) is not None
           and get_account_full_name(account) != bank_acct_name
           and (lot := split.GetLot()) is not None
           and int(getattr(lot, 'instance', lot)) == mine_ptr]
    if own:
        return own

    return placeable()


def _placeable_lotted_splits(transaction, bank_acct_name: str, own_lot):
    """The already-lotted splits a retarget may still place.

    A split in a lot holding no document: an owner's parked credit, or what an
    unpost abandoned. A lot the account no longer lists counts as holding none
    — the book has let go of it — and is answered by membership rather than by
    handing a pointer the engine may have freed back to the engine.

    Excludes this record's own lot, which the caller answers ahead of these and
    which is never ambiguous — it is the document's own.

    Shared by the mover and by `_refuse_an_ambiguous_retarget`, so the two
    cannot disagree about what could be picked. They did: the guard counted
    only lot-*less* splits, so a transaction carrying two of an owner's credits
    — which the `txn_split_guid:` + `prepayment:` path can leave, parking each
    loose sibling in its own lot — was not ambiguous by that measure while the
    mover had two to choose between and took whichever came first. On a foreign
    book the two can carry different costs, so split order would decide which
    basis was consumed, and with it the gain realized.
    """
    mine_ptr = (int(getattr(own_lot, 'instance', own_lot))
                if own_lot is not None else None)
    live_lots = {}
    placeable = []
    for split in transaction.GetSplitList():
        account = split.GetAccount()
        if account is None or get_account_full_name(account) == bank_acct_name:
            continue
        lot = split.GetLot()
        if lot is None:
            continue                        # offered as a candidate already
        lot_ptr = int(getattr(lot, 'instance', lot))
        if lot_ptr == mine_ptr:
            continue
        # Once per account rather than once per split: the walk is over one lot
        # per document the book has ever posted there.
        account_ptr = int(account.instance)
        if account_ptr not in live_lots:
            live_lots[account_ptr] = _live_lot_pointers(account)
        if lot_ptr not in live_lots[account_ptr]:
            placeable.append(split)         # destroyed; holds no document
        elif not gc.gncInvoiceGetInvoiceFromLot(getattr(lot, 'instance', lot)):
            # Asked only of a lot the account still lists, which is what the
            # check above is for: a pointer the book has freed is not one to
            # hand to the engine.
            placeable.append(split)
    return placeable


def _sits_in_an_owners_credit(split) -> bool:
    """Whether moving this split out of its lot spends an owner's credit.

    An owner's credit is a live lot that holds no document and names an owner.
    All three are asked. Live, because a destroyed lot holds nothing and is no
    pointer to question. No document, because a lot holding one is a document's
    lot and its splits settle that document. An owner, because a lot can hold
    no document and belong to nobody — GnuCash opens lots on stock and asset
    accounts to match sales against purchases, and stripping the cost basis off
    one of those would take a figure this tool did not put there.

    False, too, for a settlement an unpost orphaned, which is otherwise
    identical: live lot, no document, owner attached. Nothing in the book
    separates the two, so the unpost writes it down at the time and this reads
    what it wrote (`ORPHANED_BY_UNPOST_KEY`, CLAUDE.md finding 10).

    Whose orphan it is does not enter into it — what settles the question is
    whether the money ever came out of credit, which the split says by
    carrying `applied_from_credit` or not. An orphan that did is credit still,
    loose again and spendable by anyone the owner owes; an orphan that did not
    is a bank's payment waiting to be put back, whichever document's unpost
    loosened it. `_apply_credit_payment_directive` reads the same fact off the
    same split for the same reason.

    What turns on it is the bookkeeping a settlement does. Spending a credit
    takes the cost basis off the split it spent and notes where the money came
    from, exactly as a `from_credit:` block does; a file reaching the same
    physical move through a bare `txn_guid:` gets the same accounting, rather
    than a split left carrying a basis for currency it no longer holds.
    """
    lot = split.GetLot()
    if lot is None:
        return False
    if is_a_bank_paid_orphan(split):
        # An unpost loosened this, and it never came out of credit — so a bank
        # paid it, and it is a settlement waiting to be put back rather than
        # anybody's credit to spend. True whichever document's unpost left it:
        # `unpost-invoices B` and then a file settling A off B's deposit is one
        # step and reachable, and calling it a credit there strips the basis
        # off currency the bank still holds and exports a block that named an
        # account and a date as `from_credit:` carrying neither.
        return False
    account = split.GetAccount()
    if account is None:
        return False
    if int(getattr(lot, 'instance', lot)) not in _live_lot_pointers(account):
        return False
    raw = getattr(lot, 'instance', lot)
    if gc.gncInvoiceGetInvoiceFromLot(raw):
        return False
    from infrastructure.gnucash.engine import load_gnc_engine
    lib = load_gnc_engine()
    buffer = ctypes.create_string_buffer(256)
    owner_ptr = ctypes.cast(buffer, ctypes.c_void_p)
    return lib.gncOwnerGetOwnerFromLot(ctypes.c_void_p(int(raw)), owner_ptr) == 1


# A dict for the length of a stretch of lot-membership questions that nothing
# between them can change the answer to, and None everywhere else. Opened by
# `_lot_membership_unchanged`, which is the only thing that should write it.
_LIVE_LOT_MEMO = None


@contextmanager
def _lot_membership_unchanged():
    """Answer repeated "is this lot still the account's" from one walk.

    The guards a settlement runs before it moves anything each ask that, and
    each answer costs the account's whole lot list — one lot per document ever
    posted on a receivable, with a `GList` node built in Python for every one.
    Three guards on the same split therefore walked the same list three times,
    and re-importing an export of a long-lived book paid the product of its
    documents and its history. `_retarget_choices` was corrected for exactly
    this and the guards beside it were not.

    Held open only where nothing can move a split, which is what makes a
    remembered answer safe: posting a document opens a lot, parking a residue
    opens another, and `gnc_lot_remove_split` destroys one when its listed
    splits run out — so a memo living across any of those would report a live
    lot as one the book had let go of, and the reader treats that as a lot
    holding nothing. Nested opens keep the outer dict and leave it in place,
    so a stretch inside another does not end the outer one early.
    """
    global _LIVE_LOT_MEMO
    outer = _LIVE_LOT_MEMO
    if outer is None:
        _LIVE_LOT_MEMO = {}
    try:
        yield
    finally:
        _LIVE_LOT_MEMO = outer


def _live_lot_pointers(account):
    """Every lot the account still has, as raw pointers.

    Membership, not dereference. A split whose lot is missing from here is
    holding a pointer the book no longer has, and asking that pointer anything
    is a question about freed memory; asking the *account* is safe whatever the
    split holds.

    Nothing here calls `gnc_lot_destroy` or `xaccAccountRemoveLot` directly,
    and unposting does not destroy the lot either — finding 10 in CLAUDE.md is
    that it leaves it on the account, which is what makes the rest of this
    necessary. But `gnc_lot_remove_split` destroys a lot once its *listed*
    splits run out, and finding 9 is that a split attached with
    `xaccSplitSetLot` is not on that list: a lot can be emptied and freed while
    a split this tool attached is still pointing at it. Membership is what
    answers that safely, and the cost of asking is one list walk against a
    segfault.
    """
    from infrastructure.gnucash.engine import iterate_glist, load_gnc_engine

    account_ptr = int(account.instance)
    memo = _LIVE_LOT_MEMO
    if memo is not None and account_ptr in memo:
        return memo[account_ptr]
    lib = load_gnc_engine()
    pointers = set(iterate_glist(
        lib, lib.xaccAccountGetLotList(account_ptr),
        lambda _lib, data: int(data)))
    if memo is not None:
        memo[account_ptr] = pointers
    return pointers


def _refuse_an_ambiguous_retarget(bank_acct_name: str, txn_guid: str,
                                  kind: str, doc_id: str, candidates) -> None:
    """Refuse `txn_guid:` alone where the transaction offers several splits.

    A block naming only a transaction is retargeted by moving the side that is
    not the bank — and where there are several such sides, the one that moves
    is whichever the transaction returns first. That is a choice made by split
    order, not by the file, and it moves real money: on a deposit covering two
    customers, the second customer's invoice was part-settled by the first
    customer's portion because that portion was written first.

    `txn_split_guid:` is how a file says which, and the shared-deposit
    workflow is written that way already. So this is refused for what the file
    leaves unsaid rather than judged by whose money it is — judging by owner is
    order-dependent, since a portion already settled into its own document's
    lot names an owner while a portion still loose names nobody, so the same
    file would import or not depending on what ran before it.

    Counted with `_retarget_choices`, which is what the mover picks from, so
    the two cannot disagree about what is ambiguous. Counting receivable-typed
    splits instead missed a deposit booked net of a bank fee: by that measure
    there is one receivable and no ambiguity, while the mover has two sides to
    choose between and took the 5.00 fee — a 100.00 invoice reading as settled
    by 5.00, with the receivable split left loose.

    Not every lotted split is a candidate, because most are settling a
    document and are not the mover's to take. A block that overpays divides
    its transaction and leaves the residue in a lot, so counting everything
    made the document it settled uneditable ever after: the same file, with
    anything else about the invoice changed, came back to a transaction now
    carrying two receivable splits and was refused — with the remedy reachable
    only by re-exporting.

    `candidates` is the tier `_retarget_choices` returned — worked out once by
    the caller and given to both this and the mover, so the two cannot disagree
    about what is ambiguous and the account's lot list is walked once.

    The ones that *are* candidates are counted, whether or not they are lotted.
    Counting only the loose ones left the mover's later choices unguarded: a
    transaction can carry two of an owner's credits, and with no loose split
    beside them the guard saw nothing to be ambiguous about while the mover
    took whichever came first. On a foreign book those two can carry different
    costs, so split order would decide which basis was consumed and with it the
    gain realized.
    """
    if len(candidates) < 2:
        return
    raise Exception(
        f'{kind} {doc_id}: tx {txn_guid!r} carries {len(candidates)} splits '
        f'that are not {bank_acct_name!r} and could each settle this '
        f'{kind.lower()}, and this block names only the transaction — which of '
        f'them it would move is decided by the order they happen to be in, not '
        f'by anything in the file. Add `txn_split_guid:` naming the split this '
        f'{kind.lower()} is paid by; that is how one deposit settles several '
        f'documents, and how a payment booked net of a fee says which side is '
        f'the payment.')


def _refuse_a_split_settling_another_document(record, split, kind: str,
                                              doc_id: str,
                                              named: str) -> None:
    """Refuse a named split that is already settling somebody else's document.

    The bare `txn_guid:` spelling cannot reach one — `_placeable_lotted_splits`
    leaves out any split whose lot holds a document, because moving it settles
    this document by leaving that one unpaid with every figure still balancing.
    Naming the split outright reached it unguarded, and this change set is what
    makes that the advertised route: `_why_nothing_can_move` tells the reader
    to "name it outright with `txn_split_guid:` and unpick what it is settling
    now", and the error table says the same. Unpicking is a thing to do to the
    other document first, not a thing this can do on the reader's behalf.

    This record's *own* lot is not another document: re-importing an export
    names the split already in it, and a rebuild re-attaches its own
    settlement. Only a lot holding some other document is refused.
    """
    lot = split.GetLot()
    if lot is None:
        return
    # Membership before dereference, as every other reader of a lot pointer
    # here does: `gnc_lot_remove_split` frees a lot once its listed splits run
    # out, and a split attached with `xaccSplitSetLot` is not on that list
    # (finding 9), so a split can hold a pointer the book has let go of.
    if not _lot_is_still_on_its_account(split, lot):
        return
    raw = getattr(lot, 'instance', lot)
    other = gc.gncInvoiceGetInvoiceFromLot(raw)
    if not other:
        return
    mine = record.GetPostedLot()
    if mine is not None and int(getattr(mine, 'instance', mine)) == int(
            getattr(lot, 'instance', lot)):
        return
    raise Exception(
        f'{kind} {doc_id}: the split txn_split_guid {named!r} names is in '
        f'another document\'s lot — it settles that one, and moving it here '
        f'would leave that document unpaid with every figure in the book still '
        f'balancing. Unpick it there first (re-import that document without '
        f'the payment block that claims it), or name money that is not '
        f'already spoken for.')


def _refuse_another_owners_split(record, split, kind: str, doc_id: str) -> None:
    """Refuse a split the book records as somebody else's money.

    A payment block reaches its split by guid, and a guid copied out of a
    large export says nothing about whose money it is. Attaching one owner's
    to another's document leaves that document reading as paid though nobody
    paid it, and the owner who really paid with no record of what they are
    owed — nothing in the book disagrees afterwards, because every figure in
    it still balances.
    """
    _refuse_if_not_this_owner(record, _recorded_owner_of(split), kind, doc_id,
                              'the split named by txn_split_guid')


def _apply_credit_payment_directive(record, pay_dir, book, is_bill) -> None:
    """Settle a document out of the owner's existing credit.

    Applying a credit moves no money. The currency is already in the book,
    sitting on a lot of the owner's that no document owns, and applying it is
    putting that split in this document's lot — which is what closes the lot
    and marks the document paid. So the block carries no bank account and no
    date of its own: it names the split (`txn_guid:` / `txn_split_guid:`), how
    much of the document that split settles, and the date of the transaction
    the credit arrived in, as `credit_dated:`.

    What the file states is checked rather than trusted, the way a stated cost
    or a stated balance is: the split must exist on the named transaction, be
    on this document's own posted account, carry the amount the block claims
    with the sign a credit has on that side, and still be the owner's to spend.
    """
    kind = 'Bill' if is_bill else 'Invoice'
    md = pay_dir.metadata
    doc_id = record.GetID()

    for key in ('bank_account', 'account'):
        if md.get(key):
            raise Exception(
                f'{kind} {doc_id}: a payment with `from_credit: true` names no '
                f'account — the money is already in the book, on the credit '
                f'`txn_split_guid:` names. Drop `{key}:`, or drop '
                f'`from_credit:` if a bank really paid this.')
    if md.get('date'):
        raise Exception(
            f'{kind} {doc_id}: a payment with `from_credit: true` has no date '
            f'of its own — GnuCash records none for applying a credit. Use '
            f'`credit_dated:` for the date of the transaction the credit '
            f'arrived in.')

    txn_guid = (md.get('txn_guid') or '').strip()
    split_guid_declared = (md.get('txn_split_guid') or '').strip()
    if not txn_guid or not split_guid_declared:
        raise Exception(
            f'{kind} {doc_id}: a payment with `from_credit: true` must name '
            f'the credit it spends with `txn_guid:` and `txn_split_guid:`. '
            f'Without them the file says a credit was applied without saying '
            f'which — write `auto_apply_credit: true` on the '
            f'{kind.lower()} to have any of the owner\'s credit applied.')

    lot = record.GetPostedLot()
    if lot is None:
        raise Exception(
            f'{kind} {doc_id}: has no posted lot — a credit can only be '
            f'applied to a posted {kind.lower()}')
    post_acct = record.GetPostedAcc()

    existing_tx = _find_transaction_by_guid(book, txn_guid)
    if existing_tx is None:
        raise Exception(f'{kind} {doc_id}: txn_guid {txn_guid!r} not found in book')

    try:
        target_guid = _normalise_guid(split_guid_declared)
    except Exception as exc:
        raise Exception(
            f'{kind} {doc_id}: txn_split_guid {split_guid_declared!r} is not a '
            f'valid GUID') from exc
    target_split = next(
        (s for s in existing_tx.GetSplitList()
         if s.GetGUID().to_string().replace('-', '').lower() == target_guid), None)
    if target_split is None:
        raise Exception(
            f'{kind} {doc_id}: txn_split_guid {split_guid_declared!r} not found '
            f'on tx {txn_guid!r}')

    target_acct = target_split.GetAccount()
    if (target_acct is None or post_acct is None
            or get_account_full_name(target_acct) != get_account_full_name(post_acct)):
        raise Exception(
            f'{kind} {doc_id}: the credit split lives on '
            f'{get_account_full_name(target_acct) if target_acct else None!r} '
            f'but this {kind.lower()} is posted to '
            f'{get_account_full_name(post_acct) if post_acct else None!r} — a '
            f'credit is only spendable against the account it sits on')

    stated_date = (md.get('credit_dated') or '').strip()
    if stated_date and existing_tx.GetDate().strftime('%Y-%m-%d') != stated_date:
        raise Exception(
            f'{kind} {doc_id}: `credit_dated: {stated_date}` does not match tx '
            f'{txn_guid!r}, which is dated '
            f'{existing_tx.GetDate().strftime("%Y-%m-%d")}')

    amount = numeric_to_fraction(target_split.GetAmount())
    # A credit is on the side a document is not raised on: a customer's is a
    # credit of the receivable, a vendor's a debit of the payable.
    if (amount > 0) != bool(is_bill) or amount == 0:
        raise Exception(
            f'{kind} {doc_id}: the split txn_split_guid names carries '
            f'{_account_money_str(amount, post_acct)}, which is not a '
            f'credit on {get_account_full_name(post_acct)} — a credit this '
            f'{kind.lower()} can spend is '
            f'{"a debit" if is_bill else "a credit"} of that account')

    stated_amount = (str(md.get('amount', '')) or '').strip()
    if stated_amount:
        try:
            claimed = Fraction(stated_amount)
        except (ValueError, ZeroDivisionError) as exc:
            raise Exception(
                f'{kind} {doc_id}: payment amount must be a number, got '
                f'{stated_amount!r}') from exc
        if claimed != abs(amount):
            raise Exception(
                f'{kind} {doc_id}: `amount: '
                f'{_account_money_str(claimed, post_acct)}` does not '
                f'match the credit split, which carries '
                f'{_account_money_str(abs(amount), post_acct)}. The '
                f'`amount:` says what the split holds, not what this '
                f'{kind.lower()} takes of it — a credit bigger than the '
                f'{kind.lower()} is divided, and what it took is what the '
                f'export writes back.')

    # Membership before dereference, like every other reader here — and this
    # one sits a line away from `_refuse_a_split_settling_another_document`,
    # which asks the same question of the same split under the rule.
    #
    # Both readings walk the account's lot list to answer about one split, and
    # the division that could change the answer comes after them, so the list
    # is read once for the pair.
    with _lot_membership_unchanged():
        existing_lot = target_split.GetLot()
        if (existing_lot is not None
                and _lot_is_still_on_its_account(target_split, existing_lot)
                and gc.gncInvoiceGetInvoiceFromLot(existing_lot)):
            raise Exception(
                f'{kind} {doc_id}: the split txn_split_guid names is already '
                f'in a document\'s lot — it settled that one and is not the '
                f'owner\'s to spend again')
        # The third spelling has to answer as the other two do, and this is
        # where it can be told wrong. A split an unpost orphaned looks like an
        # owner's credit from every angle — live lot, no document, the owner
        # still on it — and `find-prepayments` and the exported
        # `open_prepayment:` block both offer it as spendable, which is how a
        # reader is led to write this block about it.
        #
        # Whether it really came out of credit is on the split, written when
        # the credit was spent, and it survives the unpost. Where it says so,
        # the file is right and the rebuild proceeds: that is how a
        # credit-settled document comes back from its own export. Where it
        # does not, a bank paid this and the file is asserting something the
        # book contradicts — and that holds whichever document's unpost
        # loosened it, which is the same predicate `_sits_in_an_owners_credit`
        # asks of the same split.
        if is_a_bank_paid_orphan(target_split):
            raise Exception(
                f'{kind} {doc_id}: the split txn_split_guid names is a '
                f'settlement a bank paid, left loose when the document it '
                f'settled was unposted — no credit was spent on it. '
                f'Unposting leaves the money in a lot of the owner\'s, which '
                f'is what makes it look like a credit. Drop `from_credit:` '
                f'and name the transaction with `txn_guid:` to attach it as '
                f'the bank payment it is, or re-post the document it settled.')
        _refuse_another_owners_split(record, target_split, kind, doc_id)

    # A credit bigger than what the document still owes is divided rather than
    # attached whole. Attaching it takes the lot past zero — measured, a 50.00
    # credit on a 30.00 invoice leaves the lot at −20.00 with `IsPaid` false
    # and the customer's 20.00 gone from `find-prepayments`, which lists only
    # lots no document owns. So it is divided here, from the figures the file
    # named — through `_settle_from_one_split`, the mechanic an overpaying bank
    # transfer goes through — rather than by asking the engine, which takes no
    # instruction about which credit to spend and carves differently from one
    # version to the next.
    #
    # What is still owed, not what the document was raised for: cash blocks
    # are applied before credit ones, so a 100.00 invoice with 80.00 of cash
    # on it owes 20.00 by the time a credit block is read, and measuring
    # against the 100.00 let a 50.00 credit in whole.
    outstanding = _still_owed(record, lot, post_acct)
    if outstanding <= 0:
        raise Exception(
            f'{kind} {doc_id}: owes nothing for this credit to settle — the '
            f'payments already on it cover it in full. Attaching the credit '
            f'anyway would take its lot past zero, leaving the '
            f'{kind.lower()} neither settled nor open and the owner\'s money '
            f'inside its lot where nothing can spend it again.')
    if abs(amount) > outstanding:
        # A credit bigger than the document it settles is an overpayment by
        # another name, and takes the path an overpaying bank transfer has
        # always taken: the document is settled with what it owes, and the
        # rest becomes the owner's credit in a lot of its own. The only thing
        # this caller contributes is which split — it was named by guid, so
        # there is nothing for the mechanic to find.
        #
        # Whose money is left over has to be known before any is parked as
        # theirs. A split in no lot has no owner recorded, and where its
        # transaction pays more than one of them, none can be worked out from
        # it either — attaching the residue to this document's owner would
        # hand them a credit that may be somebody else's. Dividing whole is
        # the shape that needs it; taken whole, no new credit is invented.
        if target_split.GetLot() is None:
            raise Exception(
                f'{kind} {doc_id}: the credit named by txn_split_guid is in no '
                f'lot, so nothing in the book says whose it is — and it is '
                f'bigger than this {kind.lower()}, so what is left of it would '
                f'be parked as a credit for an owner nobody can confirm. Give '
                f'the credit its owner first, with `lot_owner:` on that split, '
                f'or name a credit that fits the {kind.lower()} whole.')
        from infrastructure.gnucash.engine import load_gnc_engine
        _settle_from_one_split(
            load_gnc_engine(), book, record, existing_tx, target_split,
            post_acct, lot, outstanding, abs(amount), kind, doc_id,
            from_credit=True)
    else:
        _attach_split_to_lot(target_split, lot)
        _mark_spent_credit(target_split)

    # Last, so that the credit left behind by a division keeps the memo it
    # arrived with rather than the one written about settling this document.
    memo = md.get('memo')
    if memo is not None:
        target_split.SetMemo(memo)


def _the_tax_table_named(book, name: str, kind: str, ident: str):
    """The tax table a line names, or a refusal.

    Swallowed, a name the book does not hold left the entry with no table —
    and the comparison that decides whether a document is up to date reads the
    name the file states against the table the entry carries, so the two could
    never agree. A posted document was then unposted, its posting transaction
    destroyed, its payments orphaned, and the whole thing rebuilt, on every
    import, reported as `updated` with no error at all.

    A line naming a table is asking for it. The book either has it or the file
    is wrong, and saying so once is cheaper than a rebuild that never settles.
    """
    raw = gc.gncTaxTableLookupByName(book.instance, name)
    if not raw:
        raise Exception(
            f'{kind} {ident!r}: tax table {name!r} is not in this book. A line '
            f'naming a table must name one the book holds — declare it with a '
            f'`taxtable "{name}"` block, or take `tax_table:` off the line.')
    return TaxTable(instance=raw)


def _the_transaction_this_record_orphaned(bank_account, record_guid: str,
                                          pay_dir=None) -> str:
    """The guid of the settlement this record's own unpost loosened, or None.

    Walked from the bank account because that is the side a payment block
    names, while the mark is written on the split the unpost loosened — the
    receivable's — so the transaction is what joins them.

    Matched on `record_guid`, not on the mark's presence: one deposit can
    settle two documents, and rebuilding the first marks that transaction
    while its other portion is still money the book independently had. Asked
    as a bare presence, the first document's mark hid the whole deposit from
    the second document's duplicate check and the second was paid again —
    measured, two extra bank transactions on a run that exited 0.

    A document settled twice out of one account has two such orphans, and the
    block has to be given its own. `pay_dir` is what says which: the figure it
    states, and the day it states it on.

    Not "whichever comes first". A retarget checks the block's figure against
    the split it would move, so a block handed the wrong movement is refused —
    `this block says 60.00 arrived, but the split it would move … carries
    40.00`, on a file that is correct. First-match happens to pair them right
    while the account's splits are in the order the document lists its
    payments, which is why this looked like it did not matter; measured by
    walking that list the other way, the correction was refused outright.

    Nothing where nothing matches. A bare retarget cannot arrive here — the
    caller asks only when the block `describes_itself`, which needs a date, an
    amount and an account — so a block reaching this and matching no orphan is
    one describing a movement neither orphan is. Handing it the first marked
    orphan anyway attached a 60.00 settlement to a block stating 55.00 and
    reported `updated`: the figure the file states, ignored in silence.
    Answering None sends it where an unresolvable guid describing a payment
    the book has not got already goes — the duplicate check, and then
    recording the payment the block describes.

    `_attach_split_to_lot` clears the mark, so a second block finds the other
    one rather than the same one twice.

    The block's own figure and date are compared before the mark is read. Every
    guard here is a plain read with no side effect, so their order does not
    change which transaction is returned — but the mark is a KVP read, one per
    split of each candidate, where the other two are a subtraction and a date.
    This runs for every payment block whose `txn_guid:` resolves to nothing,
    which is every block of a printed document read anywhere but its own book,
    and it walks the whole bank account each time.
    """
    if not record_guid:
        return None
    wanted = _bank_side_figure_of(pay_dir.metadata) if pay_dir else None
    stated_date = ((pay_dir.metadata.get('date') or '').strip()
                   if pay_dir else '')
    for split in bank_account.GetSplitList():
        transaction = split.GetParent()
        if transaction is None:
            continue
        if transaction.GetGUID().to_string() in _PAYMENTS_THIS_RUN_MADE:
            continue
        if wanted is not None and abs(numeric_to_fraction(
                split.GetAmount())) != wanted:
            continue
        if stated_date and transaction.GetDate().strftime(
                '%Y-%m-%d') != stated_date:
            continue
        if not any(_orphaned_from(other) == record_guid
                   for other in transaction.GetSplitList()):
            continue
        return transaction.GetGUID().to_string()
    return None


def _the_document_a_transaction_settles(transaction):
    """The posted document this transaction is applied to, or None.

    Read from the lot on the transaction's own receivable/payable split, which
    is where GnuCash records that a movement settled a document.

    Asked of the *document* in the lot, not of the lot: a posted document's lot
    carries no owner of its own — GnuCash attaches one when the document is
    unposted (CLAUDE.md finding 10) — so `gncOwnerGetOwnerFromLot` answers
    nothing here, and every owner-reading path in this module skips document
    lots for that reason. Measured, asking the lot: `theirs=None` on the very
    split that settles the other invoice.
    """
    import gnucash.gnucash_core_c as _gc

    from infrastructure.gnucash.utils import wrap_invoice_or_bill

    for split in transaction.GetSplitList():
        account = split.GetAccount()
        if account is None or account.GetType() not in (ACCT_TYPE_RECEIVABLE,
                                                        ACCT_TYPE_PAYABLE):
            continue
        lot = split.GetLot()
        if lot is None:
            continue
        raw = _gc.gncInvoiceGetInvoiceFromLot(getattr(lot, 'instance', lot))
        if not raw:
            continue
        return wrap_invoice_or_bill(raw)
    return None


def _settles_another_owners_document(record, transaction) -> bool:
    """Whether this transaction settles a document belonging to somebody else.

    Payments that agree on every field the guard compares are ordinary: two
    invoices for 100.00, paid into one account on one day, carrying whatever
    memo the bank line was given. That happens between two customers and it
    happens within one — a customer with two invoices out settles them as they
    come — and printed from the book they were made in, both blocks arrive
    anywhere else with guids that name nothing.

    Whose money it is decides it, and it decides it through the remedy. The
    refusal this feeds tells the reader to correct the guid to the transaction
    it found, and correcting it retargets that movement onto the document in
    hand. Between two of one owner's documents that is a real operation and may
    well be what was meant: their receipt, their invoice, applied to the wrong
    one. Across owners it is not an operation at all — customer A's receipt
    cannot settle customer B's invoice — so a match there can only be a
    coincidence of date, figure and memo, and refusing on it would offer a
    remedy that does not exist.

    Nor "settles any document at all", which looks like the simpler question
    and is the wrong one: a mistyped guid naming a movement that already
    settled *this owner's* other document is the case the guard exists for,
    and skipping every document's money let that duplicate straight through
    again — measured, two extra transactions on the third-currency shape,
    which is one customer's second document naming the first one's movement.

    False on silence, as every owner check here is: a document owned by a job
    reports as the customer behind it, so the two are not comparable, and
    money in no document's lot is what the guard is for.
    """
    owner = record.GetOwner()
    mine = (_OWNER_KINDS.get(owner.GetType()), owner.GetID())
    if mine[0] is None or not mine[1]:
        return False
    other = _the_document_a_transaction_settles(transaction)
    if other is None:
        return False
    their_owner = other.GetOwner()
    theirs = (_OWNER_KINDS.get(their_owner.GetType()), their_owner.GetID())
    if theirs[0] is None or not theirs[1]:
        return False
    return theirs != mine


def _a_transaction_matching_the_payment_block(book, pay_dir, bank_account,
                                              is_bill, record):
    """A transaction the book already holds that this payment block describes.

    Asked only where a `txn_guid:` named nothing, to tell a mistyped retarget
    from a document being rebuilt into a fresh book. The two carry the same
    fields and the same unresolvable guid; the difference is whether the money
    is already here.

    Matched on what a payment block states about the movement it names — the
    date, the amount, and the account it went through — because those are the
    three the block itself carries, and a retarget block names them precisely
    so a reader can check the guid against them. A rebuild into a fresh book
    matches nothing, so it passes through untouched.

    Returns a short description of the first match, for the refusal to quote,
    or None.
    """
    stated_date = (pay_dir.metadata.get('date') or '').strip()
    # The bank's own figure, because the bank's split is what is being
    # compared — `_bank_side_figure_of` is where the two spellings of it are
    # read, and the sibling comparison in `_single_payment_matches` reads it
    # through the same function so the two cannot answer differently again.
    wanted = _bank_side_figure_of(pay_dir.metadata)
    if not stated_date or wanted is None:
        return None

    # The memo too, and it is what makes this about *this* payment. Two
    # customers each paying 100.00 into one account on one day is ordinary,
    # and a date and an amount cannot tell them apart — so rebuilding one
    # document into a book holding the other's deposit was refused outright,
    # with the message naming somebody else's money and offering to hand-edit
    # a file this tool wrote. A payment block carries a memo to say which
    # movement it is; blocks that state none still match on the other two,
    # which is the shape a bare retarget has.
    stated_memo = (pay_dir.metadata.get('memo') or '').strip()
    account_name = get_account_full_name(bank_account)
    for split in bank_account.GetSplitList():
        transaction = split.GetParent()
        if transaction is None:
            continue
        if transaction.GetGUID().to_string() in _PAYMENTS_THIS_RUN_MADE:
            continue
        if transaction.GetDate().strftime('%Y-%m-%d') != stated_date:
            continue
        moved = numeric_to_fraction(split.GetAmount())
        if abs(moved) != wanted:
            continue
        # And which way it moved. A bill's payment sends money out and an
        # invoice's brings it in, so an outgoing 400.00 and an incoming 400.00
        # on one day are not the same movement — matched on the absolute
        # figure alone, a printed bill read into a book holding a customer's
        # deposit of the same size was refused, with a receipt named as the
        # reason a payment could not be recorded.
        if (moved < 0) != is_bill:
            continue
        if stated_memo and (split.GetMemo() or '').strip() != stated_memo:
            continue
        # And not money that already settles another owner's document.
        # Everything above can agree between two documents — two customers each
        # paying 100.00 into one account on one day, both printed elsewhere so
        # both guids name nothing, and printed blocks carry whatever memo the
        # payment had. `_PAYMENTS_THIS_RUN_MADE` excuses only what this process
        # made, so read one file at a time the second document was refused for
        # the first one's payment: `invoice INV-OTHER: … describes one it
        # already has — 'Spelling Customer' for 100.00`, naming another
        # customer's receipt as the reason this invoice could not be paid.
        #
        # Another owner's settled document is not the movement this block is
        # about, whatever the two have in common. This owner's still is — that
        # is the mistyped guid the guard exists for.
        if _settles_another_owners_document(record, transaction):
            continue
        # With its guid, because the message tells the reader to correct the
        # one in their file to this transaction's — and without it they have
        # to go and run `find-transactions` to act on a hard refusal.
        #
        # And with the document that movement is already applied to, when it is
        # applied to one. This owner's two invoices, each genuinely paid the
        # same figure on the same day with the same memo, reach here with
        # nothing left to tell them apart, and the refusal is right — the file
        # says nothing that distinguishes the two movements. What it owes the
        # reader is why: money already settling `invoice "INV-A"` is plainly
        # not this document's receipt, and the line that says so is the one
        # that sends them to `drop txn_guid:` rather than to the ledger.
        settled = _the_document_a_transaction_settles(transaction)
        applied = ''
        if settled is not None and settled.GetID():
            kind = ('bill' if settled.GetOwnerType() == _GNC_OWNER_VENDOR
                    else 'invoice')
            applied = f', already settling {kind} "{settled.GetID()}"'
        description = transaction.GetDescription() or '(no description)'
        return (f'{stated_date} {description!r} for '
                f'{_account_money_str(wanted, bank_account)} in '
                f'{account_name}{applied} (txn_guid: '
                f'{transaction.GetGUID().to_string()})')
    return None


def _apply_payment_directive(record, pay_dir, book, is_bill, fx_rates=None):
    """Apply one PAYMENT directive to an already-posted invoice or bill.

    Used by both the normal rebuild path (after entries/posted have been
    re-applied) and the Q-015 add-payment fast path (the record is still
    posted and is mutated in-place).


    For invoices, `ApplyPayment(+amount)` closes the AR lot. For bills,
    AP has the opposite sign convention so we pass `-amount`; see Q-014
    notes in `CLAUDE.md` for the accounting reasoning.
    """
    if not _is_falsy(str(pay_dir.metadata.get('from_credit', 'false'))):
        _apply_credit_payment_directive(record, pay_dir, book, is_bill)
        return

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
    # Whether the block pointed at money at all, kept because `txn_guid` is
    # cleared below when it named nothing — and what `amount:` means further
    # down turns on the difference between a block that names a movement and
    # one that describes the payment to make.
    _named_a_transaction = bool(txn_guid)
    # What the block names, read once into a local. The reattach below finds
    # the record's own settlement and the split the file names goes with the
    # guid it was written against, so both change — and they change for this
    # application, not for the directive, which is the file's record of what
    # was written.
    named_split = (pay_dir.metadata.get('txn_split_guid') or '').strip()
    # A guid names money the book may already hold, and a book that does not
    # hold it is being told about the payment for the first time — *if* the
    # block says everything needed to make it. A block that only points at a
    # transaction, naming no date or amount of its own, is a reference and
    # nothing else: a guid that resolves to nothing there is a stale or
    # mistyped reference, and it is refused as one. That is the case a printed document
    # lands in: `print-invoice` and `print-bill` name the transactions so the
    # same book relinks them rather than paying twice, and the same file read
    # into a fresh book, reconstructing from a document, has nothing to
    # relink. Refused, the two purposes were exclusive: naming the money
    # duplicated it on re-import into the same book, and not naming it left
    # the document unreadable anywhere else.
    # The account through the one resolver the rest of the file uses:
    # `account:` is the canonical key and `bank_account:` the accepted alias,
    # so asking for one spelling made the answer depend on which word the
    # writer used — the alias minted a payment, the canonical key refused the
    # run, for the same block.
    describes_itself = bool(
        pay_dir.metadata.get('date') and pay_dir.metadata.get('amount')
        and _payment_xfer_account_name(pay_dir.metadata))
    if (txn_guid and describes_itself
            and _find_transaction_by_guid(book, txn_guid) is None):
        # First: the settlement this record's own rebuild just loosened.
        #
        # A printed document carries the guids of the book it was printed
        # from, so re-imported anywhere else they name nothing. The first such
        # import records the payment from the block, which is right — the money
        # was not here. Editing a field and importing again rebuilds the
        # document, and the rebuild unposts it, which leaves that payment on
        # the bank account with its splits loose. The guid still names the
        # other book, so the second run met its own orphan: refused as money
        # already here, and a printed document could be read into a book once
        # and never corrected.
        #
        # Recording from the block instead is worse, not better — measured, the
        # correction left two bank transactions for one movement, exit 0 — so
        # what is wanted is neither refusal nor a fresh payment but the
        # reattachment the rebuild is entitled to. The mark says which
        # settlement that is (CLAUDE.md finding 10); naming its transaction
        # hands the ordinary retarget path a resolvable guid, and
        # `_retarget_choices` takes the marked orphan as its surest tier.
        #
        # The block's `txn_split_guid:` goes with the old guid — it names a
        # split in the book that printed it — so the search is by mark rather
        # than by that name.
        mine = _the_transaction_this_record_orphaned(
            bank_account, _swig_invoice_guid_str(record), pay_dir)
        if mine is not None:
            # Which movement it reattached, not merely that it did. A document
            # settled twice out of one account has two loose settlements and
            # the block does not say which is its own, so a reader checking
            # what a correction did to their book has nothing else to read —
            # and neither had a test.
            logging.info(
                'txn_guid %r names no transaction in this book; reattaching '
                'the settlement this rebuild loosened instead: %s',
                txn_guid, mine)
            _echo_note(f'note: txn_guid {txn_guid!r} names no transaction in '
                       f'this book — reattaching the settlement this rebuild '
                       f'loosened, {mine}')
            # In locals, not back into the directive. `pay_dir.metadata` is
            # the file's record of what the writer wrote, and a run that
            # substitutes its own answer into it leaves nothing able to say
            # what the ledger said — the guid written here is one GnuCash
            # minted, not one the reader can find in their file.
            named_split = ''
            txn_guid = mine
        # Otherwise, only when the money is not already here. A rebuild into a
        # fresh book and a mistyped retarget against the book that holds the
        # transaction are the same three fields and the same missing guid —
        # what tells them apart is whether the block describes something the
        # book already has. Recording it from the block regardless entered the
        # payment a second time for money that moved once, and said so in a
        # note on stderr while exiting 0.
        already = None if mine is not None else \
            _a_transaction_matching_the_payment_block(
                book, pay_dir, bank_account, is_bill, record)
        if already is not None:
            kind = 'bill' if is_bill else 'invoice'
            raise Exception(
                f'{kind} {record.GetID()}: txn_guid {txn_guid!r} names no '
                f'transaction in this book, but this payment block describes '
                f'one it already has — {already} on {bank_acct_name!r}. '
                f'Recording it would enter the same money twice. Correct the '
                f'guid to that transaction, or drop `txn_guid:` if this '
                f'payment really is a second one.')
        elif mine is None:
            # Said, not silent: a stale reference and a document being rebuilt
            # into a book that never held its bank transaction reach here
            # alike, and only the reader can tell which they meant.
            logging.warning(
                'txn_guid %r names no transaction in this book; recording the '
                'payment from the block instead', txn_guid)
            _echo_note(f'note: txn_guid {txn_guid!r} names no transaction in '
                       f'this book — recording the payment from the block')
            txn_guid = ''
            named_split = ''
    if txn_guid:
        # Retarget: existing bank tx is retargeted into the AR/AP lot
        # without `ApplyPayment` (no new tx, preserves original tx GUID
        # and KVP). Counter-split retargeting closes the lot when the
        # AR/AP-side split sum hits zero.
        #
        # The transaction already exists and already carries whatever splits it
        # was written with, so a split line here would be placed nowhere.
        _require_no_unplaced_payment_splits(
            pay_dir, 'bill' if is_bill else 'invoice',
            'it attaches an existing transaction with `txn_guid:`, which '
            'already carries its own splits',
            remedy=('Put the split(s) in that transaction — it is an ordinary '
                    'transaction and takes any number — and drop them from the '
                    'payment block.'))
        existing_tx = _find_transaction_by_guid(book, txn_guid)
        if existing_tx is None:
            raise Exception(f'txn_guid {txn_guid!r} not found in book')
        # Only where no split is named: `txn_guid:` alone retargets whichever
        # counter split the transaction carries, so a check hanging off
        # `txn_split_guid:` would be one a file walks past by writing one line
        # less, and the transaction is then all there is to judge. Where a
        # split *is* named, that split's own owner is what matters and is
        # checked below — one deposit settles documents of several owners at
        # once, each block naming its own portion, and asking the transaction
        # there refuses the second document for the first one's owner.
        #
        # A split in no lot is answered for by its transaction where that
        # transaction carries a single receivable or payable split, and by
        # nothing where it carries several — none of them can be shown to be
        # the one, which is the shared-deposit shape above. Dividing such a
        # split is refused outright, for the same absence of a lot.
        #
        # Whose money it is is asked of the split that will move, whether the
        # file named it or the retarget found it — one question, one answer.
        # Asked of the whole transaction instead, a deposit whose other portion
        # had already been settled into its own document's lot named that
        # document's owner, and the second owner's invoice was refused for the
        # first one's money though the split it would move was its own. Which
        # way round the two documents were imported decided it.
        # Worked out once and carried down. Every question below asks the same
        # one — which split would move — and answering it walks the account's
        # whole lot list, one lot per document ever posted there. Nothing
        # between here and the move changes the transaction, so asking three
        # times made an import's cost the product of its documents and the
        # book's history, which is the shape `_still_owed` exists to avoid.
        #
        # Inside the branch that uses it, and not above: a block naming its
        # split needs none of this, and every block a book's own export writes
        # names one. Worked out unconditionally, re-importing an export paid
        # for that walk on every payment block and threw the answer away.
        choices = []
        if not named_split:
            # The search and the guard on what it picked ask the same account
            # the same question, and nothing between them moves a split.
            with _lot_membership_unchanged():
                choices = _retarget_choices(existing_tx, bank_acct_name,
                                            record.GetPostedLot(), record)
                _refuse_an_ambiguous_retarget(
                    bank_acct_name, txn_guid,
                    'Bill' if is_bill else 'Invoice', record.GetID(), choices)
                moving = choices[0] if choices else None
                if moving is not None:
                    _refuse_another_owners_split(
                        record, moving, 'Bill' if is_bill else 'Invoice',
                        record.GetID())
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
        declared_split_guid = named_split
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
            # Whoever the book says that money is with, it is not spendable on
            # anybody else's document — the guids reach a split directly, and
            # a wrong pair otherwise settles this record out of another
            # owner's payment without a figure anywhere disagreeing.
            # All three read the same lot list to answer about the same split,
            # and nothing between them moves anything — so it is read once.
            with _lot_membership_unchanged():
                _refuse_another_owners_split(
                    record, target_split, 'Bill' if is_bill else 'Invoice',
                    record.GetID())
                _refuse_a_split_settling_another_document(
                    record, target_split, 'Bill' if is_bill else 'Invoice',
                    record.GetID(), declared_split_guid)

                # Read before the move, which is what takes the split out of
                # the credit. The third spelling of one settlement: naming the
                # split outright says which, not where it comes from, so a
                # guid landing on an owner's parked credit spends that credit
                # exactly as the two shorter spellings do — and the ambiguity
                # refusal sends readers here by name, so this is the route a
                # transaction carrying two credits is meant to be settled
                # through.
                spends_credit = _sits_in_an_owners_credit(target_split)
            _attach_split_to_lot(target_split, lot)
            if spends_credit:
                _mark_spent_credit(target_split)

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
                    declared_prepay = Fraction(declared_prepay_str)
                except (ValueError, ZeroDivisionError) as exc:
                    raise Exception(
                        f'prepayment field must be a number, got {declared_prepay_str!r}'
                    ) from exc
                # Find sibling splits on the same AR/AP account, not the
                # target, that are still loose. Each becomes its own
                # prepay lot. Their absolute amounts must sum to the
                # declared prepayment (defensive check).
                loose_siblings = []
                actual_prepay = Fraction(0)
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
                    actual_prepay += abs(numeric_to_fraction(raw_sp.GetAmount()))
                    if raw_sp.GetLot() is None:
                        loose_siblings.append(raw_sp)
                if actual_prepay != declared_prepay:
                    raise Exception(
                        f'declared `prepayment: {declared_prepay_str}` does not '
                        f'match the residual AR/AP splits on tx {txn_guid!r} '
                        f'(sum of loose siblings = '
                        f'{_account_money_str(actual_prepay, post_acct)})'
                    )
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
        # absolute amount = bank-side amount. If it exceeds what the record
        # still owes the user is asking us to overpay; that requires the
        # `prepayment:` field on the directive (we will not silently leave the
        # lot in an overpaid state).
        # The same tier worked out above, not asked again: nothing since has
        # touched the transaction, and the `txn_split_guid:` branch that could
        # have moved a split has already returned.
        counter_split = choices[0] if choices else None
        counter_amount_abs = (
            abs(numeric_to_fraction(counter_split.GetAmount()))
            if counter_split is not None else None)
        # Not `lot.get_balance()`: a lot does not count a split attached with
        # `xaccSplitSetLot` until the book has been written and read back, and
        # that is how an earlier `txn_guid:` block on this same document
        # attached its own. Two retargeted cash blocks would each be measured
        # against the whole total, and the second would read as an overpayment
        # of everything the first had already paid.
        invoice_remaining_abs = _still_owed(record, lot, post_acct)

        # Asked before the split is moved, and of both figures at once: the
        # money this file describes may have been divided or spent since it was
        # written, leaving a smaller split of the same transaction to be found
        # in its place.
        if counter_amount_abs is not None:
            _refuse_a_payment_that_would_fall_short(
                pay_dir.metadata, counter_amount_abs, invoice_remaining_abs,
                post_acct, 'Bill' if is_bill else 'Invoice',
                record.GetID(), txn_guid, counter_split.GetAccount())

        # Exact figures, so "more than the record has left" is a plain
        # comparison rather than one carrying an epsilon.
        if counter_amount_abs is not None and \
                counter_amount_abs > invoice_remaining_abs:
            # Asked before any residual is worked out. A lot can already be
            # past zero — `txn_split_guid:` names a split outright and attaches
            # it without comparing it to what is owed — and a negative
            # outstanding turns the arithmetic below into nonsense: what the
            # payment can take reads as less than nothing, so the residual
            # comes out larger than the transaction, and the message quotes
            # both. Nothing owed and less than nothing owed are the same
            # answer to the same question.
            _refuse_if_nothing_owed(invoice_remaining_abs,
                                    'Bill' if is_bill else 'Invoice',
                                    record.GetID())
            # What is left over is what the payment does not take, and what it
            # takes is floored to the unit the account is kept to — the same
            # figure `_settle_from_one_split` will apply. Subtracting the
            # unfloored amount states a residual the book does not create: on a
            # receivable kept to the tenth, 50.00 against 30.05 owed declares
            # 19.95 and parks 20.00.
            # Asked before the residual is worked out, so a reader is told the
            # real obstacle rather than sent to declare a `prepayment:` that is
            # accepted here and refused at the point of applying it.
            expected_prepay = counter_amount_abs - _refuse_if_below_the_accounts_unit(
                invoice_remaining_abs, post_acct,
                'Bill' if is_bill else 'Invoice', record.GetID())
            raw_declared = pay_dir.metadata.get('prepayment')
            declared_str = '' if raw_declared is None else str(raw_declared).strip()
            kind = 'bill' if is_bill else 'invoice'
            if not declared_str:
                raise Exception(
                    f'tx {txn_guid!r} amount '
                    f'{_account_money_str(counter_amount_abs, post_acct)} '
                    f'exceeds {kind} remaining '
                    f'{_account_money_str(invoice_remaining_abs, post_acct)}; '
                    f'add `prepayment: '
                    f'{_account_money_str(expected_prepay, post_acct)}` to the payment '
                    f'block to accept the residual as a pre-payment credit, '
                    f'or retarget a bank tx whose counter-split matches the '
                    f'{kind}\'s outstanding amount exactly.'
                )
            try:
                declared = Fraction(declared_str)
            except (ValueError, ZeroDivisionError) as exc:
                raise Exception(
                    f'prepayment field must be a number, got {declared_str!r}'
                ) from exc
            if declared != expected_prepay:
                raise Exception(
                    f'declared `prepayment: {declared_str}` does not match the '
                    f'computed residual '
                    f'{_account_money_str(expected_prepay, post_acct)} '
                    f'(tx counter-split '
                    f'{_account_money_str(counter_amount_abs, post_acct)} − '
                    f'{_account_money_str(_takeable_from(invoice_remaining_abs, post_acct), post_acct)} '
                    f'this payment can take of the {kind}\'s '
                    f'{_account_money_str(invoice_remaining_abs, post_acct)} '
                    f'outstanding).'
                )
            _settle_from_one_split(
                lib, book, record, existing_tx, counter_split, post_acct, lot,
                invoice_remaining_abs, counter_amount_abs,
                kind.capitalize(), record.GetID(),
                from_credit=_sits_in_an_owners_credit(counter_split))
            return

        if counter_split is None:
            raise _why_nothing_can_move(
                existing_tx, bank_acct_name, txn_guid,
                'Bill' if is_bill else 'Invoice', record.GetID())

        # Exact or partial retarget: the whole split moves.
        #
        # A `prepayment:` stated on this branch is not checked, and that is not
        # an oversight. Nothing is being parked here — the split covers what is
        # owed and no more — so there is no figure of this import's making to
        # compare it against. The one file that states it and lands here is a
        # rebuilt overpaid document, whose residue was parked by the run that
        # first read it and is still where that run left it; the figure is
        # right, and it is the export that recomputes it. The overpaying branch
        # above checks strictly because there it says what this import is about
        # to create.
        #
        # Read before the move, which is what takes the split out of the credit.
        spends_credit = _sits_in_an_owners_credit(counter_split)
        _retarget_counter_split_to_lot(lib, existing_tx, counter_split,
                                       post_acct, lot)
        if spends_credit:
            _mark_spent_credit(counter_split)
        return

    pay_date = datetime.strptime(pay_dir.metadata['date'], "%Y-%m-%d")
    amount_str = pay_dir.metadata['amount']
    memo = pay_dir.metadata['memo']
    num = pay_dir.metadata.get('num', '')
    # What `amount:` means depends on whether the block points at money.
    #
    # A block naming a transaction states this document's own *slice* of it —
    # it has to, because one deposit can settle several documents and the bank
    # figure would over-report every one of them — and `prepayment:` states
    # what that movement left over. A block naming none states the payment to
    # make, and `prepayment:` declares what it will leave; twenty-odd fixtures
    # here are written that way and are unaffected.
    #
    # So rebuilding a block of the first kind, where the guid named nothing,
    # means making the whole movement: the slice plus the residue. Read as the
    # payment itself, a printed 250.00 deposit against a 100.00 invoice entered
    # 100.00 — the bank short by 150.00, the owner's credit never created —
    # and once the printed block stated its residue, the same file was refused
    # outright for declaring a residue its own payment could not leave.
    if _named_a_transaction and str(
            pay_dir.metadata.get('prepayment', '')).strip():
        posted_account = record.GetPostedAcc()
        residue = stated_money(
            pay_dir.metadata['prepayment'], record.GetCurrency(),
            f'the prepayment on this {"bill" if is_bill else "invoice"}',
            scu=(posted_account.GetCommoditySCU()
                 if posted_account is not None else None))
        whole = numeric_to_fraction(stated_money(
            amount_str, record.GetCurrency(),
            f'the payment amount on this {"bill" if is_bill else "invoice"}',
            scu=(posted_account.GetCommoditySCU()
                 if posted_account is not None else None))
        ) + numeric_to_fraction(residue)
        amount_str = money_text(
            whole,
            (posted_account.GetCommoditySCU()
             if posted_account is not None else None)
            or record.GetCurrency().get_fraction())
    # Judged against the currency, like every other booked amount. This is the
    # figure that settles the document, stated in the document's own currency,
    # and it was the last place the rule was not applied: `18.191` on a split
    # line is refused, and the same figure on this line was taken, rounded by
    # GnuCash to 18.19 on the way into the splits, and reported `Errors: 0` —
    # so the invoice was settled by a figure the file never stated and the
    # next export wrote 18.19 back. Measured.
    #
    # `string_to_gnc_numeric_quantity` still does the parsing, because the
    # sign handling below and `ApplyPayment` are built around it; this only
    # refuses first.
    #
    # Against the receivable's own unit as well as the currency's, because
    # that is the account the settling split lands on and is stored at. Left
    # to the currency alone, `amount: 18.19` on a receivable kept to whole
    # dollars gave amount 18 against value 18.19 on a same-currency split,
    # and the export wrote `amount: 18` back — the account arm of the check
    # exists for exactly that and never ran here.
    _posted = record.GetPostedAcc()
    stated_money(
        amount_str, record.GetCurrency(),
        f'the payment amount on this {"bill" if is_bill else "invoice"}',
        scu=_posted.GetCommoditySCU() if _posted is not None else None)
    if is_bill:
        amount = string_to_gnc_numeric_quantity(f'-{amount_str}')
    else:
        amount = string_to_gnc_numeric_quantity(amount_str)
    exchange = _payment_exchange_rate(record, bank_account, pay_dir, is_bill)
    lot_before = _lot_transaction_guids(record)
    # Pass txn=None: GnuCash creates the payment transaction internally.
    # Passing a manually-allocated Transaction causes a segfault on
    # GnuCash 3.8 (ubuntu20) because the tx is not initialised before
    # ApplyPayment uses it.
    record.ApplyPayment(None, bank_account, amount, exchange, pay_date, memo, num)
    # Noted as this run's, so a later block in the same file does not meet it
    # and read it as money the book already had. Found through the lot, which
    # is where `ApplyPayment` just put it.
    settled = _settlement_transaction_in(record, lot_before)
    if settled is not None:
        _PAYMENTS_THIS_RUN_MADE.add(settled.GetGUID().to_string())
    _check_declared_prepayment(
        record, pay_dir, lot_before, 'bill' if is_bill else 'invoice')
    _book_payment_fx_difference(record, book, pay_dir, bank_account, is_bill,
                                lot_before, fx_rates)
    _record_overpaid_basis(record, lot_before)


def _carried_cost_of(record):
    """What this record's own posting priced its currency at, or None.

    The figure a credit left by overpaying it is worth: the payment itself
    states no base-currency amount when it is made in the record's own
    currency, so there is nothing in it to divide, and the posting is the only
    place the book says what that currency cost.

    None for a record in the book's own currency, which has no cost to carry.
    """
    currency = record.GetCurrency()
    if currency is None or currency.get_mnemonic() == BASE_CURRENCY:
        return None
    posted_account = record.GetPostedAcc()
    posting_txn = record.GetPostedTxn()
    if posted_account is None or posting_txn is None:
        return None
    posted_name = get_account_full_name(posted_account)
    for split in posting_txn.GetSplitList():
        if get_account_full_name(split.GetAccount()) == posted_name:
            return cost_of(split)
    return None


def _check_declared_prepayment(record, pay_dir, lot_before, kind) -> None:
    """What the block says is left over has to be what is left over.

    `prepayment:` states the credit a payment beyond the document leaves
    behind. On the `txn_guid:` routes this tool carves the residue itself and
    compares the figure exactly; on this one GnuCash carves it, and nothing
    read the declaration at all — so `prepayment: 50` on a payment that left
    100.00 imported with `Errors: 0` and the next export wrote `prepayment:
    100.00` back. The identical misstatement written the other way is
    refused. One file, two answers, decided by which spelling was used.

    Read after `ApplyPayment` because that is what makes the splits, and
    before anything is drawn down, so a refusal costs nothing.
    """
    declared = pay_dir.metadata.get('prepayment')
    if declared is None or str(declared).strip() == '':
        # Silence is allowed here, and deliberately: on this route `amount:`
        # already says how much is paid and GnuCash carves the residue from
        # it, so an overpayment needs no second figure to be unambiguous.
        # Twenty-odd fixtures across the suite express an overpayment exactly
        # that way. The `txn_guid:` route demands the declaration because
        # there *this* tool divides an existing split and has to be told where
        # to cut — a different question with the same key.
        #
        # Answered before the lot is walked, which is the common case paying
        # for a figure it then discards.
        return

    posted_account = record.GetPostedAcc()
    lot = record.GetPostedLot()
    if posted_account is None or lot is None:
        return
    payment_txn = _settlement_transaction_in(record, lot_before)
    if payment_txn is None:
        return

    posted_name = get_account_full_name(posted_account)
    in_lot = {split_guid(Split(instance=raw)) for raw in lot.get_split_list()}
    left_over = sum(
        (abs(numeric_to_fraction(split.GetAmount()))
         for split in payment_txn.GetSplitList()
         if split.GetAccount() is not None
         and get_account_full_name(split.GetAccount()) == posted_name
         and split_guid(split) not in in_lot),
        Fraction(0))

    # Through `stated_money`, so the figure is judged against the currency
    # and the account it will sit on, like every other booked amount here.
    stated = numeric_to_fraction(stated_money(
        declared, record.GetCurrency(), f'the prepayment on this {kind}',
        scu=posted_account.GetCommoditySCU()))
    if stated != left_over:
        raise Exception(
            f'this {kind} payment declares `prepayment: {declared}` but '
            f'leaves {_account_money_str(left_over, posted_account)} over — '
            f'the payment settles what the {kind} owes and the rest becomes '
            f'the owner\'s credit, so the two have to agree. State the figure '
            f'the payment actually leaves, or change the amount it pays.')


def _record_overpaid_basis(record, lot_before) -> None:
    """Open a basis for the currency an overpayment leaves in the book.

    A payment beyond the record puts two splits on the A/R or A/P account: the
    part that settles it, in the record's lot, and the credit left over, in a
    lot of its own. The bank holds both, so both are currency the book can
    sell — the credit being a borrowing, held and owed back.

    For the payment GnuCash writes itself, which is the caller here: the
    splits it made are found by walking the record's lot. A payment this tool
    divides has its residue in hand and writes to it directly — a retargeted
    split is in a lot for every purpose except `gnc_lot_get_split_list`, which
    does not see it until the book is written and read back.
    """
    lot = record.GetPostedLot()
    if lot is None:
        return
    basis_cost = _carried_cost_of(record)
    if basis_cost is None:
        return
    posted_account = record.GetPostedAcc()
    posted_name = get_account_full_name(posted_account)

    # Only the payment just made, and only its splits. Walking the whole
    # account reaches every other record's settlement split on it — none of
    # them in this record's lot — and stamps them with this record's cost:
    # two ordinary foreign invoices sharing one A/R account had the second
    # payment open a phantom basis on the first invoice's settling split, and
    # the book claimed 400.00 USD sellable while the bank held 300.00.
    payment_txn = None
    for raw in lot.get_split_list():
        parent = Split(instance=raw).GetParent()
        if parent is not None and parent.GetGUID().to_string() not in lot_before:
            payment_txn = parent
            break
    if payment_txn is None:
        return

    settled = {split_guid(Split(instance=raw)) for raw in lot.get_split_list()}
    for split in payment_txn.GetSplitList():
        account = split.GetAccount()
        if account is None or get_account_full_name(account) != posted_name:
            continue
        if split_guid(split) in settled:
            continue                 # the part that settled the record
        record_borrowed_basis(split, basis_cost)


def _still_owed(record, lot, post_account) -> Fraction:
    """What this document still owes, counting every payment already on it.

    Its total less what has been paid. The total is the starting point rather
    than the lot's balance because a document whose posting transaction is
    attached rather than freshly posted has not joined that lot yet.

    What has been paid comes from the lot's own splits, which is cheap and is
    right for every payment GnuCash wrote — until this import attaches one
    with `xaccSplitSetLot`, which puts the split in the lot without adding it
    to that list (CLAUDE.md finding 9). For those lots, and only those, the
    account is walked instead and each split asked which lot it is in.

    Measured, asking only the lot: a 100.00 invoice carrying an 80.00
    retargeted cash block and a 50.00 credit block read as owing its whole
    100.00 when the credit was applied, so the credit was attached whole
    instead of divided — the lot at −30.00 with `IsPaid` false, and the
    customer's 50.00 inside a lot they cannot spend from. Cash blocks are
    applied before credit ones precisely so the credit takes what is left, and
    how the cash arrived cannot be allowed to change that figure.

    The account walk is not free: `GetSplitList()` builds a fresh wrapper for
    every split on the account each time it is called, and a receivable
    carries the whole history of the business. Paying it once per payment
    block on every document would make an import's cost the product of the two
    — so it is paid only where the cheap answer is known to be wrong, which is
    the handful of lots `_attach_split_to_lot` has touched in this run.
    """
    posting_txn = record.GetPostedTxn()
    posting_guid = posting_txn.GetGUID().to_string() if posting_txn else None
    # What the posting actually put on the account, which on one kept coarser
    # than the document's total is not that total. Falling back to the total
    # where there is no posting split to read — a document whose posting
    # transaction is attached rather than freshly posted reaches here before
    # one exists, and the two agree wherever the account can hold the total.
    posted = _posting_amount_of(record, post_account)
    owed = abs(posted) if posted is not None else abs(
        numeric_to_fraction(record.GetTotal()))

    # Signed, against the direction the posting went. A payment carries the
    # opposite sign to the posting and reduces what is owed; anything carrying
    # the *same* sign — an adjustment raised against the document rather than
    # against a credit lot — adds to it. Summing absolute amounts reads that
    # second kind as a payment and reports the document as owing less than it
    # does, so a later payment would be taken for an overpayment it is not.
    # No file in this tree produces one today, which is why the arithmetic is
    # written to be right rather than guarded by a test.
    toward_settlement = -1 if (posted is None or posted >= 0) else 1

    def _reduction(split):
        parent = split.GetParent()
        if parent is not None and parent.GetGUID().to_string() == posting_guid:
            return Fraction(0)          # the posting itself is not a payment
        return toward_settlement * numeric_to_fraction(split.GetAmount())

    for split in _everything_the_lot_holds(lot, post_account):
        owed -= _reduction(split)
    return owed


def _posting_amount_of(record, post_account):
    """What this document's posting put on its receivable or payable, signed.

    The figure every payment on the lot has to cancel. It is the document's own
    total wherever the account can hold that total, which posting now requires
    — but it is read from the split rather than assumed, because the split is
    what the lot contains and what a payment has to sum to zero against. The
    sign comes with it: an invoice debits the receivable and a bill credits the
    payable, and that is what tells the caller which way a payment counts.

    None where there is no posting split to read. Both callers reach this only
    for a record whose posted lot exists, which implies a posting transaction,
    so this is the answer to a question the callers do not ask — kept because
    returning a figure derived from nothing would be worse than saying nothing,
    and the caller falls back to the document's total.
    """
    posting_txn = record.GetPostedTxn()
    if posting_txn is None or post_account is None:
        return None
    posted_name = get_account_full_name(post_account)
    for split in posting_txn.GetSplitList():
        account = split.GetAccount()
        if account is not None and get_account_full_name(account) == posted_name:
            return numeric_to_fraction(split.GetAmount())
    return None


def _lot_transaction_guids(record) -> set:
    """The transactions currently in this record's posted lot.

    `gnc_lot_get_split_list` hands back raw pointers, so each one is wrapped
    before use — a bare SwigPyObject has no Split methods.
    """
    lot = record.GetPostedLot()
    if lot is None:
        return set()
    guids = set()
    for raw in lot.get_split_list():
        parent = Split(instance=raw).GetParent()
        if parent is not None:
            guids.add(parent.GetGUID().to_string())
    return guids


def holdable_unit(commodity, scu: int) -> int:
    """The smallest unit a figure on this account has to be a whole number of.

    The coarser of the account's own unit and the currency's, because the
    figure has to survive both: judged against the account alone, a
    `commodity_scu: 1000` account accepted 18.191 CAD and the amount then sat
    at the account's unit while its value was rounded to the currency's — one
    split carrying two figures for one sum. Judged against the currency alone,
    a book kept to whole dollars took 18.19.

    A security is held to the account's unit alone. It is counted in units, not
    converted, so its account is the only authority for how finely it divides —
    a fund declared `fraction: 100` and kept to thousandths holds 12.345 units,
    and taking the coarser of the two would call that unholdable.

    The currency's unit is what the book will still hold *after the save*, not
    what this run's file restated the commodity to. GnuCash writes an ISO
    currency by code and looks its fraction up again on the way back in, so a
    finer one declared in a file lasts only as long as the import — and read
    here it was a rule the file could widen its way past.

    One function because there were three copies of this and they disagreed.
    Two were corrected for the widened fraction and the third was not, so a
    file stating a whole-cent `amount:` and a `cost_basis_balance: "60.001"`
    behind `fraction: 1000` was accepted, and the reopened book held a balance
    it could not express: displayed rounded, unremarked by `--verify-costs`,
    and written back out into a file the importer then refuses.
    """
    if commodity is None:
        return scu
    if (commodity.get_namespace() or '').upper() != 'CURRENCY':
        return scu
    return min(scu, _PERSISTED_CURRENCY_FRACTION.get(
        commodity.get_mnemonic(), commodity.get_fraction()))


def stated_money(text, commodity, what: str, scu: int = None) -> GncNumeric:
    """A money amount the file states, refused when its currency cannot hold it.

    2.005 CAD is half a cent. Truncating it to 2.00 — which is what building
    the numeric as `int(Decimal(s) * fraction)` does — books a figure nobody
    wrote, and leaves `$residual$` absorbing the missing half cent into a
    second one. A figure the file states is honoured or refused, never
    adjusted; only a *computed* figure is rounded, by GnuCash, because there is
    no stated number to honour.

    A rate is not money and is not passed through here: it has no smallest unit
    and legitimately carries more decimals than the currency does.

    `scu` is the account's own smallest unit where the caller knows it, which
    is not always the currency's: GnuCash stores a unit per account and this
    tool round-trips it as `commodity_scu:`. It is what the figure is finally
    *stored* at, and the figure is judged against whichever of the two is
    coarser, so it has to survive both.

    Both directions matter and each was got wrong on its own. Judged against
    the account alone, a `commodity_scu: 1000` account accepted 18.191 — the
    amount then sat at the account's unit while its value was rounded to the
    currency's, one split carrying two figures for one sum. Judged against the
    currency alone, an account kept to whole dollars accepted 18.19 and
    `to_money` rounded it to 18, leaving the counterpart split at 18.19 and
    GnuCash parking the difference in Imbalance-CAD. Both were measured, and
    both reported `Errors: 0`.
    """
    raw = str(text).replace(',', '.').strip()
    try:
        value = Fraction(raw)
    except (ValueError, ZeroDivisionError) as exc:
        raise Exception(f'{what} must be a number, got {text!r}') from exc
    # No null-commodity fallback. The refusal below reads the commodity's
    # mnemonic and its fraction without asking, so one of the two was wrong —
    # and a fallback that only holds until the figure is refused is the worse
    # half: it turns the message this exists to print into an AttributeError.
    # An account carries a commodity; nothing in this tree makes one that
    # does not.
    if scu is None:
        scu = commodity.get_fraction()
    # Judged against the *currency*, whatever unit the account is kept to.
    # GnuCash lets an account hold a finer figure than its commodity has;
    # this tool does not follow it there. `18.190` passes — it is `18.19`
    # with a trailing zero, and scales to 1819 hundredths exactly — while
    # `18.191` is refused.
    #
    # What the account's own unit bought was a book GnuCash could not keep
    # straight: the amount was stored at the account's finer unit and the
    # value at the currency's, so a split in the transaction's own currency
    # came out with an amount of 18.191 against a value of 18.190 and an
    # invented rate of 1819000/1819100 between CAD and CAD. Nothing caught
    # it — both splits were wrong by the same factor in opposite directions,
    # so the values still summed to zero, and the value sum is all anything
    # checks. Measured on GnuCash 5.10: `Errors: 0`, and saved.
    # Against whichever unit is *coarser*, because the figure has to survive
    # both. The currency, so a finer `commodity_scu:` cannot smuggle a tenth
    # of a cent past as money. And the account, because that is what the
    # amount is finally stored at: an account kept to whole dollars rounds
    # 18.19 to 18 on the way in, the counterpart split keeps 18.19, and
    # GnuCash parks the 0.19 in Imbalance-CAD — measured, with the summary
    # reporting `Errors: 0`. Judging only the currency lets that through.
    # Only money is judged against its commodity's unit. A security is not
    # money — fund units are quoted to three decimals and more — so a quantity
    # is held to the account's unit alone, the same line `string_to_gnc_
    # numeric` draws for the beancount path and that `establishes_cost_basis`
    # and `_check_stated_balances` draw for theirs. Judged as money, a FUND
    # declared `fraction: 100` on an account kept to thousandths refused
    # `12.345` units with a message calling them "not money this book can
    # record", which is true and beside the point.
    is_currency = (commodity is not None
                   and (commodity.get_namespace() or '').upper() == 'CURRENCY')
    holdable = holdable_unit(commodity, scu)
    if (value * holdable).denominator != 1:
        # Which unit it failed against, and only a currency can fail against
        # the currency's — a security is judged by the account alone, so
        # `12.3456` FUNDX on an account kept to thousandths must be told to
        # round to 0.001, not handed the currency's 0.01 and called "not
        # money this book can record". Both claims would be false for it:
        # three decimals are legal here, and fund units are not money.
        #
        # The currency's own unit through the same reader the rule used, so
        # the figure named here is the one the figure was judged against.
        currency_scu = holdable_unit(commodity, commodity.get_fraction())
        finer_than_currency = (is_currency
                               and (value * currency_scu).denominator != 1)
        raise Exception(
            f'{what} states {raw} {commodity.get_mnemonic()}, which is finer '
            f'than '
            + (f'that currency: its smallest unit is '
               f'{money_text(Fraction(1, currency_scu), currency_scu)}, and a '
               f'booked amount is a whole number of those. A trailing zero is '
               f'fine — 18.190 is 18.19 — but a figure that needs the extra '
               f'digit is not money this book can record.'
               if finer_than_currency else
               f'that account is kept to: its smallest unit is '
               f'{money_text(Fraction(1, scu), scu)}. Round the figure, or '
               f'give the account a smaller unit — `commodity_scu:` in '
               f'plaintext, `gnucash-scu:` in beancount.'))
    return to_money(value, scu)


def _basis_figures_in_book(existing_tx):
    """What a cost basis depends on, as the book holds it: which account each
    split is on, the amount it moves, the value it moves, and the basis it
    picks. Memos, descriptions, actions and dates are absent because none of
    them can change what a basis holds or what it cost."""
    rows = []
    for split in existing_tx.GetSplitList():
        account = split.GetAccount()
        rows.append((
            get_account_full_name(account) if account is not None else '',
            numeric_to_fraction(split.GetAmount()),
            numeric_to_fraction(split.GetValue()),
            numeric_to_fraction(split.GetSharePrice()),
            (cost_basis_guid_of(split) or '').replace('-', '').lower(),
        ))
    return sorted(rows, key=lambda row: (row[0], row[1], row[2], row[3], row[4]))


def _basis_figures_in_directive(directive, booked):
    """The same figures as the incoming version states them.

    A split that states no `value:` is compared on its booked value, since the
    file is not restating it — only what the file actually says is treated as
    a change.
    """
    booked_values = {(row[0], row[1]): row[2] for row in booked}
    booked_rates = {(row[0], row[1]): row[3] for row in booked}
    rows = []
    for child in directive.children:
        if child.type != DirectiveType.SPLIT:
            continue
        account = str(child.props.get('account', ''))
        raw_amount = str(child.props.get('amount', ''))
        if raw_amount == RESIDUAL_AMOUNT:
            # Unresolvable here, and it would change the amount by definition.
            return None
        try:
            amount = Fraction(raw_amount.replace(',', '.'))
        except (ValueError, ZeroDivisionError):
            return None
        stated_value = child.metadata.get('value')
        if stated_value is None:
            value = booked_values.get((account, amount))
            if value is None:
                return None
        else:
            try:
                value = Fraction(str(stated_value).replace(',', '.'))
            except (ValueError, ZeroDivisionError):
                return None
        # The rate counts as much as the value. `SetSharePrice` runs after
        # `SetValue` on the update path and recomputes value = amount × price,
        # so editing `share_price:` alone moves the figure `cost_of` derives a
        # basis from — 1.35 re-priced to 2.00 CAD/USD while the guard saw
        # nothing move.
        stated_rate = child.metadata.get('share_price')
        if stated_rate is None:
            rate = booked_rates.get((account, amount))
            if rate is None:
                return None
        else:
            try:
                rate = Fraction(str(stated_rate).replace(',', '.'))
            except (ValueError, ZeroDivisionError):
                return None
        picked = str(child.metadata.get(COST_BASIS_SPLIT_KEY) or '')
        rows.append((account, amount, value, rate,
                     picked.replace('-', '').lower()))
    return sorted(rows, key=lambda row: (row[0], row[1], row[2], row[3], row[4]))


def _stated_txn_type(directive) -> str:
    """The `txn_type:` this directive states, checked. `''` when it states none.

    Read before anything is written, like a stated cost: knowing whether a
    character is one GnuCash uses takes only the character, so there is no
    reason for the answer to arrive after a transaction has been rewritten and
    its splits attached to lots. An unset field arrives as `N` or, from an
    export older than this, as a NUL byte; neither states anything.
    """
    stated = str(directive.metadata.get('txn_type', '')).strip()
    if not stated or stated in ('N', '\x00'):
        return ''
    # GnuCash knows three: an invoice/bill posting, a payment, a link. A
    # character it does not know would land in engine state and export back
    # out, so a typo would become permanent rather than staying inert.
    if stated not in ('I', 'P', 'L'):
        raise Exception(
            f'txn_type: {stated!r} is not one of I (posting), P (payment) or '
            f'L (link)')
    return stated


def _restore_txn_type(transaction, directive) -> None:
    """Put a stated `txn_type:` back on the transaction itself.

    A payment exports as `txn_type: P`; restored as a KVP alone it left the
    engine field unset, so a re-imported payment was no longer a payment to
    anything that asks GnuCash — `find-orphan-payments` among them — and the
    next export wrote the unset field back out as a NUL byte. Both the create
    and the update path go through here, or the two disagree about what a
    re-imported payment is.
    """
    stated = _stated_txn_type(directive)
    if not stated:
        return
    # Through SWIG, the way this module already sets a payment's type
    # elsewhere — no ctypes, and no argtypes to declare on a shared handle.
    gc.xaccTransSetTxnType(transaction.instance, stated)


def _require_no_cost_basis_edit(existing_tx, directive) -> None:
    """Refuse an in-place edit that would move what a cost basis rests on.

    Only the figures matter. A memo, a description, an action, a date, a
    doc_link — none of them can change what a basis holds or what it cost, so
    editing those on a transaction that touches a basis is ordinary and goes
    through. Changing an amount, a value, an account or the basis a split
    picks does change it, and cannot be checked from here: the rules that
    govern a sale run over a transaction's splits once they are book state,
    and an in-place edit has already overwritten what the old amounts drew
    before anything can re-check them. Left alone, that accepted a sale of
    400.00 USD against a basis holding 60.00, reported `Updated: 1`, and left
    the basis still reading 60.00.

    Deleting the transaction and importing it afresh is the route that works,
    and reaches the same end state: deleting a sale gives the basis back
    exactly what that sale took, and the new import runs every check.
    """
    involved = any(establishes_cost_basis(split) or cost_basis_guid_of(split)
                   for split in existing_tx.GetSplitList())
    picks_a_basis = any(
        child.type == DirectiveType.SPLIT and child.metadata.get(COST_BASIS_SPLIT_KEY)
        for child in directive.children)
    if not involved and not picks_a_basis:
        return

    booked = _basis_figures_in_book(existing_tx)
    incoming = _basis_figures_in_directive(directive, booked)
    if incoming is not None and incoming == booked:
        return          # nothing a basis rests on has moved

    guid = existing_tx.GetGUID().to_string()
    raise Exception(
        f'transaction {guid} touches a cost basis, so its amounts, values, '
        f'accounts and basis picks cannot be edited in place — a memo or '
        f'description can. Delete it and import the new version instead: '
        f'`delete-transactions --by-guid {guid.replace("-", "")}` gives the '
        f'basis back exactly what this transaction took, and the fresh import '
        f'checks the new figures against it.')


APPLIED_FROM_CREDIT_KEY = 'applied_from_credit'


def _splits_in_lot(record):
    """The guids of everything in this document's posted lot, or an empty set.

    Taken before a credit is applied and compared with the same walk after,
    it says which splits the application put there — which nothing else in
    the book records.
    """
    lot = record.GetPostedLot()
    if lot is None:
        return set()
    return {Split(instance=raw).GetGUID().to_string()
            for raw in lot.get_split_list()}


def _mark_applied_from_credit(record, lot_before) -> list:
    """Record on each split that it settled this document out of credit.

    Whether a payment was a bank payment or a credit applied afterwards is
    not a question the book can be asked later. Once applied, a consumed
    credit's split sits in the document's lot exactly as a bank payment's
    split does, and GnuCash keeps no record of the lot it came from — so a
    reader is left inferring it, and on the day a deposit is taken and an
    invoice raised against it there is nothing left to infer from.

    The tool knows, because it is the one applying it. What it knows it
    writes down, on the splits the application moved into this lot, and the
    export reads that rather than guessing.

    Returns the splits it marked.
    """
    lot = record.GetPostedLot()
    if lot is None:
        return []
    marked = []
    for raw in lot.get_split_list():
        split = Split(instance=raw)
        if split.GetGUID().to_string() in lot_before:
            continue
        # `AutoApplyPayments` searches for open, documentless, owner-attached
        # lots, which is exactly what an unpost leaves behind — this record's
        # own, so a rebuilt document can be handed back the settlement it
        # already had, or another document's, which the engine will take just
        # as readily since both name the same owner. Either way a bank paid
        # that money and no credit was spent: marking it would call a bank
        # payment a credit applied and take the account and the date it came
        # from out of the export.
        #
        # The same question `_sits_in_an_owners_credit` and
        # `_apply_credit_payment_directive` ask of the same split — how the
        # money was paid, not whose orphan it is.
        if is_a_bank_paid_orphan(split):
            # It is in a document's lot now, so it is a settlement again — and
            # the engine's own `gnc_lot_add_split` put it there, which is the
            # one route into a lot that does not pass `_attach_split_to_lot`.
            # Cleared here or the split sits in a document's lot still calling
            # itself an orphan.
            #
            # A settlement holds no basis either, whatever brought it here. No
            # route has been found that marks a split carrying one — the
            # residue `record_borrowed_basis` writes to lands in a fresh owner
            # lot, never the posted one — so this is the rule stated rather
            # than a defect corrected, and it costs one dict comprehension not
            # to depend on that staying true.
            _strip_a_settlements_basis(split)
            _forget_orphaned_by_unpost(split)
            continue
        transaction = split.GetParent()
        if transaction is None:
            continue
        # Read through the normaliser, so a balance written under its
        # pre-rename name is one of the keys dropped below rather than the one
        # key that survives being spent.
        metadata = cost_basis_metadata(split)
        metadata[APPLIED_FROM_CREDIT_KEY] = 'true'
        # A settlement holds no basis: this currency has been spent on the
        # document, whether the credit went whole into it or was carved. Nor
        # is it any document's orphan — the engine copies the source split's
        # whole slot frame onto the splits it makes, so a mark can arrive here
        # describing a split this one merely came from.
        for key in (COST_BASIS_BALANCE_KEY, COST_BASIS_COST_KEY,
                    ORPHANED_BY_UNPOST_KEY):
            metadata.pop(key, None)
        transaction.BeginEdit()
        set_custom_metadata(split, metadata)
        transaction.CommitEdit()
        marked.append(split)
    return marked


def _basis_splits_on(account):
    """Every split on this account that carries cost-basis keys, by guid.

    Keyed by guid with the amount and the keys themselves, so the same walk
    taken again can say which splits changed size and which are new.

    A bank-paid orphan is included whether or not it carries a basis. It
    usually carries none — the basis of a settled document sits on its posting
    split — so on this reading alone the engine could carve one and the
    remainder would be visited by nothing, arriving unmarked in the same
    abandoned lot and passing every test a credit passes. That is the harm
    this whole area exists to prevent, reached by spending forty of a hundred.
    """
    if account is None:
        return {}
    found = {}
    for split in account.GetSplitList():
        # Under the current name whichever the book kept it under, or a basis
        # written before the rename reads here as one this application never
        # touched — and its remainder is carved with no balance at all.
        metadata = cost_basis_metadata(split)
        if (COST_BASIS_BALANCE_KEY in metadata or COST_BASIS_COST_KEY in metadata
                or is_a_bank_paid_orphan(split)):
            found[split_guid(split)] = (numeric_to_fraction(split.GetAmount()),
                                        dict(metadata))
    return found


def _splits_on(account) -> set:
    """The guids of every split on this account, as it stands.

    Taken before a credit is applied, it is what says which splits the
    application made. Asking instead which splits carry basis keys answers a
    different question: a settlement written by an earlier payment carries
    none either, and where it happens to be the size of the carved remainder
    — a 250.00 payment against a 100.00 invoice, then 50.00 applied — it was
    taken for the remainder and handed the credit's balance and cost. Nothing
    reads those on a settlement, so the customer's real remaining credit was
    left with no balance at all: unlisted, and refused as a basis.
    """
    if account is None:
        return set()
    return {split_guid(split) for split in account.GetSplitList()}


def _carry_basis_across_applied_credit(record, before, existed_before=frozenset()) -> None:
    """Move a credit's cost basis onto what is left of the credit.

    Applying a customer's credit to an invoice does not set the credit aside.
    GnuCash reduces the split to the part being applied and carves the
    remainder into a new split in the same transaction, so a 100.00 USD credit
    meeting a 40.00 USD invoice becomes a 40.00 split and a 60.00 one.

    The keys stay where they were, on the split that shrank. That leaves the
    applied 40.00 saying `cost_basis_balance: "100.00"` — a balance for
    currency it no longer carries, inert only for as long as nothing reads it,
    and one unapply away from offering 100.00 of a 40.00 lump — while the
    60.00 the customer still has left is a prepayment with no cost at all, so
    `fx-balances` stops listing it and none of it can be sold.

    Both halves are put right here: the applied part gives its keys up, and
    the remainder takes the cost the credit was acquired at with a balance of
    its own size. Nothing is invented — the cost is the one already recorded
    on the split the remainder was carved from.

    The lot cannot be used to work out which is which: a lot's tie to its
    invoice is not visible through `gncInvoiceGetInvoiceFromLot` until the
    session is written, so in here the applied split still reads as the
    prepayment it was a moment ago. What is visible is size — the split that
    got smaller is the one that was applied.
    """
    account = record.GetPostedAcc()
    if account is None or not before:
        return
    after = {split_guid(split): split for split in account.GetSplitList()}

    for guid, (old_amount, metadata) in before.items():
        split = after.get(guid)
        if split is None:
            continue
        new_amount = numeric_to_fraction(split.GetAmount())
        if abs(new_amount) >= abs(old_amount):
            continue                    # untouched by this application

        old_available = None
        raw = metadata.get(COST_BASIS_BALANCE_KEY)
        if raw is not None:
            try:
                old_available = Fraction(str(raw))
            except (ValueError, ZeroDivisionError):
                old_available = None

        transaction = split.GetParent()
        if transaction is None:
            continue
        # Always bracketed, even when the engine already has this transaction
        # open: a KVP written outside an edit does not mark the transaction
        # dirty, so it is dropped on the way to disk. GnuCash counts edit
        # levels, so entering one it is already in is safe.
        transaction.BeginEdit()

        # The remainder is the split this transaction gained that carries
        # exactly what the credit lost. Size says which one: applying 40.00 of
        # a 100.00 credit leaves 60.00 behind, so the new 60.00 split on this
        # account is the customer's remaining credit.
        #
        # What the engine copies a slot frame onto, measured on GnuCash 5.10,
        # 4.13, 4.4, 3.8 and 5.15: the *applied* part, which keeps the source
        # split's guid and with it every slot the source had — basis keys and
        # `orphaned_by_unpost` alike. The carved remainder comes out with an
        # empty frame, carrying neither. So the only split with anything to
        # give up is the applied one, handled below; the remainder is written
        # rather than stripped, and no third split is made at all.
        #
        # The mark on the applied part is `_mark_applied_from_credit`'s to
        # clear, and it does.
        carried = abs(old_amount) - abs(new_amount)
        taken = False
        for sibling in transaction.GetSplitList():
            if (get_account_full_name(sibling.GetAccount())
                    != get_account_full_name(account)):
                continue
            sibling_guid = split_guid(sibling)
            if sibling_guid == guid:
                # The applied part is a settlement now, and settlements have
                # no basis.
                #
                # The mark stays in what is written back, and must: this runs
                # before `_mark_applied_from_credit`, which reads it to decide
                # whether the split is a bank's payment or a credit applied,
                # and then strips it itself. Excluding it here — which looks
                # like making the two independent — deletes the evidence the
                # next reader needs, so a bank-paid orphan the engine had
                # partly spent came out stamped `applied_from_credit` and
                # exported as a credit with no account and no date.
                set_custom_metadata(sibling, {
                    key: value for key, value in metadata.items()
                    if key not in (COST_BASIS_BALANCE_KEY, COST_BASIS_COST_KEY)})
                continue
            if sibling_guid in existed_before:
                # It was here before the credit was applied, so it is not what
                # the credit was carved into — whatever its size. Left alone:
                # a settlement written by an earlier payment carries no basis
                # keys of its own, and the engine copies none onto a split it
                # did not make.
                continue
            remaining = numeric_to_fraction(sibling.GetAmount())
            if taken or abs(remaining) != carried or (remaining < 0) != (old_amount < 0):
                # Not the remainder — this is the test that says which split
                # is. Nothing is written to the others: measured across the
                # whole suite on GnuCash 5.10, 4.13, 4.4, 3.8 and 5.15, the
                # engine's carve makes exactly one new split on the account
                # and this branch never runs at all.
                continue
            taken = True
            sibling_meta = dict(get_custom_metadata(sibling))
            available = (carried if old_available is None
                         else min(old_available, carried))
            # What the source was, the remainder still is. Spending part of a
            # settlement an unpost loosened does not turn the rest into the
            # owner's credit — the bank paid all of it — so the mark goes
            # forward. Without this, forty of a hundred spent left the sixty
            # unmarked in the same abandoned lot, passing every test a credit
            # passes: listed as one, spendable by a `from_credit:` block, and
            # exported as a credit applied with no account and no date.
            if ORPHANED_BY_UNPOST_KEY in metadata:
                sibling_meta[ORPHANED_BY_UNPOST_KEY] = metadata[
                    ORPHANED_BY_UNPOST_KEY]
                set_custom_metadata(sibling, sibling_meta)
            # Only where the source had one. A split reaches this walk either
            # because it carried a basis or because it was a bank-paid orphan,
            # and the second kind usually carries none — opening one for it
            # would invent currency the split never brought in.
            if (COST_BASIS_BALANCE_KEY not in metadata
                    and COST_BASIS_COST_KEY not in metadata):
                continue
            if COST_BASIS_COST_KEY in metadata:
                sibling_meta[COST_BASIS_COST_KEY] = metadata[COST_BASIS_COST_KEY]
                set_custom_metadata(sibling, sibling_meta)
            # Through the same writer every balance goes through, so it lands
            # at this split's own smallest unit and keeps the keys already
            # on it.
            write_cost_basis_balance(sibling, available)
        transaction.CommitEdit()


def _check_payment_split_lines(book, pay_dir, kind: str, bank_currency: str):
    """Judge a payment block's split lines, and return the accounts to write.

    What a settlement realizes goes on a split the block writes for itself, in
    the same shape a transaction uses:

        payment:
            …
            Income:FX Gain $residual$ CAD

    No key names an account and nothing is configured: the split says where
    the gain belongs, and `$residual$` takes what the rest of the entry leaves
    over, exactly as it does in a transaction.

    Run before the settlement touches anything, because everything here is
    knowable from the block and the account tree — and what follows it lowers
    a cost basis.
    """
    extra_dirs = [child for child in pay_dir.children
                  if child.type == DirectiveType.SPLIT]
    root = book.get_root_account()
    residual_dirs = [d for d in extra_dirs
                     if str(d.props.get('amount', '')) == RESIDUAL_AMOUNT]
    if len(residual_dirs) > 1:
        raise Exception(
            f'{len(residual_dirs)} splits on this payment ask for '
            f'{RESIDUAL_AMOUNT} — only one can take the residual')

    prepared = []
    for split_dir in extra_dirs:
        account_name = split_dir.props['account']
        account = find_account(root, account_name)
        if account is None:
            raise Exception(
                f'Account {account_name!r} not found for a split on this '
                f'{kind} payment')
        if split_dir not in residual_dirs:
            # The difference a settlement realizes is the one figure in this
            # entry that nobody moved: it is what the rate did. Everything
            # else in a payment is a movement with a date and a counterparty
            # of its own, and arrives as its own transaction — from a bank
            # import like anything else.
            #
            # Which is why this is not a question about what the line *is*.
            # Nothing here identifies a charge: an account is not a fee
            # because of its name, and this tool never reads one that way.
            # The test is only whether the line is the residual.
            #
            # Left open, whatever it was also had to be valued, and a figure
            # taken out of the settlement reduces the rate the currency
            # converted at: 274.00 CAD produced with 2.00 kept prices the
            # currency at 272/200, so that 2.00 lands in the cost basis of any
            # credit the payment leaves, where every later sale of that
            # currency is measured against it.
            raise Exception(
                f'split on {account_name!r} in this {kind} payment is not '
                f'{RESIDUAL_AMOUNT}. A payment block carries only the '
                f'difference the settlement realizes — the one figure in it '
                f'that moved no money. Anything that did move money is its '
                f'own transaction, with its own date, and leaves the rate '
                f'this settlement converted at alone')
        commodity = account.GetCommodity()
        if commodity is None or commodity.get_mnemonic() != bank_currency:
            raise Exception(
                f'split on {account_name!r} in this {kind} payment is in '
                f'{commodity.get_mnemonic() if commodity else "?"} but the '
                f'settlement is stated in {bank_currency}')
        # And it lands in the profit and loss, because that is what it is: the
        # difference between the rate the record was booked at and the rate it
        # settled at, which is income when the book gained and an expense when
        # it lost. Sent to a bank or another asset the entry still balances —
        # the residual absorbs whatever is left wherever it is put — and the
        # difference never reaches the income statement, sitting in the balance
        # sheet as though the money had merely moved.
        #
        # The account's type decides, and nothing else: an account is not a
        # gain account because of its name.
        if account.GetType() not in (ACCT_TYPE_INCOME, ACCT_TYPE_EXPENSE):
            raise Exception(
                f'{RESIDUAL_AMOUNT} on {account_name!r} posts to a '
                f'{xaccAccountGetTypeStr(account.GetType())} account — the '
                f'difference a settlement realizes is a gain or a loss, so it '
                f'belongs in income or expense. Anywhere else absorbs it into '
                f'the balance sheet, where the year\'s exchange result never '
                f'sees it')
        prepared.append((account, None))
    return prepared


def _check_stated_balances(book, directive) -> None:
    """Read every `cost_basis_balance:` in this directive before it lands.

    A stated balance is authoritative and nothing downstream questions it: a
    sale is measured against it, and valued at the basis cost. That makes it
    the one figure a file can write that conjures currency — 150.00 stated on
    a split that brought in 100.00 leaves 50.00 sellable that never arrived,
    and the gain booked on selling it is computed against a cost the book did
    pay. So it is checked here, on both ways in, against the split's own
    figures: a number, not negative, not finer than the currency can hold, and
    not more than the split brings in.

    The unparseable case is the quiet one. `60,00` for `60.00` — one wrong
    character in an export — used to leave the split *noted* as having stated
    a balance, so the sale below it in the same file was skipped as already
    accounted for, while the basis, having no readable balance, was opened at
    its full amount. Forty sold USD came back, silently, and the figure then
    parses so nothing afterwards finds it odd.
    """
    root = book.get_root_account()
    for child in directive.children:
        if child.type != DirectiveType.SPLIT:
            continue
        # The key this one was called before it was renamed. Not a reserved
        # key any more, so a file still stating it would be kept as an
        # ordinary custom key and read by nothing: unchecked, not noted as
        # already accounted for, and the basis opened at its full amount —
        # giving back currency the file itself records as sold. Refused by
        # name instead, which is the one shape that cannot go quiet.
        if 'cost_basis_available' in child.metadata:
            raise Exception(
                f'`cost_basis_available:` is now `{COST_BASIS_BALANCE_KEY}:`. '
                f'Left as it is, nothing would read it and the basis would '
                f'open at everything it brought in, giving back currency this '
                f'file records as sold. Rename the key — the figure is '
                f'unchanged.')
        stated = child.metadata.get(COST_BASIS_BALANCE_KEY)
        if stated is None or str(stated).strip() == '':
            continue
        account_name = str(child.props.get('account', ''))
        account = find_account(root, account_name)
        if account is None:
            continue        # the account check further in says so plainly
        commodity = account.GetCommodity()
        currency = commodity.get_mnemonic() if commodity is not None else ''
        where = f'{COST_BASIS_BALANCE_KEY} on split {account_name!r}'

        # On the split that holds the currency, before anything about the
        # figure. A purchase writes two lines and the balance belongs on one
        # of them; put on the other it passes every test of the figure itself
        # — 60.00 is a number, positive, in whole cents, less than the 135.00
        # that line carries — and says nothing, because no basis lives on a
        # split in the book's own currency. The basis it was meant for is then
        # left without a balance and opens at its full amount, so a file
        # asking for 60.00 available leaves 100.00 in the book with no error.
        # `cost_basis_cost:` is refused on the same line for the same reason.
        if currency == BASE_CURRENCY:
            raise Exception(
                f'{where} is on a {BASE_CURRENCY} split, which holds no '
                f'foreign currency for a cost basis to be about — state it on '
                f'the split that does')
        if commodity is not None and commodity.get_namespace() != 'CURRENCY':
            raise Exception(
                f'{where} is on a {currency} split, and {currency} is a '
                f'security rather than a currency — shares are counted and '
                f'priced, not converted, so they have no cost basis here')

        text = str(stated).strip()
        try:
            balance = Fraction(text)
        except (ValueError, ZeroDivisionError) as exc:
            raise Exception(f'{where} is not a number: {text!r}') from exc
        if balance < 0:
            raise Exception(
                f'{where} is negative: {text} — a balance falls by what a sale '
                f'takes and rises by what one gives back, and neither takes it '
                f'below nothing')

        # The same rule a stated `amount:` is held to, and for the same reason:
        # a balance is money, so it has to fit the currency as well as the
        # account. Judged against the account alone, `cost_basis_balance:
        # 100.001` was accepted on a `commodity_scu: 1000` account while
        # `amount: 100.001` was refused on that same account — one decision,
        # two answers, depending on which line of the block stated the figure.
        unit = account.GetCommoditySCU()
        account_commodity = account.GetCommodity()
        # Gated on the commodity being a currency, as the two other copies of
        # this rule are (`stated_money`, `string_to_gnc_numeric`). A security
        # is counted in units, not converted, so its account's own unit is the
        # only authority for how finely it divides — a fund declared
        # `fraction: 100` and kept to thousandths holds 12.345 units, and
        # taking the coarser of the two would call that unholdable. Nothing
        # reaches here with a security today, since a balance on one is
        # refused earlier; three copies of one rule that disagree is how the
        # odd one out drifts into being the reachable one.
        holdable = holdable_unit(account_commodity, unit)
        if (balance * holdable).denominator != 1:
            raise Exception(
                f'{where} states {text} {currency}, which this book cannot '
                f'hold — the smallest unit here is '
                f'{money_text(Fraction(1, holdable), holdable)}')

        amount_text = str(child.props.get('amount', '')).strip()
        try:
            acquired = abs(Fraction(amount_text))
        except (ValueError, ZeroDivisionError):
            continue        # the amount is checked, and refused, further in
        if balance > acquired:
            raise Exception(
                f'{where} states {money_text(balance, unit)} {currency}, but '
                f'that split brings in {money_text(acquired, unit)} — a basis '
                f'cannot have more available than it acquired, and the '
                f'difference would be sellable currency the book never held')


def _check_stated_costs(book, directive, existing_tx=None) -> None:
    """Read every `cost_basis_cost:` in this directive before anything is written.

    Both ways in go through here, or the same file means two things. The cost
    is read back after the commit — where a refusal can no longer undo an edit
    — so one missing its direction would otherwise leave a transaction
    rewritten and its basis unopened.

    A cost on a base-currency split is refused rather than stored, because
    nothing will ever read it: such a split establishes no cost basis, so the
    cost is never consulted, and it is almost always on the wrong one of the
    two lines. Checked on the update path alone, this was an error there and
    an inert KVP through `--new`.

    So is a cost on a split the transaction already prices. `cost_of` reads a
    stated cost before deriving one, so the file's figure wins over the
    book's: 9.99 stated beside 135.00 CAD for 100.00 USD is what `fx-balances`
    reports and what every later sale must be valued against. This tool never
    writes that second copy — `record_borrowed_basis` stores a cost only where
    the transaction cannot state one — and a file that writes it is refused
    for the same reason.
    """
    # The currency the transaction will actually be in, which is not always
    # the one the file names. An update states `currency.mnemonic:` only when
    # it means to change it, so a file that omits it leaves the transaction's
    # own — and reading the file alone answered "no base-currency side" for a
    # CAD transaction being edited, letting a stated cost through to be
    # written and then ignored.
    tx_currency = str(directive.metadata.get('currency.mnemonic', '') or '')
    if not tx_currency and existing_tx is not None:
        current = existing_tx.GetCurrency()
        tx_currency = current.get_mnemonic() if current is not None else ''
    root = book.get_root_account()

    def commodity_of(child):
        account = find_account(root, str(child.props.get('account', '')))
        if account is None or account.GetCommodity() is None:
            return None
        return account.GetCommodity().get_mnemonic()

    def namespace_of(child):
        account = find_account(root, str(child.props.get('account', '')))
        if account is None or account.GetCommodity() is None:
            return None
        return account.GetCommodity().get_namespace()

    # What `cost_of` needs to derive a cost: a base-currency figure for the
    # split's own to be read against — either because the transaction is
    # stated in the book's currency, or because a split on a base-currency
    # account gives the rate. The split's figure itself is never missing: one
    # that states no `value:` is valued at its amount, so asking which keys
    # the file typed answered "not priced" for a split the transaction prices
    # at 1, and let a stated cost through to be written and then ignored.
    prices_in_base = tx_currency == BASE_CURRENCY or any(
        child.type == DirectiveType.SPLIT and commodity_of(child) == BASE_CURRENCY
        for child in directive.children)

    for child in directive.children:
        if child.type != DirectiveType.SPLIT:
            continue
        stated = child.metadata.get(COST_BASIS_COST_KEY)
        if stated is None or str(stated).strip() == '':
            continue
        account_name = str(child.props.get('account', ''))
        currency = commodity_of(child)
        if currency is None:
            # The account check further in says so plainly, and still before
            # anything is written; guessing a currency here would report a
            # typo'd account as a malformed cost.
            continue
        if currency == BASE_CURRENCY:
            raise Exception(
                f'{COST_BASIS_COST_KEY} on split {account_name!r} is on a '
                f'{BASE_CURRENCY} split, which holds no foreign currency to '
                f'have a cost — state it on the split that does')
        # A security is counted and priced rather than converted, so it has no
        # cost in the sense this key means, and `establishes_cost_basis` will
        # never read one from it. Refused on the same terms as a stated
        # balance, which its sibling check has always refused here: a stored
        # `50 CAD/USTECH` is a figure the book keeps and nothing consults.
        if namespace_of(child) not in (None, 'CURRENCY'):
            raise Exception(
                f'{COST_BASIS_COST_KEY} on split {account_name!r} is on a '
                f'{currency} split, and {currency} is a security rather than '
                f'a currency — shares are counted and priced, not converted, '
                f'so they have no cost basis here')
        if prices_in_base:
            raise Exception(
                f'{COST_BASIS_COST_KEY} on split {account_name!r} states '
                f'{str(stated).strip()!r}, but this transaction already prices '
                f'that split — its value over its amount says what the '
                f'{currency} cost, and two answers would disagree. Drop the '
                f'line, or correct the split\'s own figures')
        parse_stated_cost(stated, currency, f'split {account_name!r}')


def _stated_rate(text, what: str) -> GncNumeric:
    """A rate the file states, parsed exactly.

    A rate is not money: it has no smallest unit, and 1.405 CAD/USD is an
    ordinary rate rather than a figure that must reach the cent. Parsing it
    against the currency's fraction truncates it to 1.40, which then values
    45.00 USD at 63.00 CAD instead of 63.23 and leaves the entry short.

    Exact here means exact *as an input*. The rate does not come back as
    written: a split of 45.00 USD valued at 63.23 CAD exports its rate as
    6323/4500 — the value over the amount, 1.405 + 1/9000 — because the value
    had to reach the cent. Observed by importing
    `tests/fixtures/fx_sell_usd_half_cent_residual.txt` and exporting it. So a
    stated rate is what the value is computed from; nothing should expect it
    back verbatim.
    """
    raw = str(text).replace(',', '.').strip()
    try:
        rate = Fraction(raw)
    except (ValueError, ZeroDivisionError) as exc:
        raise Exception(f'{what} must be a number, got {text!r}') from exc
    return GncNumeric(rate.numerator, rate.denominator)


def _require_no_unplaced_payment_splits(pay_dir, kind, reason, remedy=None):
    """Refuse a payment whose split lines nothing in this path will place.

    A payment block's splits are placed by the cross-currency settlement, which
    is the path that has a realized difference for them to take. Every other
    payment returns before reading them, so a fee written on an ordinary
    same-currency payment — or on one attached with `txn_guid:` — would parse,
    vanish, and be reported as a successful import: a book holding less than
    the file stated, which is the failure this whole feature exists to end.
    """
    unplaced = [child for child in pay_dir.children
                if child.type == DirectiveType.SPLIT]
    if not unplaced:
        return
    named = ', '.join(str(child.props.get('account', '?')) for child in unplaced)
    if remedy is None:
        remedy = ('Write the payment as an ordinary transaction — where any '
                  'number of splits is ordinary — and attach it with '
                  '`txn_guid:` / `txn_split_guid:`, or drop the split line(s) '
                  'from the payment block.')
    raise Exception(
        f'this {kind} payment carries {len(unplaced)} split line(s) ({named}), '
        f'but {reason}, so nothing would place them. {remedy}')


def _settlement_transaction_in(record, lot_before):
    """The transaction a payment just put in this record's lot, or None.

    Identified by not having been there before: `lot_before` is the set of
    transaction guids the lot held when the block started.
    """
    lot = record.GetPostedLot()
    if lot is None:
        return None
    for raw in lot.get_split_list():
        parent = Split(instance=raw).GetParent()
        if parent is None:
            continue
        if parent.GetGUID().to_string() not in lot_before:
            return parent
    return None


def _refuse_a_payment_block_spending_a_cost_basis_balance(record, bank_account, kind, lot_before):
    """A payment block cannot spend foreign cash a basis still has a balance for.

    Cash leaving a foreign account is a disposal, and this tool measures every
    foreign disposal against a named cost basis. A payment block has nowhere
    to name one: GnuCash's `ApplyPayment` writes its bank split, so
    `cost_basis_split_guid:` cannot go on it the way an ordinary
    transaction's selling split carries it.

    Left alone it drifts twice over. The basis keeps offering currency the
    account no longer holds — settle a USD invoice into an HKD bank and pay a
    USD bill back out of it, and the account is empty while `fx-balances`
    still reports 1,560.00 HKD available (measured). And the cash goes out
    valued at the payment day's rate rather than at what it cost, so an
    account holding no HKD is left holding a CAD figure whenever the two
    rates differ.

    Asked of every foreign bank, not only one in a third currency: paying a
    USD bill from a USD bank whose bases still have a balance drifts the same
    way, and that shape is the commoner one. It reaches none of the
    cross-currency arithmetic — `_book_payment_fx_difference` returns early
    when the record and the bank share a currency — so the question has to be
    asked before that.

    Allowed where the account's bases have nothing left: there is nothing to
    measure against, which is where every settlement into a fresh account
    starts. The way to spend a cost basis balance is the one every other foreign
    disposal uses — an ordinary transaction whose bank split names its basis,
    attached with `txn_guid:` / `txn_split_guid:`.
    """
    bank_commodity = bank_account.GetCommodity()
    if bank_commodity is None:
        return
    bank_currency = bank_commodity.get_mnemonic()
    if bank_currency == BASE_CURRENCY:
        return
    payment_txn = _settlement_transaction_in(record, lot_before)
    if payment_txn is None:
        # No settlement entry to judge. The callers that need one to exist
        # say so themselves, in their own words.
        return
    account_name = get_account_full_name(bank_account)
    for split in payment_txn.GetSplitList():
        # No null-account guard. Nothing `ApplyPayment` writes lacks an
        # account, and nothing loaded from a book can either — GnuCash 5.x
        # drops such a transaction while reading the file and 4.x segfaults on
        # it (CLAUDE.md §12), so the guard was agreeing with its sibling about
        # a state neither can meet.
        if get_account_full_name(split.GetAccount()) != account_name:
            continue
        spent = numeric_to_fraction(split.GetAmount())
        if spent >= 0:
            # Cash arriving, which opens a basis rather than drawing one
            # down. `record_cost_bases` gives it a basis balance.
            return
        offered = total_cost_basis_balance_in(bank_account)
        if offered > 0:
            raise Exception(
                f'this {kind} pays '
                f'{_account_money_str(abs(spent), bank_account)} '
                f'{bank_currency} out of {account_name!r}, whose cost bases '
                f'still have {_account_money_str(offered, bank_account)} '
                f'{bank_currency} of balance between them, and spending that '
                f'has to say which cost basis it comes out of. A payment block '
                f'cannot — GnuCash writes its bank split. Write the settlement '
                f'as an ordinary transaction with `{COST_BASIS_SPLIT_KEY}:` on '
                f'the bank line and attach it with `txn_guid:` / '
                f'`txn_split_guid:`')
        return


def _book_payment_fx_difference(record, book, pay_dir, bank_account, is_bill,
                                lot_before, fx_rates=None):
    """Book what a cross-currency settlement realized.

    A USD invoice recognises its revenue at the posting-date rate; settling it
    into CAD months later at another rate is a disposal of that receivable, and
    the difference between what the currency was booked at and what it actually
    fetched is realized on the settlement date.

    GnuCash values the A/R side of its payment at the settlement rate, so the
    entry balances and the difference disappears — 140.00 CAD of revenue
    against 137.00 CAD received, with nothing to explain the missing 3.00. Here
    the A/R side is valued at the cost basis it settles instead, and the
    difference goes on a split the payment block writes for itself, so the
    entry balances with the gain or loss stated.

    Same shape on the bill side, where settling a payable booked at 140.00 CAD
    for 137.00 CAD of cash is a gain.
    """
    kind = 'bill' if is_bill else 'invoice'
    record_commodity = record.GetCurrency()
    bank_commodity = bank_account.GetCommodity()
    # Above every return in this function, because it needs none of what they
    # bail out over: it reads the bank account's own commodity and the lot,
    # and asks its question of a same-currency settlement — which returns two
    # hundred lines below — as much as of a cross-currency one.
    _refuse_a_payment_block_spending_a_cost_basis_balance(record, bank_account, kind, lot_before)
    if record_commodity is None or bank_commodity is None:
        _require_no_unplaced_payment_splits(
            pay_dir, kind, 'its currencies could not be read')
        return
    record_currency = record_commodity.get_mnemonic()
    bank_currency = bank_commodity.get_mnemonic()
    if record_currency == bank_currency:
        _require_no_unplaced_payment_splits(
            pay_dir, kind,
            f'it settles in the {kind}\'s own currency ({record_currency}) and '
            f'so realizes nothing')
        return

    # The settlement entry is denominated in the base currency, because the
    # realized difference is a figure in it and a split's value is stated in
    # its transaction's currency. Where the bank *is* the base currency its
    # split is free — amount and value are one number. Where it is not, the
    # cash has to be valued, and that needs a rate.
    #
    # `bank_rate` is that rate, or None for a base-currency bank. Refusing the
    # whole shape as "a gain between two foreign currencies is not supported"
    # was the wrong diagnosis: nothing about it is unsupportable, the tool
    # simply had no rate in scope to value the cash with. What it is short of
    # is a number, and it says which one.
    # A document already in the base currency realizes nothing to measure: its
    # receivable holds CAD, and CAD does not appreciate against itself. What
    # the cash cost is a question about the *bank*, not about this document,
    # and it is answered where currency is bought — not here.
    #
    # Refused rather than run through: the posting split is base-currency, so
    # `derived_cost_of` answers 1 rather than None and the basis bail-out
    # below does not catch it. Measured on a CAD invoice settled into an HKD
    # bank — it reached the drawdown and failed with "state
    # `cost_basis_balance:` on that split", which cannot be done: the
    # importer refuses that key on a CAD split, and the split is written by
    # the posting, so there is no directive to state it on. It had already
    # committed a `cost_basis_split:` pointing at a base-currency split by
    # then, which is itself a thing no file may state.
    if record_currency == BASE_CURRENCY and bank_currency != BASE_CURRENCY:
        # Raised outright, not through `_require_no_unplaced_payment_splits`:
        # that only speaks when the block carries split lines, so a file
        # without a `$residual$` — which is what a reader writes for a
        # settlement that realizes nothing — returned quietly here and skipped
        # everything below, leaving the incoming currency with no available
        # balance and the entry denominated by whatever `ApplyPayment` chose,
        # differently on 3.8 than on 4.x.
        raise Exception(
            f'{kind} {record.GetID()}: this payment settles a '
            f'{BASE_CURRENCY} {kind} into a {bank_currency} account. Nothing '
            f'is realized — {BASE_CURRENCY} does not move against itself — '
            f'and what the {bank_currency} cost belongs to that account, '
            f'recorded where the currency was bought, not to this {kind}. '
            f'Settle it from a {BASE_CURRENCY} account, or record the '
            f'{bank_currency} purchase as its own transaction.')

    posted_account = record.GetPostedAcc()
    posting_txn = record.GetPostedTxn()
    if posted_account is None or posting_txn is None:
        _require_no_unplaced_payment_splits(
            pay_dir, kind, f'the {kind} is not posted')
        return

    basis_split = None
    for split in posting_txn.GetSplitList():
        if get_account_full_name(split.GetAccount()) == get_account_full_name(posted_account):
            basis_split = split
            break
    if basis_split is None:
        _require_no_unplaced_payment_splits(
            pay_dir, kind, f'the {kind} has no cost basis split to settle')
        return
    basis_cost = cost_of(basis_split)
    if basis_cost is None:
        _require_no_unplaced_payment_splits(
            pay_dir, kind,
            f'the {kind} carries no cost in {BASE_CURRENCY} to measure a '
            f'realized difference against')
        return

    # `bank_rate` is the rate that values the cash, or None where the bank is
    # already the base currency and its split is free — amount and value one
    # number. Asked for *after* the bail-outs above, because a record with no
    # cost basis returns without ever valuing anything: a CAD invoice settled
    # into an HKD account was being refused for want of a rate it would then
    # have discarded.
    #
    # Refusing the whole shape as "a gain between two foreign currencies is
    # not supported" was the wrong diagnosis — nothing about it is
    # unsupportable, the rates simply were not in scope. What it is short of
    # is a number, and it says which one.
    bank_rate = None
    if bank_currency != BASE_CURRENCY:
        pay_date = datetime.strptime(
            pay_dir.metadata['date'], "%Y-%m-%d").date()
        if fx_rates is None:
            raise MissingFxRateError(
                f'this {kind} is in {record_currency} and settles into '
                f'{bank_currency}, so valuing the cash needs the '
                f'{bank_currency}/{BASE_CURRENCY} rate on {pay_date} — pass '
                f'--fx-rates <file> with that rate in it')
        try:
            bank_rate = fx_rates.rate_fraction(bank_currency, pay_date)
        except MissingFxRateError as exc:
            raise MissingFxRateError(
                f'this {kind} is in {record_currency} and settles into '
                f'{bank_currency}, so valuing the cash needs the '
                f'{bank_currency}/{BASE_CURRENCY} rate on {pay_date}, which '
                f'the rates file does not carry: {exc}') from exc

    base_commodity = (bank_commodity if bank_rate is None
                      else book.get_table().lookup('CURRENCY', BASE_CURRENCY))

    payment_txn = _settlement_transaction_in(record, lot_before)
    lot = record.GetPostedLot()
    if payment_txn is None:
        _require_no_unplaced_payment_splits(
            pay_dir, kind,
            f'the payment did not join the {kind}\'s lot, so there is no '
            f'settlement entry to place them on')
        return

    settled_splits = []
    bank_split = None
    for split in payment_txn.GetSplitList():
        name = get_account_full_name(split.GetAccount())
        if name == get_account_full_name(posted_account):
            settled_splits.append(split)
        elif name == get_account_full_name(bank_account):
            bank_split = split

    settled_split = settled_splits[0] if len(settled_splits) == 1 else None
    overpaid_splits = []
    if len(settled_splits) > 1:
        # An overpayment lands two splits on the A/R or A/P account: the part
        # that settles the record, which the record's lot names, and the credit
        # left over, which it does not. Membership is the test — `GncLot`
        # exposes no guid accessor at all, so asking one for its guid raised
        # on every cross-currency overpayment.
        in_lot = ({split_guid(Split(instance=raw)) for raw in lot.get_split_list()}
                  if lot is not None else set())
        for split in settled_splits:
            if split_guid(split) not in in_lot:
                overpaid_splits.append(split)
            elif settled_split is None:
                settled_split = split
            else:
                # Two splits settling one record. Nothing produces this today,
                # and the arithmetic below has no place for a second: it would
                # be left out of the residual while still counting toward the
                # rate, so the entry would quietly fail to balance. Say so.
                raise Exception(
                    f'this {kind} payment puts more than one split in the '
                    f'{kind}\'s own lot, which this cannot value — write the '
                    f'settlement as an ordinary transaction and attach it with '
                    f'`txn_guid:` / `txn_split_guid:`')
    if settled_split is None or bank_split is None:
        _require_no_unplaced_payment_splits(
            pay_dir, kind,
            'the settlement entry has no recognisable bank and receivable side')
        return

    units = abs(numeric_to_fraction(settled_split.GetAmount()))

    # Money is carried in the currency's smallest unit, so the cost reaches the
    # cent first — through GnuCash's own rounding — and the difference is
    # derived from that rounded figure, which is what lets the entry balance
    # exactly even when the basis cost does not divide into cents.
    scu = base_commodity.get_fraction()
    cost_value = numeric_to_fraction(to_money(units * basis_cost, scu))

    # Everything the block says about its own split lines is judged first,
    # because the next thing this does is lower a cost basis. A refusal after
    # that point would leave the basis short by what the settlement drew, and
    # nothing on this path gives it back — the transaction path pairs its
    # drawdown with `give_back_to_cost_bases`, and here the answer is to have
    # nothing to give back. The checks need only the block and the account
    # tree, so there is no reason for them to run later.
    # Judged against the entry's own currency, which is the base one — a
    # split's value is stated in its transaction's currency, and that is what
    # a `$residual$` line has to be denominated in. Asking for the *bank's*
    # currency was the same thing while the bank was required to be the base
    # currency, and refused a correct CAD residual the moment it was not.
    prepared = _check_payment_split_lines(book, pay_dir, kind, BASE_CURRENCY)

    # Spending a cost basis balance was refused before any of this ran — see
    # `_refuse_a_payment_block_spending_a_cost_basis_balance`, called at the
    # top so the same-currency settlements that return long before here are
    # asked too.

    # The currency has been converted whether or not the rate moved, so the
    # basis is drawn down and the settlement tagged either way. Settling at
    # exactly the booked rate realizes nothing, and only the gain split is
    # skipped — leaving the basis untouched there would keep offering USD that
    # is now CAD, and a later sale would book a gain against currency the book
    # no longer holds.
    payment_txn.BeginEdit()
    set_custom_metadata(
        settled_split, {COST_BASIS_SPLIT_KEY: split_guid(basis_split)})
    payment_txn.CommitEdit()
    _draw_down_settled_basis(basis_split, units, kind, record_currency)

    # An invoice settles a receivable, so its side is a credit; a bill settles
    # a payable, so its side is a debit.
    settled_value = -cost_value if not is_bill else cost_value
    bank_value = Fraction(bank_split.GetAmount().num(),
                          bank_split.GetAmount().denom())
    if bank_rate is not None:
        # The cash is not in the entry's currency, so its value is what the
        # rate says it is worth — the one place a non-base bank differs from
        # a base one, which is why everything below reads the same either way.
        bank_value = numeric_to_fraction(
            to_money(bank_value * bank_rate, scu))

    # What the payment overpaid by was received at the rate the payment
    # converted at — the bank's own figure over everything it paid for — not
    # at the rate the record was booked at. Its value counts in the entry like
    # any other: left out, the residual absorbed it and GnuCash scrubbed in an
    # imbalance for the difference.
    #
    # The divisor is every receivable split the payment wrote, and it is not
    # guarded against zero: for it to be zero each of them would have to be,
    # the excess included, and the excess is why there is an overpayment at
    # all. Neither way of driving one to zero reaches here. A 0.00 posting
    # carries no cost to measure against, and a payment of nothing joins no
    # lot; both return two guards above — loudly when the block carries split
    # lines nothing would then place, silently when it carries none and there
    # is nothing to place. Skipping the arithmetic when the sum came out zero
    # would instead leave `overpaid_values` empty and the entry short by the
    # credit, which is the one outcome worth avoiding here.
    overpaid_values = []
    if overpaid_splits:
        total_units = sum((abs(numeric_to_fraction(split.GetAmount()))
                           for split in settled_splits), Fraction(0))
        # The bank line is the whole conversion, because a payment block
        # carries nothing else that moved money: a fee is its own transaction,
        # so nothing has been taken out of this figure. That is what keeps a
        # charge out of the rate — 272.00 credited after a 2.00 fee would
        # otherwise price the currency at 272/200 and put a dollar of bank
        # charge into the cost basis of the credit left over.
        received_rate = abs(bank_value) / total_units
        for split in overpaid_splits:
            # Its own name: `units` above is what the settlement drew from the
            # basis, and `_draw_down_settled_basis` is the next thing to use it.
            overpaid_units = abs(numeric_to_fraction(split.GetAmount()))
            value = numeric_to_fraction(
                to_money(overpaid_units * received_rate, scu))
            signed = -value if not is_bill else value
            overpaid_values.append((split, signed))

    # Everything in the entry but the residual itself: the bank, what the
    # settlement released at the record's cost, and any credit left over at
    # the rate the payment converted at. Nothing else can be here to add.
    leftover = -(bank_value + settled_value
                 + sum((value for _split, value in overpaid_values), Fraction(0)))
    # `prepared` is the residual and nothing else now, so its emptiness is the
    # question both of these ask: was a residual written, and is there
    # anything for it to take.
    if prepared and leftover == 0:
        raise Exception(
            f'{RESIDUAL_AMOUNT} on this {kind} payment has nothing to take — '
            f'the settlement leaves nothing over')
    if not prepared and leftover != 0:
        raise Exception(
            f'settling this {record_currency} {kind} into {bank_currency} '
            f'realizes '
            f'{_money_str(abs(leftover), base_commodity)} '
            f'{BASE_CURRENCY} against the '
            f'{exact_text(basis_cost)} '
            f'{BASE_CURRENCY}/{record_currency} it was '
            f'booked at — add a split to the payment block saying where that '
            f'belongs, e.g. `Income:FX Gain {RESIDUAL_AMOUNT} '
            f'{BASE_CURRENCY}`')
    # No early return when nothing was realized. There is no gain split to
    # place, but the entry still needs denominating in the base currency and
    # its values restating — and the cash still arrived, so the currency the
    # book now holds still needs a basis. Returning here skipped all three
    # exactly when the settlement came out at the rate it was booked at: the
    # one case a reader would least expect to leave money unsellable, and the
    # one shape left denominated differently on 3.8 than on 4.x, which the
    # explicit restatement below exists to prevent.
    settled_amount_numeric = settled_split.GetAmount()
    bank_amount_numeric = bank_split.GetAmount()

    payment_txn.BeginEdit()
    # The realized difference is a figure in the book's currency, so the entry
    # has to be denominated in it: a split's value is stated in its
    # transaction's currency, and GnuCash 3.8 raises the payment in the
    # record's currency (4.x and later use the transfer account's). Left in
    # USD, setting the A/R side's value to a CAD figure rewrites its *amount*
    # instead — the account's commodity being the transaction currency — and
    # the remainder lands in Imbalance-USD. Every value is then restated
    # explicitly, so the entry reads the same on every supported version.
    payment_txn.SetCurrency(base_commodity)
    bank_split.SetAmount(bank_amount_numeric)
    # Amount and value are one number only while the bank *is* the entry's
    # currency. Where the cash is in a third currency its value is what the
    # rate makes it, and writing the amount here instead left GnuCash to
    # scrub in an Imbalance split for the difference — 780.00 HKD entered as
    # 780.00 CAD, against 134.16 of actual value.
    bank_split.SetValue(bank_amount_numeric if bank_rate is None
                        else to_money(bank_value, scu))
    settled_split.SetAmount(settled_amount_numeric)
    # Through GnuCash, not `int(x * scu)`: truncation toward zero puts a
    # half-cent on the wrong side, and the residual is derived from these same
    # figures, so a cent lost here is a cent the entry no longer balances by.
    settled_split.SetValue(to_money(settled_value, scu))
    for split, value in overpaid_values:
        # Valued at what it was received for, so its cost reads back off the
        # split itself — the credit was acquired at the payment's rate, not at
        # the one the record was carried at.
        split.SetValue(to_money(value, scu))
    for account, amount in prepared:
        figure = leftover if amount is None else amount
        numeric = to_money(figure, scu)
        extra_split = Split(book)
        extra_split.SetParent(payment_txn)
        extra_split.SetAccount(account)
        extra_split.SetAmount(numeric)
        extra_split.SetValue(numeric)
        extra_split.SetMemo(pay_dir.metadata.get('memo', ''))
    payment_txn.CommitEdit()

    # Currency this settlement brought in gets a basis, exactly as it would
    # arriving by any other route. Settling a USD receivable into an HKD bank
    # puts 780.00 HKD in the book at a cost of 0.172 CAD/HKD, and without this
    # the split established a cost with no balance: `fx-balances` listed it as
    # empty and a later sale naming it was refused for having nothing left —
    # while the same 780 HKD entered as an
    # ordinary transaction was sellable. How the money arrived decided
    # whether the book would let go of it.
    #
    # Nothing to do where the bank is the base currency, which is why this
    # never showed before: `establishes_cost_basis` wants a non-base
    # commodity, so a CAD bank split is not a basis at all.
    record_cost_bases(book, payment_txn)


def _draw_down_settled_basis(basis_split, units, kind, record_currency):
    """Take what a settlement converted out of the basis's basis balance.

    Refused rather than driven negative when the basis has less left than the
    settlement converts — that state means the same currency was already sold
    elsewhere, which no amount of bookkeeping here can reconcile.
    """
    available = cost_basis_balance_of(basis_split)
    if available is None:
        raise Exception(
            f'cost basis {split_guid(basis_split)} has no balance recorded, '
            f'so settling this {kind} cannot draw it down — state '
            f'`{COST_BASIS_BALANCE_KEY}:` on that split in an import file to '
            f'give it one')
    if units > available:
        basis_currency = basis_split.GetAccount().GetCommodity()
        raise Exception(
            f'settling this {kind} converts '
            f'{_money_str(units, basis_currency)} '
            f'{record_currency} but cost basis {split_guid(basis_split)} has '
            f'only {_money_str(available, basis_currency)} '
            f'left — that {record_currency} has already been sold against it')
    lower_cost_basis_balance(basis_split, units)


def _payment_exchange_rate(record, bank_account, pay_dir, is_bill):
    """The rate `ApplyPayment` settles this payment at.

    A payment states its `amount:` in the record's own currency, so when the
    money lands in another currency something has to say what that side
    received — 100 USD into a CAD bank could be 137.00 CAD or 139.00. Either
    half may be written:

    - `settled_amount: 137.00` — what actually arrived in (or left) the
      account. This is the form a bank statement gives you, and the rate is
      derived from it;
    - `share_price: "1.37"` — the rate itself, meaning what it means on an
      ordinary split: one unit of the record's currency is worth this many
      units of the account's.

    Both may be given only if they agree. One of them is required when the
    currencies differ, and both are rejected when they match, where neither
    could mean anything. There is deliberately no fallback to a published rate:
    a payment records what actually happened, and only the payer knows what
    their money converted at. Substituting a mid-market rate would book a
    plausible-but-wrong bank balance and invent a gain that never occurred —
    the same quiet wrongness as the 1:1 default it replaces.
    """
    kind = 'bill' if is_bill else 'invoice'
    record_commodity = record.GetCurrency()
    record_currency = record_commodity.get_mnemonic() if record_commodity else '?'
    bank_commodity = bank_account.GetCommodity()
    # Asked without a fallback, as `stated_money` asks it — this commodity is
    # handed straight to that function, so a `'?'` here only postponed the
    # dereference to somewhere with a worse message.
    bank_currency = bank_commodity.get_mnemonic()
    account_label = get_account_full_name(bank_account)

    raw_rate = pay_dir.metadata.get('share_price')
    declared_rate = '' if raw_rate is None else str(raw_rate).strip()
    raw_settled = pay_dir.metadata.get('settled_amount')
    declared_settled = '' if raw_settled is None else str(raw_settled).strip()

    if record_currency == bank_currency:
        if declared_rate or declared_settled:
            field = 'share_price' if declared_rate else 'settled_amount'
            raise Exception(
                f'payment declares {field}: '
                f'{declared_rate or declared_settled} but the {kind} and '
                f'{account_label!r} are both in {record_currency} — there is '
                f'nothing to convert')
        return GncNumeric(1, 1)

    if not declared_rate and not declared_settled:
        raise Exception(
            f'this {kind} is in {record_currency} but the payment settles into '
            f'{account_label!r}, which is in {bank_currency} — add '
            f'`settled_amount:` to the payment block stating how much '
            f'{bank_currency} actually moved (or `share_price:` if you would '
            f'rather state the rate). Neither is looked up: only the payer '
            f'knows what the payment actually converted at.')

    amount_str = str(pay_dir.metadata.get('amount', '0')).strip()
    try:
        paid_units = Fraction(amount_str)
    except (ValueError, ZeroDivisionError) as exc:
        raise Exception(f'payment amount {amount_str!r} is not a number') from exc

    rate = None
    if declared_settled:
        try:
            settled = Fraction(declared_settled)
        except (ValueError, ZeroDivisionError) as exc:
            raise Exception(
                f'payment settled_amount {declared_settled!r} is not a number'
            ) from exc
        if settled <= 0:
            raise Exception(
                f'payment settled_amount {declared_settled!r} must be positive '
                f'— it is how much {bank_currency} moved, and the direction '
                f'comes from the {kind}, not from a sign')
        # And judged against the bank's currency, because it is a booked
        # amount too: this is the cash that lands on the bank split. Checked
        # only for "parses" and "positive", `137.005` into a CAD bank gave a
        # rate of 137.005/100, the split rounded to 137.00, and the residual
        # was computed from that rounded figure — so the entry balanced and
        # the run said `Errors: 0` about a payment the file did not describe.
        stated_money(declared_settled, bank_commodity,
                      f'the settled_amount on this {kind}',
                      scu=bank_account.GetCommoditySCU())
        if paid_units == 0:
            raise Exception('payment amount must not be zero')
        rate = settled / paid_units

    if declared_rate:
        try:
            stated = Fraction(declared_rate)
        except (ValueError, ZeroDivisionError) as exc:
            raise Exception(
                f'payment share_price {declared_rate!r} is not a number') from exc
        if stated <= 0:
            raise Exception(f'payment share_price {declared_rate!r} must be positive')
        if rate is not None and stated != rate:
            raise Exception(
                f'payment declares settled_amount: {declared_settled} and '
                f'share_price: {declared_rate}, but {amount_str} '
                f'{record_currency} at {declared_rate} is '
                f'{_money_str(paid_units * stated, bank_account.GetCommodity())} '
                f'{bank_currency}, not '
                f'{declared_settled} — they must agree')
        # What the rate *reaches* is judged the same way the figure itself is,
        # because it is the same figure: `settled_amount:` and `share_price:`
        # are the two documented spellings of how much of the bank's currency
        # moved, and a rule on one of them is a rule a file walks past by
        # writing the other word. 100 USD at 7.80005 is 780.005 HKD — the
        # split rounded to 780.00 while the residual was computed from the
        # rounded figure, so the entry balanced and the run said `Errors: 0`
        # about a payment the file did not describe.
        #
        # Worse than under the other spelling, because nothing matched it
        # afterwards either: the comparison reads what the file says against
        # what the book holds, 780.005 against 780.00, so the document was
        # judged changed on every import — and a posted document judged
        # changed is unposted, its posting destroyed and its payments
        # orphaned, then rebuilt to be judged again on the next run.
        # Through `exact_text`, because `_money_str` writes at the currency's
        # own places and would hand the check a figure already rounded to the
        # thing being checked for — 780.005 arriving as "780.00", which passes.
        #
        # A rate may be written as a fraction (README's own `10000/14000`), so
        # what it reaches may have no exact decimal either and `exact_text`
        # answers `100/7`. That is the right figure to quote and the refusal
        # reads correctly around it — the label is a noun phrase because the
        # sentence continues "states <figure>", and one ending in a verb gave
        # "which reaches states 100/7 HKD".
        stated_money(exact_text(paid_units * stated), bank_commodity,
                     f"the cash this {kind}'s share_price reaches",
                     scu=bank_account.GetCommoditySCU())
        rate = stated

    # Exact: `1.37` is 137/100, not the nearest binary float.
    return GncNumeric(rate.numerator, rate.denominator)


def _payments_only_added_diff(record, payment_dirs, asked_for_credit=False):
    """Q-015 classifier helper.

    Return (True, added_directives) iff every payment the record already
    holds is one the directive states, and the directive states more besides
    — those are what is being added. Matched by searching rather than by
    position or order: the lot holds cash before credit however a file writes
    them, and a payment may be added anywhere in the file rather than only at
    the end.

    Return (False, []) for any other shape — equal count, directive has
    fewer payments, or any in-place modification of an existing payment.
    """
    pay_splits = _lot_payment_splits(record, asked_for_credit)
    if len(pay_splits) >= len(payment_dirs):
        return False, []

    # Each payment the document already holds must be one the file states,
    # and what the file states beyond them is what is being added. Matched by
    # searching rather than by position: the lot holds cash before credit and
    # a file may write them either way round, so a document already settled
    # in part by a credit, with the cash appended below it, had its one
    # credit split compared against the file's cash block — and an ordinary
    # append became an unpost and rebuild.
    claimed, unclaimed = _pair_off_payments(pay_splits, payment_dirs)
    if claimed != len(pay_splits):
        return False, []
    # Returned in the order they must be applied — cash first, credit after —
    # so a caller cannot apply them in the order the file happened to write
    # them. Ordering here rather than at each call site: a second caller that
    # forgot would settle the document differently for no reason it states.
    return True, _cash_before_credit(unclaimed)


def _record_consumed_credit(record) -> bool:
    """Q-015: True iff a credit settled part or all of this record.

    Read from what the application wrote on the splits it moved into the
    record's lot, which is the same fact the exporter reads. Worked out from
    the lots instead — a payment touching both another document's lot and a
    leftover credit lot — it was right only while a residual survived, and
    said no for a credit consumed to the last cent.
    """
    return bool(_credit_splits_in_lot(record))


def _invoice_non_payment_matches(invoice, directive: 'PlaintextDirective') -> bool:
    """True iff every non-payment field of an existing customer invoice
    matches the directive: date_opened, billing_id, notes, custom KVP,
    entries (positional by field), and the posted block (or its absence).
    Used by both the strict-equality classifier and the Q-015 add-only
    classifier — payments are checked separately."""
    md = directive.metadata
    if invoice.GetDateOpened().strftime("%Y-%m-%d") != md['date_opened']:
        return False
    if not _document_text_matches(invoice, md):
        return False
    if not _named_custom_metadata_matches(invoice, md, KNOWN_INVOICE_METADATA_KEYS):
        return False

    # Q-015: a file asking for the owner's credit describes a book where it
    # has been applied. The reverse is not a difference: an export of that
    # same book carries no flag and names the credit in a payment block
    # instead, which the payment comparison below matches split for split.
    if _asks_for_credit(directive) and not _record_consumed_credit(invoice):
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
    return _payments_match_directive(invoice, payment_dirs, _asks_for_credit(directive))


def _is_only_added_payment_diff_invoice(invoice, directive):
    """Q-015 classifier for customer invoices.

    Return (True, added_directives) iff the only difference between the
    existing posted invoice and the directive is `payment:` blocks the
    directive states and the invoice does not yet hold — wherever in the
    file they are written (entries + posted + metadata all match, and every
    payment the invoice holds is one the directive states).

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
    return _payments_only_added_diff(invoice, payment_dirs, _asks_for_credit(directive))


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
    # Presence, and named keys only — the same rule the two
    # `*_non_payment_matches` comparisons keep, because this one decides
    # whether a `posted: none` edit can take the fast path that preserves the
    # entry guids. Reading an absent key as the empty string, and the slot
    # wholesale, made it permanently false for any document whose block names
    # less than the book holds — so the edit fell through to the full destroy
    # and rebuild, losing the guids this path exists to keep.
    if not _document_text_matches(invoice_or_bill, md):
        return False
    known_keys = KNOWN_BILL_METADATA_KEYS if is_bill else KNOWN_INVOICE_METADATA_KEYS
    if not _named_custom_metadata_matches(invoice_or_bill, md, known_keys):
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
    if not _document_text_matches(bill, md):
        return False
    if not _named_custom_metadata_matches(bill, md, KNOWN_BILL_METADATA_KEYS):
        return False

    if _asks_for_credit(directive) and not _record_consumed_credit(bill):
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
    return _payments_match_directive(bill, payment_dirs, _asks_for_credit(directive))


def _is_only_added_payment_diff_bill(bill, directive):
    """Q-015 classifier for vendor bills. Symmetric to
    `_is_only_added_payment_diff_invoice`."""
    if bill.GetPostedTxn() is None:
        return False, []
    if not _bill_non_payment_matches(bill, directive):
        return False, []
    payment_dirs = [c for c in directive.children if c.type == DirectiveType.PAYMENT]
    return _payments_only_added_diff(bill, payment_dirs, _asks_for_credit(directive))


def _echo_note(message: str) -> None:
    """A note to the reader from inside the importer.

    The importer is a service and does not own the terminal, so this is the
    one place that reaches for it — through click if the command line is what
    is running, and silently otherwise.
    """
    try:
        import click
        click.echo(f'  {message}', err=True)
    except Exception:
        pass


#: The keys a block is read for outright, so a `KeyError` naming one of them
#: really is a line the writer left out. Collected from the `metadata['…']`
#: reads in this module.
_BLOCK_FIELDS = frozenset({
    'account', 'accumulate', 'action', 'active', 'amount', 'ap_account',
    'ar_account', 'billing_id', 'commodity', 'commodity_scu', 'currency',
    'date', 'date_opened', 'description', 'doc_link', 'due', 'fraction',
    'fullname', 'memo', 'mnemonic', 'name', 'namespace', 'notes', 'price',
    'quantity', 'rate', 'share_price', 'tax_included', 'tax_table', 'taxable',
    'txn_guid', 'type', 'value',
})


def _said_plainly(error: Exception) -> str:
    """An error as a sentence, where the exception alone is not one.

    A required key read outright raises `KeyError`, and a `KeyError` renders
    as the key's own name: the reader was told `invoice "INV-1": 'due'`, which
    says neither that the field is required, nor which block wanted it, nor
    what to write. Every business-object failure passes through here on its
    way to the reader, so the one shape that is not a sentence becomes one.

    Only for a key a block is actually read for. Any `KeyError` at all became
    a claim about the reader's file, so an internal lookup that raised one —
    a guid missing from a map, a currency missing from a rates dict — would
    tell them to add a line their file has no place for. A `KeyError` on
    something else is left as it is: unhelpful, and honestly so.
    """
    if (isinstance(error, KeyError) and error.args
            and error.args[0] in _BLOCK_FIELDS):
        return (f'is missing the required field {error.args[0]!r} — every key '
                f'in the block it belongs to has to be stated')
    return str(error)


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
            if namespace.upper() == 'CURRENCY':
                # GnuCash fills the CURRENCY namespace from its own ISO 4217
                # table and serialises a currency *without* `<cmdty:name>` or
                # `<cmdty:fraction>`, expecting to look both up when the file
                # is read back. A code the table does not have gives it
                # nothing to look up: the book saves, and reloading it reports
                # `Syntax error in Xml File` and yields an empty book.
                #
                # Refused here rather than at save, because by then the
                # accounts and transactions are built and the summary has
                # counted them — measured on GnuCash 5.10, an import of such a
                # file reported `Errors: 0`, said "Changes saved", and left a
                # file that every later command read as empty.
                raise Exception(
                    f'commodity {mnemonic!r} is in the CURRENCY namespace but '
                    f'is not an ISO 4217 code. GnuCash has no such thing as a '
                    f'non-ISO currency: it writes currencies without a name or '
                    f'a fraction and looks them up by code when reading the '
                    f'book back, so this one would save and then fail to load. '
                    f'Anything that is not an ISO currency is a security — a '
                    f'stock or a fund — and lives in a namespace of its own '
                    f'(`namespace: "FUND"`, an exchange like `"NASDAQ"`, or '
                    f'any name you choose), where GnuCash writes the name and '
                    f'the fraction into the file and can read them back.')
            commodity = GncCommodity(book, fullname, namespace, mnemonic, f'{namespace}.{mnemonic}', fraction)
            commodity_table.insert(commodity)
            logging.debug(f"Created commodity {namespace}.{mnemonic}")
            # What the book did about it: `'created'`, `'updated'`, or `None`
            # for nothing. Counted rather than the declarations, because every
            # re-imported export declares every commodity it holds and most of
            # them are already there — and told apart from an update, because
            # GnuCash disagrees with itself about ISO fractions across
            # versions (KRW is 100 before 5.15 and 1 after), so a book moved
            # between two supported distros changes a fraction on every run,
            # forever. Reported as a creation that reads as a book gaining a
            # commodity it already had. Both are changes, so both still say
            # there is something to save.
            return 'created'
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
                # What the book will still hold after this session, remembered
                # before it is overwritten. A declared fraction is applied so a
                # book carried between two GnuCash versions stays the book it
                # was — the yen and the won are shipped differently across
                # supported distros — but for an ISO currency GnuCash writes
                # the code and looks the fraction up again on the way back in,
                # so a *finer* one lives only as long as the import.
                #
                # While it lived it was also what the amount rule read, which
                # made it a rule a file could widen its way past: `fraction:
                # 1000` for CAD beside `Expenses:Fuel 1.819 CAD` imported with
                # `Errors: 0` and saved, and the reopened book — CAD a
                # hundredth again, the split sub-cent — was refused by `export`
                # with nothing inside this tool able to correct it. Measured:
                # import exited 0, export of what it wrote exited 1.
                #
                # So the declaration still applies, and `stated_money` judges
                # against this instead.
                #
                # First value wins. One file declares a commodity once, so
                # this normally records once — but a run may import more than
                # one file into a book, and by the second the commodity
                # already carries what the first restated it to. Recording
                # again would remember that as the book's own.
                if (namespace or '').upper() == 'CURRENCY':
                    _PERSISTED_CURRENCY_FRACTION.setdefault(
                        mnemonic, commodity.get_fraction())
                commodity.set_fraction(fraction)
                logging.debug(
                    f"Commodity {namespace}.{mnemonic} exists; fraction set "
                    f"to {fraction}")
                # Said apart, because the two questions have different
                # answers here: what the run changed, and whether the book
                # needs writing. GnuCash writes an ISO currency without a
                # fraction and looks it up by code when reading the book back
                # — the paragraph above says so — so this fraction is a
                # session value the file never keeps, and saving cannot make
                # the mismatch go away. Counted as a reason to save, an
                # unchanged ledger rewrote the book on every run and left a
                # timestamped backup each time, forever, because the next run
                # found exactly the same difference. A book carried between
                # two supported distros meets that by itself, since GnuCash
                # disagrees with itself about KRW.
                #
                # Still reported, because it is what the run did and a reader
                # moving a file between versions needs to see it.
                # Cased the way the ISO refusal above cases it, so the two
                # tests of the same namespace cannot disagree.
                return ('updated' if (namespace or '').upper() != 'CURRENCY'
                        else 'updated-in-session')
            logging.debug(f"Commodity {namespace}.{mnemonic} already exists")
        return None

    @staticmethod
    def create_account(directive: PlaintextDirective, book: Book) -> bool:
        """
        Create account from directive.

        Args:
            directive: PlaintextDirective of type OPEN_ACCOUNT
            book: GnuCash book

        Returns:
            Whether the book gained an account. An `open` for one it already
            holds changes nothing, and counting it as created said the run had
            done something it had not: re-importing an unchanged ledger
            reported every account in the file, and the caller reads that
            count to decide whether to save, so it saved.
        """
        if directive.type != DirectiveType.OPEN_ACCOUNT:
            raise ValueError(f"Expected OPEN_ACCOUNT but got {directive.type}")

        root_account = book.get_root_account()
        account = Account(book)
        account_fullname = directive.props['account']
        account_type_str = directive.metadata['type']
        # Resolve the type up front: an unrecognised string fails clearly here,
        # before the account is attached to the tree, instead of leaving a
        # half-created INVALID-typed account (which silently drops off reports).
        if account_type_str not in ACCT_TYPE_MAP:
            raise ValueError(
                f"Unknown account type {account_type_str!r} for {account_fullname!r}. "
                f"Supported types: {', '.join(sorted(ACCT_TYPE_MAP))}.")
        account_type = ACCT_TYPE_MAP[account_type_str]
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

        # An `open` for an account the book already has is a no-op — found by
        # name under the same parent, and the block never read. That is what
        # README states beside the set/clear/absent rule, and what
        # `test_an_empty_key_on_an_account.py` pins: an `open` creates an
        # account or does nothing, so nothing in it can change one.
        if parent.lookup_by_name(account_name) is not None:
            logging.debug(f"Account {account_fullname} already exists, skipping")
            return False

        # Built first and attached last, so a refusal leaves the book as it
        # found it. An account is refused for things only knowable while it is
        # being built — a `guid:` another object already holds, a guid that is
        # not one, a `commodity_scu:` the setter will not take — and attached
        # before those were applied it stayed in the tree without them.
        #
        # On the `--include-business-objects` path that was silent as well as
        # wrong: the pre-pass leaves reporting to the transaction pass, and the
        # transaction pass found the account already there and had nothing to
        # report. `Errors: 0`, exit 0, and a book holding an account that had
        # been refused — where the same file without the flag said so and
        # exited 1.
        account.SetName(account_name)
        account.SetType(account_type)
        account.SetPlaceholder(placeholder)
        account.SetCode(code)
        account.SetDescription(description)
        account.SetTaxRelated(tax_related)

        # Through the same filter every other block uses. Read as "not None",
        # `department: ""` was stored on an account as an empty key and
        # written back out by the exporter for good — one spelling meaning
        # "remove this" on six kinds of block and "store an empty string" on
        # the seventh, with no spelling at all that took a custom key off an
        # account. README states the rule once, for the whole format.
        custom_meta = _custom_keys_to_store(
            directive.metadata, KNOWN_ACCOUNT_METADATA_KEYS)
        if custom_meta:
            set_custom_metadata(account, custom_meta)

        if 'commodity_scu' in directive.metadata:
            commodity_scu = directive.metadata['commodity_scu']
            account.SetCommoditySCU(commodity_scu)

        # Last but for the attach, because claiming a guid registers the
        # account in the book's collection whether or not it is ever attached.
        # Claimed before the rest of the build, a refusal further down left the
        # guid taken, and the pass that retried the same directive reported a
        # collision with an account the book does not contain — naming a guid,
        # where the line at fault was the one the setter refused.
        #
        # The exporter emits `guid:` on every `open` so an account keeps its
        # identity across a round trip; without honouring it the importer would
        # mint a fresh one and the guids would drift on every trip.
        declared_guid = directive.metadata.get('guid')
        if declared_guid:
            _set_object_guid(book, account, 'account', account_fullname,
                             _normalise_guid(declared_guid))

        parent.append_child(account)
        logging.debug(f"Created account {account_fullname}")
        return True

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

        # Before the transaction exists, so a figure or a character that cannot
        # be used refuses the file rather than the book — the same checks, and
        # the same answers, as the update path makes.
        _check_stated_costs(book, directive)
        _check_stated_balances(book, directive)
        _stated_txn_type(directive)
        # Every split rather than each in its turn: a split further down the
        # list can have opened an owner lot by the time a later one is refused
        # (`gnc_lot_new` + `xaccAccountInsertLot`, which the transaction's
        # rollback does not undo), leaving an empty lot behind on a file that
        # landed nothing. Beside the others here, so a file this refuses has
        # not so much as had a transaction allocated for it. The update arm
        # scans in the same place for the same reasons.
        refuse_a_stated_orphan_mark(
            directive.metadata,
            f'the transaction dated {directive.props.get("date", "?")}')
        for split_directive in directive.children:
            refuse_a_stated_orphan_mark(
                split_directive.metadata,
                f'the split on {split_directive.props.get("account", "?")!r}')

        root_account = book.get_root_account()
        stated_balance_splits = []
        # Everything the build can refuse takes the transaction with it: an
        # account that is not there, a commodity the book does not carry, a
        # `split_guid:` by its old name, and every figure `stated_money`
        # judges. Splits are attached one at a time, so a refusal on the
        # second line lands with the first already on the transaction — and
        # abandoning it there leaves that entry in the open book for
        # duplicate matching, balances and cost bases to find. Measured: the
        # phantom is in the session's query results, and absent from the file
        # it saves, because GnuCash writes no transaction whose edit was
        # never committed.
        with transaction_under_construction(book) as transaction:
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

            # Q-032: re-apply the book-closing flag so a roundtrip doesn't
            # un-close the books (the exporter emits `closing: #True` on
            # closing entries).
            _closing = directive.metadata.get('closing')
            if _closing is not None and not _is_falsy(str(_closing)):
                xaccTransSetIsClosingTxn(transaction.instance, True)

            _restore_txn_type(transaction, directive)

            transaction.SetDateEnteredSecs(datetime.now())
            date = datetime.strptime(date_str, '%Y-%m-%d')
            transaction.SetDatePostedSecsNormalized(date)

            # Q-035: a split may write `$residual$` in place of an amount and
            # take what the others leave over — how an FX gain or loss is
            # stated.
            residual_amount_str = _resolve_residual(
                directive, commodity, root_account)

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
                if str(split_amount_str) == RESIDUAL_AMOUNT:
                    # Computed, not stated — and exact by construction, since
                    # it is the difference between figures the currency already
                    # holds (see `_resolve_residual`). It never reaches the
                    # stated-amount check, which would otherwise blame the
                    # writer for a figure they never wrote.
                    amount = to_money(Fraction(str(residual_amount_str)),
                                      split_account_currency.get_fraction())
                else:
                    amount = stated_money(
                        split_amount_str, split_account_currency,
                        f'the amount on split {split_account_str!r}',
                        scu=split_account.GetCommoditySCU())

                split = Split(book)
                split.SetParent(transaction)
                split.SetAccount(split_account)
                split.SetAmount(amount)

                if 'share_price' in split_directive.metadata:
                    share_price = _stated_rate(
                        split_directive.metadata['share_price'],
                        f'the share_price on split {split_account_str!r}')
                    split.SetSharePrice(share_price)

                if 'value' in split_directive.metadata:
                    value_str = split_directive.metadata['value']
                    value = stated_money(
                        value_str, commodity,
                        f'the value on split {split_account_str!r}')
                    split.SetValue(value)
                elif 'share_price' not in split_directive.metadata:
                    split.SetValue(amount)
                # else: `SetSharePrice` above already valued the split at
                # amount × price, rounded by the engine to the transaction
                # currency's smallest unit. Overwriting that with the amount
                # would value 45.00 USD at 45.00 CAD and leave the rate
                # reading 1.

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
                        normalised_split_guid = _normalise_guid(
                            split_declared_guid)
                    except Exception:
                        normalised_split_guid = None
                    if normalised_split_guid:
                        _set_object_guid(book, split, 'split',
                                         split_account_str,
                                         normalised_split_guid)

                # Per-split owner KVP `lot_owner: kind:id[:guid]`. An AR/AP
                # split sitting in an owner's business lot (no invoice) carries
                # it. On import we JOIN the owner's open lot this split reduces
                # (a credit clearing — refund / vendor bad debt / customer
                # forfeit, decided by the counter split's account) or CREATE a
                # new lot (an orphan payment reconstructed — restoring the
                # GnuCash txn-type heuristic's 'P' arm of "lot with owner, no
                # invoice" — or a fresh credit origin). The trailing guid, when
                # present, is authoritative: a mismatch is a hard error. Runs
                # before CommitEdit; the lot only needs the split parented +
                # valued, both already done above. See
                # _attach_lot_owner_split / _parse_lot_owner.
                _lot_owner_str = split_directive.metadata.get('lot_owner', '')
                if _lot_owner_str:
                    _lo_kind, _lo_id, _lo_guid = _parse_lot_owner(_lot_owner_str)
                    if _lo_kind in ('customer', 'vendor') and _lo_id:
                        _attach_lot_owner_split(
                            book, split, split_account,
                            _lo_kind, _lo_id, _lo_guid)

                # Store any non-standard split metadata as KVP slots
                custom_split_meta = _custom_keys_to_store(
                    split_directive.metadata, KNOWN_SPLIT_METADATA_KEYS)
                if custom_split_meta:
                    set_custom_metadata(split, custom_split_meta)

                # Q-035: a file that states a cost basis's basis balance is
                # stating it net of every sale in that file, so those sales must
                # not lower it again on re-import. Collected here and noted only
                # once the transaction is committed — the note is module state
                # that no rollback undoes, and it should not outlive the basis
                # it describes. No file can be written that tells the two
                # orderings apart: a lost transaction takes its splits' guids
                # with it, so the sales below it are refused for naming a basis
                # the book does not have
                # (test_a_balance_stated_on_a_lost_transaction_reaches_no_later_sale).
                #
                # A figure that will not read is refused earlier, by
                # `_check_stated_balances`, so nothing malformed reaches this
                # — `60,00` for `60.00` never gets as far as being noted.
                #
                # What is asked here is the other half: the file must have
                # stated it. A split can carry a balance the *book* gave it,
                # and noting that would tell the sales below to leave a basis
                # alone on the strength of a figure the file never mentioned.
                if (COST_BASIS_BALANCE_KEY in split_directive.metadata
                        and has_a_stored_cost_basis_balance(split)):
                    stated_balance_splits.append(split)

            # Store any non-standard metadata as KVP slots
            custom_tx_meta = _custom_keys_to_store(
                directive.metadata, KNOWN_TX_METADATA_KEYS)
            if custom_tx_meta:
                set_custom_metadata(transaction, custom_tx_meta)

        for split in stated_balance_splits:
            note_stated_balance(split)

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

        # Q-035: a split that picks another split's cost basis is checked
        # against that basis's basis balance and lowers it; a split that
        # brings foreign currency in opens a basis of its own. Both run after
        # CommitEdit, where the splits are readable as book state — so a sale
        # this refuses is undone here rather than left in the book: the import
        # reports the error per transaction and carries on with the rest of the
        # file, which would otherwise save a sale the ledger just rejected.
        # What the picks took is given back with the transaction. Nothing the
        # file can state reaches this point unchecked — a stated cost is parsed
        # before the transaction is created and every pick is validated before
        # the first balance moves — so what is left to fail in `record_cost_bases`
        # is the engine itself: the lot query behind `_is_prepayment`, and the
        # KVP writes that open a basis. A drawdown outliving its transaction
        # would leave a basis reading 60.00 USD available with nothing in the
        # book that took the other 40, so the two are undone together.
        # `apply_cost_basis_picks` holds the same invariant for its own loop,
        # and the pair is tested in
        # tests/unit/services/test_cost_basis_drawdown_is_reversible.py.
        taken = {}
        try:
            taken = apply_cost_basis_picks(book, transaction)
            record_cost_bases(book, transaction)
        except Exception:
            transaction.BeginEdit()
            transaction.Destroy()
            transaction.CommitEdit()
            give_back_to_cost_bases(book, taken)
            raise

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

        # Q-035: a transaction that touches a cost basis is not edited in
        # place. The checks that govern a sale — that a basis has the currency
        # it is being sold, that the basis is lowered by what the sale takes —
        # run over a transaction's splits once they are book state, and an
        # in-place edit has already overwritten what the old amounts drew
        # before anything can be re-checked. Editing this way accepted a sale
        # of 400.00 USD against a basis holding 60.00, reported `Updated: 1`,
        # and left the basis still reading 60.00.
        #
        # Deleting the transaction and importing it afresh is the supported
        # route and gives the same end state: deleting a sale gives the basis
        # back exactly what that sale took, and the new import runs every
        # check. That is what this refusal points at.
        _require_no_cost_basis_edit(existing_tx, directive)

        # A block with no splits, against a transaction that has some. The
        # block is the source of truth for the splits — one absent from it is
        # removed, which is what lets a person delete a split by deleting a
        # line — and nothing told that apart from a file that stops here. A
        # transaction block needs only its date, flag and description to
        # parse, so a file cut short by a failed write still reads as one, and
        # rebuilding from it left the transaction with no splits at all:
        # measured, the transaction was then gone from the book entirely.
        #
        # Only when there is something to lose, as the document blocks are
        # guarded: a transaction with no splits can still be created, since
        # nothing is destroyed by it.
        if (not any(c.type == DirectiveType.SPLIT for c in directive.children)
                and existing_tx.GetSplitList()):
            raise Exception(
                f'the transaction {existing_tx.GetDescription()!r} has no '
                f'splits in this file and '
                f'{len(existing_tx.GetSplitList())} in the book. A '
                f'transaction is rebuilt from its block, so importing this '
                f'would leave it with no money in it — which is what a file '
                f'cut short looks like. State the splits, or remove the block '
                f'to leave the transaction alone.')

        stated_balance_splits = []

        # Which splits were already cost bases. Not which splits existed:
        # splits are matched by account, so correcting reversed signs reuses
        # the same split — same guid — and turns something that was no basis
        # into one. Skipping it because it existed left that currency with no
        # basis.
        splits_before = {split_guid(split) for split in existing_tx.GetSplitList()
                         if establishes_cost_basis(split)}

        # All before `BeginEdit`, so a file this refuses has moved nothing.
        # `_restore_txn_type` re-reads the character below, where it is applied;
        # by then splits have been rewritten and attached to owner lots, and a
        # lot is engine state the transaction's own rollback does not obviously
        # undo.
        #
        # The cost check is given the transaction as well, because an update
        # that does not restate `currency.mnemonic:` keeps the currency the
        # book already holds — and whether the transaction can price a split
        # is the whole question that check asks.
        _check_stated_costs(book, directive, existing_tx)
        _check_stated_balances(book, directive)
        _stated_txn_type(directive)
        refuse_a_stated_orphan_mark(
            directive.metadata,
            f'the transaction dated {directive.props.get("date", "?")}')
        for split_directive in directive.children:
            refuse_a_stated_orphan_mark(
                split_directive.metadata,
                f'the split on {split_directive.props.get("account", "?")!r}')

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

            # Through the same merge the owner and document blocks use, so
            # `key: ""` means one thing in this format rather than two: a key
            # the block does not name is left alone, and a key named empty is
            # removed. Merged with `update` and only the `None` filter, an
            # empty value set the key to the empty string and there was no
            # spelling that took it off.
            _merge_custom_metadata(existing_tx, directive.metadata,
                                   KNOWN_TX_METADATA_KEYS)

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
                    amount = stated_money(
                        split_directive.props['amount'], split_account_currency,
                        f'the amount on split {acct_name!r}',
                        scu=split_account.GetCommoditySCU())

                    if 'value' in split_directive.metadata:
                        value = stated_money(
                            split_directive.metadata['value'], tx_currency,
                            f'the value on split {acct_name!r}')
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
                        share_price = _stated_rate(
                            split_directive.metadata['share_price'],
                            f'the share_price on split {acct_name!r}')
                        split.SetSharePrice(share_price)

                    if 'action' in split_directive.metadata:
                        action = split_directive.metadata['action']
                        if action is not None:
                            split.SetAction(action)

                    if 'memo' in split_directive.metadata:
                        memo = split_directive.metadata['memo']
                        if memo is not None:
                            split.SetMemo(memo)

                    # `lot_owner:` on the create path's terms — an AR/AP split
                    # in an owner's business lot — for a split this edit
                    # writes. An update can put one in the book as readily as
                    # a fresh transaction can: a CAD receipt corrected into a
                    # customer's USD prepayment is the credit that says the
                    # currency is owed back, and it is only a prepayment
                    # because it is in that lot. Acted on by the create path
                    # alone, the line was dropped in silence and the split
                    # read as a settlement.
                    #
                    # Only when the split is in no lot yet. An exported
                    # prepayment carries `lot_owner:` and is already in its
                    # owner's lot, so re-importing it over itself must leave
                    # that lot alone rather than open a second one.
                    _lot_owner_str = split_directive.metadata.get('lot_owner', '')
                    if _lot_owner_str and split.GetLot() is None:
                        _lo_kind, _lo_id, _lo_guid = _parse_lot_owner(_lot_owner_str)
                        if _lo_kind in ('customer', 'vendor') and _lo_id:
                            _attach_lot_owner_split(
                                book, split, split_account,
                                _lo_kind, _lo_id, _lo_guid)

                    # Update split-level custom metadata: a key the block names
                    # wins, a key named empty comes off, and a key the block
                    # does not mention is left alone.
                    _merge_slot_keys_named(split, split_directive.metadata,
                                           KNOWN_SPLIT_METADATA_KEYS)

                    # Q-035: as on the create path — a file stating a basis's
                    # basis balance is stating it net of every sale in that
                    # file, so those sales must not lower it again. Noted after
                    # the commit for the same reason: the note is module state
                    # that a rollback cannot undo. Unobservable from here too,
                    # and for its own reason: this path is only reached with
                    # `--strategy update`, which requires a `guid:` on every
                    # transaction in the file, so a failing edit and a freshly
                    # written sale cannot arrive together. And as there, a
                    # balance that does not parse states nothing and is not
                    # noted.
                    #
                    # The key must be in the *file*, which matters more here
                    # than on the create path: an updated split usually
                    # carries a balance already, from the book, and noting
                    # that would mark a basis as spoken for by a file that
                    # never mentioned it.
                    if (COST_BASIS_BALANCE_KEY in split_directive.metadata
                            and has_a_stored_cost_basis_balance(split)):
                        stated_balance_splits.append(split)

            _restore_txn_type(existing_tx, directive)
            existing_tx.CommitEdit()
            logging.debug(f"Updated transaction on {date_str}")

        except Exception:
            existing_tx.RollbackEdit()
            raise

        # After the commit, and outside the block that rolls back — a rollback
        # cannot undo a committed edit, so a failure in here reported an error
        # while the rewritten transaction stayed on disk, which is how a
        # malformed `cost_basis_cost:` left a split changed and with no basis.
        # An update can bring foreign currency into the book (a CAD placeholder
        # corrected into `Assets:Bank:USD 100.00 USD`), and that currency needs
        # a basis like any other.
        #
        # Only the splits this edit made into bases — `splits_before` above
        # holds the ones that already were. Not the splits that already
        # *existed*: a split matched by account and corrected keeps its guid
        # while becoming a basis it was not, and skipping it for having
        # existed left that currency with no basis at all. A split that was
        # already a basis and carries no stored balance was written in the
        # GUI, or predates this, and how much of its currency has been sold is
        # not recorded; opening it at its full amount would offer currency
        # that may be long gone. Correcting a description was enough to do
        # that to every such basis in a book.
        for split in stated_balance_splits:
            note_stated_balance(split)

        for split in existing_tx.GetSplitList():
            if split_guid(split) in splits_before:
                continue
            if establishes_cost_basis(split):
                open_cost_basis_balance_if_none_is_stored(split)

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

        # Address lines → the single multi-line `Company Address` slot, the
        # inverse of the `read_book_company_info` split-on-newline. As many
        # lines as the block names: the slot is free text, and File →
        # Properties → Business takes as many as are typed into it, so an
        # address with a unit, a country and an "attention" line has six
        # without being unusual.
        #
        # Only the lines the block names, the rest left where they are. It
        # used to rewrite the whole slot from whatever the block named, so a
        # block correcting the street deleted the postcode — an address of
        # four lines cut to one by a block that named `addr[0]`. Every other
        # key in this format leaves what it does not mention alone, the
        # customer address included, and there was no reason for the book's
        # own address to be the exception.
        # A book written before the company block had address lines keeps them
        # in the custom blob and has nothing on the option, so on such a book
        # the blob **is** the address — and the lines the block names are
        # written on top of it, not instead of it. Editing the street of a
        # four-line address stated that way otherwise left the option holding
        # the street alone: the other three were superseded out of the blob,
        # the option never learnt them, and the export — which falls back to
        # the blob only when the book has no address at all — then wrote a
        # one-line address. A block that said nothing kept all four, so the
        # loss came of asking to change one of them.
        held = get_book_custom_metadata(book) or {}
        carried_lines = {address_line_index(k): str(v)
                         for k, v in held.items()
                         if is_address_key(k) and v is not None and str(v)}

        named_lines = named_address_lines(md)
        current = get_book_string_option(book, 'Business',
                                         'Company Address') or ''
        migrating = bool(carried_lines)
        if named_lines or migrating:
            # The option is the address as far as it goes, and the slot
            # supplies what lies past the end of it. A book can hold both —
            # type an address into File → Properties → Business on a book
            # whose address was still in the slot, and it does — and reading
            # only one of them lost the other's tail: a four-line slot behind
            # a two-line option had lines three and four in no export and in
            # no book rebuilt from one, permanently, since no import merged
            # them either.
            base = address_lines_beyond(
                current.split('\n') if current else [], carried_lines)
            addr_val = '\n'.join(address_lines_from(base, named_lines))
            if current:
                had_any = True
            # Every line's blob copy goes once the option holds the address,
            # not only the copies of the lines the block named — and only once
            # the option write has reported success, because until then the
            # blob is the sole copy of whatever it carried.
            # `set_book_string_option` swallows its exception and returns
            # False, so an unguarded delete would lose the address on exactly
            # the run that failed to write it.
            wrote = current != addr_val and set_book_string_option(
                book, 'Business', 'Company Address', addr_val)
            if wrote:
                changed = True
            # `current == addr_val` is the option already holding everything
            # the blob had — nothing to write, and the copies are stale all
            # the same. Left behind they are carried by every later run of
            # this book for no reader at all.
            if (migrating and (wrote or current == addr_val)
                    and merge_book_custom_metadata(
                        book, {k: None for k in held if is_address_key(k)})):
                changed = True

        # Q-029 (fixed): any key that is not a known Business field or an address
        # line is book-level custom metadata. The directive is a partial UPSERT,
        # consistent with the known-field tier above and with the documented
        # contract that an absent field is left as-is — keys named here are set,
        # keys NOT named are preserved, and a key given the null value (`#None`)
        # is removed (JSON Merge Patch). It used to replace the whole blob, so a
        # partial company directive silently deleted any custom key it didn't
        # repeat; merge is shared with `set-book-key` so both behave the same.
        known = set(COMPANY_FIELD_TO_SLOT)
        _refuse_bracketed_keys(md, known | {k for k in md
                                            if is_address_key(k)})
        custom = {k: v for k, v in md.items()
                  if k not in known and not is_address_key(k)}

        # A key that has since become a field of its own leaves the slot —
        # **but only once the block has stated it**, which is the rule
        # `_merge_custom_metadata` follows for the per-object slots and for
        # the same reason: until the block states it, the slot is the only
        # copy the book has. A book written before `date_format` was a
        # Business option keeps it there and has nothing on the option;
        # dropping it unasked loses the format outright.
        #
        # Stated, the loop above has just written the option, so the slot's
        # copy is the stale one and goes. (CLAUDE.md finding 11.)
        held = get_book_custom_metadata(book) or {}
        superseded = {k: None for k in held if k in known and k in md}
        # The address's own copies are dealt with where it is written, above:
        # migrating takes every line, since the option then holds the whole
        # address, and that has to happen before this reads the blob back.
        # An address line's stale copy goes by the line it names rather than
        # by the key, because the two spellings name the same line: a block
        # saying `addr[0]` supersedes a blob holding `addr1`, and a book that
        # kept both would export the line twice with the stale copy second.
        superseded.update({k: None for k in held
                           if is_address_key(k)
                           and address_line_index(k) in named_lines})
        if superseded and merge_book_custom_metadata(book, superseded):
            changed = True

        # And the option is written from the slot when the block says nothing
        # and the option has nothing — the migration itself, rather than a
        # tidy-up of one. Without it a book whose only copy is in the slot
        # keeps a `date_format` that no report reads and no page shows: the
        # value is there, and everything that looks for it looks at the
        # option.
        #
        # Either way the slot's copy goes, and that second half is what keeps
        # the first honest. A book can hold both — a legacy slot copy and an
        # option written in GnuCash — and while the slot kept its copy, a
        # reader who then cleared that option in the GUI had the stale value
        # written back onto it by the next import that said nothing about the
        # key. The option is the book's answer once it has one, so a slot copy
        # beside it is stale by definition, whatever it says. This is the
        # address's rule for the fields that are not the address.
        #
        # The copy is dropped only if the option write reported success.
        # `set_book_string_option` swallows its exception and returns False,
        # and that write happens precisely when the slot is the only copy the
        # book has — so deleting it regardless of whether the value landed
        # anywhere would lose it outright, on the one path whose whole purpose
        # is not to.
        for key, slot in COMPANY_FIELD_TO_SLOT.items():
            if key in md or key not in held:
                continue
            carried = '' if held[key] is None else str(held[key])
            option = get_book_string_option(book, 'Business', slot) or ''
            if option:
                # Said out loud, because this is the arm that ends a value.
                # These names were ordinary custom keys on every release
                # before this one, so a book may hold one for something of its
                # own — `name` as an internal codename beside a Company Name
                # — and it is dropped here without the block having asked, on
                # a run whose summary says `updated` and nothing else. Nor
                # could the reader have got it out of the last export: the
                # writers prefer the option and skip this copy.
                if merge_book_custom_metadata(book, {key: None}):
                    changed = True
                    if carried:
                        _echo_note(
                            f'⚠ dropped the book\'s custom {key!r} key '
                            f'({carried!r}) — that name belongs to the '
                            f'`company` block now, and GnuCash\'s own '
                            f'{slot} already holds {option!r}. Rename the '
                            f'key in an earlier export if you need it back.')
            elif carried and set_book_string_option(book, 'Business', slot,
                                                    carried):
                merge_book_custom_metadata(book, {key: None})
                changed = True

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

        # Before the short-circuit below, which does not read `currency:`
        # and would answer 'unchanged' to a file that changed it.
        _refuse_a_changed_currency(existing, directive, 'customer', cid)

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
        _write_named_address(customer, directive.metadata)
        customer.CommitEdit()

        # Named or not at all: a block that does not mention `active:` is not
        # asking for a retired owner to be brought back, which a default of
        # true did on every partial block.
        #
        # The export writes the key only for a retired owner, so rebuilding an
        # export into a book that has since retired one leaves it retired —
        # the file says nothing about it. Into a fresh book, which is what a
        # rebuild is, every owner starts active and the two agree.
        if 'active' in directive.metadata:
            customer.SetActive(not _is_falsy(directive.metadata['active']))

        _merge_custom_metadata(customer, directive.metadata,
                               KNOWN_CUSTOMER_METADATA_KEYS)
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

        # Before the short-circuit below, which does not read `currency:`
        # and would answer 'unchanged' to a file that changed it.
        _refuse_a_changed_currency(existing, directive, 'vendor', vid)

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
        # As the customer block has always done. Without this the address keys
        # had no setter behind them and were kept as custom metadata, so a
        # book rebuilt from an export rendered its bills with the vendor's
        # address lines blank.
        _write_named_address(vendor, directive.metadata)
        vendor.CommitEdit()

        if 'active' in directive.metadata:
            vendor.SetActive(not _is_falsy(directive.metadata['active']))

        _merge_custom_metadata(vendor, directive.metadata,
                               KNOWN_VENDOR_METADATA_KEYS)
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
        # The rate the file states, exactly: `5.375%` is 43/8, not the nearest
        # binary float, and it is stored to five decimals from there.
        rate = Fraction(str(rate_str).replace("%", "").strip())
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
                rate = Fraction(str(rate_str).replace("%", "").strip())
                entry = create_tax_table_entry(book, account, rate)
                taxtable.AddEntry(entry)

        logging.debug(f"Created taxtable {directive.props['name']}")
        return 'created'

    @staticmethod
    def import_invoice(directive: PlaintextDirective, book: Book,
                       on_orphan_warning=None, fx_rates=None):
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
        _refuse_a_changed_currency(existing, directive, 'invoice', inv_id)
        _refuse_a_document_that_would_lose_its_lines(
            existing, directive, DirectiveType.INVOICE_ENTRY, 'invoice', inv_id)

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
        #   - only difference is payment(s) the directive states and the
        #     invoice does not hold → apply just those via ApplyPayment on
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
            # Before it is compared to anything, and here rather than inside
            # the comparisons: those are predicates, and a question that
            # writes to the book is one the next caller will ask without
            # expecting it to. Once per document, where the document is first
            # in hand.
            migrated = _move_slot_keys_that_became_fields(
                existing, KNOWN_INVOICE_METADATA_KEYS)
            if _invoice_matches_directive(existing, directive, book):
                # `updated` where a slot key was moved onto its field: the
                # document matches its file, and the book is not the book it
                # was a moment ago. Reported `unchanged`, the run had nothing
                # to save, the move was dropped on session end, and the next
                # run made it again.
                if migrated:
                    logging.debug(f"Invoice {inv_id}: slot keys migrated to fields")
                    return 'updated'
                logging.debug(f"Invoice {inv_id} already matches directive; unchanged")
                return 'unchanged'
            if _is_only_unpost_diff(existing, directive, is_bill=False):
                logging.debug(
                    f"Invoice {inv_id}: only difference is posted→posted:none; "
                    f"minimal unpost (entry GUIDs preserved)"
                )
                require_cost_basis_unused(book, existing, 'invoice', inv_id)
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
                # `added_pays` arrives cash-before-credit from the classifier,
                # so appending the two in one edit settles the invoice the way
                # writing them into a fresh file does.
                for pay_dir in added_pays:
                    _apply_payment_directive(existing, pay_dir, book,
                                             is_bill=False, fx_rates=fx_rates)
                return 'updated'
            status_on_success = 'updated'
            if existing.GetPostedTxn() is not None:
                logging.debug(f"Invoice {inv_id} is posted but differs; unposting for rebuild")
                require_cost_basis_unused(book, existing, 'invoice', inv_id)
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
        credit_blocks = []
        for entry_directive in directive.children:
            if entry_directive.type == DirectiveType.INVOICE_ENTRY:
                entry_index += 1
                # Everything that can refuse the line is resolved before the
                # entry exists, so a refusal leaves no half-built `GncEntry`
                # in an open edit, attached to nothing — the shape
                # `transaction_under_construction` exists to keep out of the
                # book. Both of these raise: an account the book has not got,
                # and a tax table it has not got.
                inv_acct_name = entry_directive.metadata['account']
                inv_acct = find_account(book.get_root_account(), inv_acct_name)
                if inv_acct is None:
                    raise Exception(f'Account {inv_acct_name!r} not found when creating invoice entry')
                inv_tax_table = (
                    _the_tax_table_named(
                        book, entry_directive.metadata['tax_table'],
                        'invoice', directive.props['id'])
                    if 'tax_table' in entry_directive.metadata else None)

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
                entry.SetInvAccount(inv_acct)
                entry.SetQuantity(string_to_gnc_numeric_quantity(entry_directive.metadata['quantity']))
                entry.SetInvPrice(string_to_gnc_numeric_quantity(entry_directive.metadata['price']))
                entry.SetInvTaxable(entry_directive.metadata['taxable'] == 'true')
                entry.SetInvTaxIncluded(entry_directive.metadata['tax_included'] == 'true')
                if inv_tax_table is not None:
                    entry.SetInvTaxTable(inv_tax_table)
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
                _require_posting_currency_match(
                    directive.metadata['currency'], ar_account,
                    'invoice', inv_id, ar_acct_name)
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
                    _attach_posting_rate(
                        invoice, book, directive, DirectiveType.INVOICE_ENTRY,
                        post_date, fx_rates, 'invoice', inv_id)
                    _require_the_account_can_hold_the_total(
                        invoice, ar_account, 'invoice', inv_id, ar_acct_name)
                    invoice.PostToAccount(ar_account, post_date, due_date, memo, accumulate, False)
                    # Override the transaction description GnuCash set automatically,
                    # so the roundtrip preserves the memo field exactly.
                    posting_txn = invoice.GetPostedTxn()
                    if posting_txn:
                        posting_txn.BeginEdit()
                        posting_txn.SetDescription(memo)
                        set_custom_metadata(posting_txn, _BUSINESS_GENERATED_META)
                        posting_txn.CommitEdit()
                        # Q-035: a foreign-currency A/R split is a cost basis —
                        # this many units at what the income was booked at.
                        record_cost_bases(book, posting_txn)
            elif entry_directive.type == DirectiveType.PAYMENT:
                # Credit blocks wait for the rest. What a credit may take is
                # what the document still owes, and that depends on the cash
                # beside it — applied where its own line falls, a credit
                # written above a cash block took the whole document and the
                # cash below it landed as a prepayment nobody asked for. The
                # file says the same thing whichever order it is written in.
                if not _is_falsy(str(entry_directive.metadata.get(
                        'from_credit', 'false'))):
                    credit_blocks.append(entry_directive)
                else:
                    _apply_payment_directive(invoice, entry_directive, book,
                                             is_bill=False, fx_rates=fx_rates)

        for credit_block in credit_blocks:
            _apply_payment_directive(invoice, credit_block, book, is_bill=False,
                                     fx_rates=fx_rates)

        # Q-015: auto_apply_credit consumes the customer's open prepayment
        # lots toward this invoice via gncInvoiceAutoApplyPayments. Cash
        # payments above are applied first; auto-apply then fills any
        # remaining balance from existing credit. A `from_credit:` block does
        # not come through here: it names the credit to spend and divides
        # that one itself.
        if not _is_falsy(str(directive.metadata.get('auto_apply_credit', 'false'))):
            if invoice.GetPostedTxn() is None:
                raise Exception(
                    f'Invoice {inv_id}: auto_apply_credit requires a posted: '
                    f'block (cannot apply credit to an unposted invoice)'
                )
            _apply_owner_credit(invoice)

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
            subtotal = Fraction(0)
            tax_total = Fraction(0)
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

        _merge_custom_metadata(invoice, directive.metadata,
                               KNOWN_INVOICE_METADATA_KEYS)
        logging.debug(
            f"{'Updated' if status_on_success == 'updated' else 'Created'} "
            f"invoice {directive.props['id']}"
        )
        return status_on_success

    @staticmethod
    def import_bill(directive: PlaintextDirective, book: Book,
                    on_orphan_warning=None, fx_rates=None):
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
        _refuse_a_changed_currency(existing, directive, 'bill', bill_id)
        _refuse_a_document_that_would_lose_its_lines(
            existing, directive, DirectiveType.BILL_ENTRY, 'bill', bill_id)

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
            migrated = _move_slot_keys_that_became_fields(
                existing, KNOWN_BILL_METADATA_KEYS)
            if _bill_matches_directive(existing, directive, book):
                # As the invoice side: a migration is a change to save for.
                if migrated:
                    logging.debug(f"Bill {bill_id}: slot keys migrated to fields")
                    return 'updated'
                logging.debug(f"Bill {bill_id} already matches directive; unchanged")
                return 'unchanged'
            if _is_only_unpost_diff(existing, directive, is_bill=True):
                logging.debug(
                    f"Bill {bill_id}: only difference is posted→posted:none; "
                    f"minimal unpost (entry GUIDs preserved)"
                )
                require_cost_basis_unused(book, existing, 'bill', bill_id)
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
                # Already cash-before-credit, as on the invoice side above.
                for pay_dir in added_pays:
                    _apply_payment_directive(existing, pay_dir, book,
                                             is_bill=True, fx_rates=fx_rates)
                return 'updated'
            status_on_success = 'updated'
            if existing.GetPostedTxn() is not None:
                logging.debug(f"Bill {bill_id} is posted but differs; unposting for rebuild")
                require_cost_basis_unused(book, existing, 'bill', bill_id)
                _emit_orphan_warning_before_unpost(
                    existing, 'bill', bill_id, on_orphan_warning)
                existing.Unpost(False)

        if existing is None:
            # A vendor bill is a gncInvoice with a Vendor owner; the SWIG
            # `Bill` class (a subclass of Invoice) is what makes AddEntry /
            # RemoveEntry dispatch to the gncBill* functions, so we construct
            # it as Bill rather than Invoice.
            vendor = _resolve_cross_reference(
                'vendor',
                directive.metadata.get('vendor_id'),
                directive.metadata.get('vendor_guid'),
                lambda i: _find_vendors_by_id(book, i),
                lambda g: _find_vendor_by_guid(book, g),
            )
            bill = Bill(book, bill_id, book.get_table().lookup("CURRENCY", directive.metadata['currency']), vendor)
            if must_set_guid is not None:
                _set_object_guid(book, bill, 'bill', bill_id, must_set_guid)
        else:
            # Existing bill (unposted now, after the Unpost above if needed):
            # reuse it, drop its current entries. `_find_bills_by_id` /
            # `_find_bill_by_guid` return a Bill, so RemoveEntry dispatches to
            # gncBillRemoveEntry (correctly clearing the bill's entry list).
            bill = existing
            for old_entry in list(bill.GetEntries()):
                bill.RemoveEntry(old_entry)
                old_entry.Destroy()
        bill.BeginEdit()
        bill.SetDateOpened(datetime.strptime(directive.metadata['date_opened'], "%Y-%m-%d"))

        # As the invoice writes them. Read and compared but never written,
        # `notes:` went to the slot, `GetNotes()` stayed empty, and the
        # comparison that reads it could never answer `unchanged` — so every
        # re-import of an unchanged ledger unposted the bill and built it
        # again, destroying the posting and orphaning its payments each time.
        if 'billing_id' in directive.metadata:
            bill.SetBillingID(directive.metadata['billing_id'])
        if 'notes' in directive.metadata:
            bill.SetNotes(directive.metadata['notes'])
        credit_blocks = []

        for entry_directive in directive.children:
            if entry_directive.type == DirectiveType.BILL_ENTRY:
                # Resolved before the entry exists, as the invoice side does
                # it: a refusal after `Entry(book)` leaves a half-built entry
                # in an open edit, attached to nothing.
                bill_acct_name = entry_directive.metadata['account']
                bill_acct = find_account(book.get_root_account(), bill_acct_name)
                if bill_acct is None:
                    raise Exception(f'Account {bill_acct_name!r} not found when creating bill entry')
                bill_tax_table = (
                    _the_tax_table_named(
                        book, entry_directive.metadata['tax_table'],
                        'bill', directive.props['id'])
                    if 'tax_table' in entry_directive.metadata else None)

                entry = Entry(book)
                entry.BeginEdit()
                entry.SetDate(datetime.strptime(entry_directive.metadata['date'], "%Y-%m-%d"))
                entry.SetDescription(entry_directive.metadata['description'])
                entry.SetBillAccount(bill_acct)
                entry.SetQuantity(string_to_gnc_numeric_quantity(entry_directive.metadata['quantity']))
                entry.SetBillPrice(string_to_gnc_numeric_quantity(entry_directive.metadata['price']))
                entry.SetBillTaxable(entry_directive.metadata['taxable'] == 'true')
                # Mirror the invoice-side wiring (SetInvTaxIncluded): a bill
                # entry's `tax_included: true` means the entered price already
                # contains the tax, so GnuCash must back the net out at post
                # time (net = gross / (1 + total_rate)). `tax_included` is
                # optional on bill entries — default false (tax added on top).
                entry.SetBillTaxIncluded(
                    entry_directive.metadata.get('tax_included', 'false') == 'true')
                if bill_tax_table is not None:
                    entry.SetBillTaxTable(bill_tax_table)
                # `bill` is a Bill, so AddEntry dispatches to gncBillAddEntry,
                # which sets the entry's bill-side owner pointer. GnuCash then
                # persists the bill-side tax flags (b-taxable / b-taxincluded);
                # the customer-invoice Invoice.AddEntry would drop them on save
                # and over-tax the bill.
                bill.AddEntry(entry)
                entry.CommitEdit()
            elif entry_directive.type == DirectiveType.POSTED:
                ap_acct_name = entry_directive.metadata['ap_account']
                ap_account = find_account(book.get_root_account(), ap_acct_name)
                if ap_account is None:
                    raise Exception(f'AP account {ap_acct_name!r} not found when posting bill {directive.props["id"]}')
                _require_posting_currency_match(
                    directive.metadata['currency'], ap_account,
                    'bill', bill_id, ap_acct_name)
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
                    _attach_posting_rate(
                        bill, book, directive, DirectiveType.BILL_ENTRY,
                        post_date, fx_rates, 'bill', bill_id)
                    _require_the_account_can_hold_the_total(
                        bill, ap_account, 'bill', bill_id, ap_acct_name)
                    bill.PostToAccount(ap_account, post_date, due_date, memo, accumulate, False)
                    # Override the transaction description GnuCash set automatically,
                    # so the roundtrip preserves the memo field exactly.
                    posting_txn = bill.GetPostedTxn()
                    if posting_txn:
                        posting_txn.BeginEdit()
                        posting_txn.SetDescription(memo)
                        set_custom_metadata(posting_txn, _BUSINESS_GENERATED_META)
                        posting_txn.CommitEdit()
                        # Q-035: a foreign-currency A/P split is a cost basis —
                        # this many units at what the expense was booked at.
                        record_cost_bases(book, posting_txn)
            elif entry_directive.type == DirectiveType.PAYMENT:
                # After the cash, for the reason given on the invoice side.
                if not _is_falsy(str(entry_directive.metadata.get(
                        'from_credit', 'false'))):
                    credit_blocks.append(entry_directive)
                else:
                    _apply_payment_directive(bill, entry_directive, book,
                                             is_bill=True, fx_rates=fx_rates)

        for credit_block in credit_blocks:
            _apply_payment_directive(bill, credit_block, book, is_bill=True,
                                     fx_rates=fx_rates)

        # Q-015: symmetric to the invoice side — consume vendor credit lots.
        # A `from_credit:` block does not come through here: it names the
        # credit to spend and divides that one itself.
        if not _is_falsy(
                str(directive.metadata.get('auto_apply_credit', 'false'))):
            if bill.GetPostedTxn() is None:
                raise Exception(
                    f'Bill {bill_id}: auto_apply_credit requires a posted: '
                    f'block (cannot apply credit to an unposted bill)'
                )
            # Q-035: what the book overpaid a vendor is currency it has a claim
            # on, at the cost it was sent at, and applying part of that claim
            # carves the split it lives on — so the basis follows what is left,
            # exactly as it does on the receivable side.
            _apply_owner_credit(bill)

        bill.CommitEdit()
        _merge_custom_metadata(bill, directive.metadata,
                               KNOWN_BILL_METADATA_KEYS)
        logging.debug(
            f"{'Updated' if status_on_success == 'updated' else 'Created'} "
            f"bill {directive.props['id']}"
        )
        return status_on_success

    def import_business_objects(self, directives: List[PlaintextDirective], book: Book,
                                 on_directive_status=None,
                                 on_orphan_warning=None,
                                 fx_rates=None):
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
                    raise ValueError(f'company "{cname}": {_said_plainly(e)}') from e
                result.tally('company', status)
                cb('company', cname, status)

        # Customers and vendors first (invoices/bills depend on them)
        for directive in directives:
            if directive.type == DirectiveType.CUSTOMER:
                cid = directive.props.get('id', '?')
                try:
                    status = self.import_customer(directive, book)
                except Exception as e:
                    raise ValueError(f'customer "{cid}": {_said_plainly(e)}') from e
                result.tally('customer', status)
                cb('customer', cid, status)
            elif directive.type == DirectiveType.VENDOR:
                vid = directive.props.get('id', '?')
                try:
                    status = self.import_vendor(directive, book)
                except Exception as e:
                    raise ValueError(f'vendor "{vid}": {_said_plainly(e)}') from e
                result.tally('vendor', status)
                cb('vendor', vid, status)

        # Then tax tables
        for directive in directives:
            if directive.type == DirectiveType.TAXTABLE:
                tname = directive.props.get('name', '?')
                try:
                    status = self.import_taxtable(directive, book)
                except Exception as e:
                    raise ValueError(f'taxtable "{tname}": {_said_plainly(e)}') from e
                result.tally('taxtable', status)
                cb('taxtable', tname, status)

        # Finally, invoices and bills
        for directive in directives:
            if directive.type == DirectiveType.INVOICE:
                iid = directive.props.get('id', '?')
                try:
                    status = self.import_invoice(directive, book,
                                                 on_orphan_warning=on_orphan_warning,
                                                 fx_rates=fx_rates)
                except Exception as e:
                    raise ValueError(f'invoice "{iid}": {_said_plainly(e)}') from e
                result.tally('invoice', status)
                cb('invoice', iid, status)
            elif directive.type == DirectiveType.BILL:
                bid = directive.props.get('id', '?')
                try:
                    status = self.import_bill(directive, book,
                                              on_orphan_warning=on_orphan_warning,
                                              fx_rates=fx_rates)
                except Exception as e:
                    raise ValueError(f'bill "{bid}": {_said_plainly(e)}') from e
                result.tally('bill', status)
                cb('bill', bid, status)

        return result
