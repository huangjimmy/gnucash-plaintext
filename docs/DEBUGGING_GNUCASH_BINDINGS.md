# Debugging GnuCash Python Bindings

## The Reality: No Decision Matrix

**Important**: There is no predictable "decision matrix" for when to use SWIG vs ctypes. GnuCash's Python bindings have platform-specific bugs and missing functions that can only be discovered through testing.

The workflow is always:
1. **Try SWIG first** - it's cleaner when it works
2. **Fall back to ctypes** when SWIG fails on some platform
3. **Document the failure** so others know why ctypes was chosen

## When a Function Doesn't Work

### Step 1: Try the High-Level SWIG API First
```python
# Usually works for object creation and writing operations
from gnucash import Customer, Vendor, Invoice
customer = Customer(book, "CUST-001", currency)
customer.SetName("Acme Corp")
customer.GetAddr().SetAddr1("123 Main St")
```

### Step 2: Check the gnucash_core_c Module
```python
import gnucash.gnucash_core_c as gc
# Sometimes works when high-level SWIG fails
# Use .instance to get raw pointer from SWIG object
is_paid = gc.gncInvoiceIsPaid(invoice.instance)
account_type = gc.xaccAccountGetType(account.instance)
```

### Step 3: Use ctypes (Last Resort)
```python
from infrastructure.gnucash.engine import load_gnc_engine
lib = load_gnc_engine()  # Handles RTLD_GLOBAL promotion for Ubuntu

# For tax tables (SWIG missing these entirely)
tt_ptr = lib.gncTaxTableGetTables(int(book.instance))

# For invoice entries (SWIG has const-type bugs)
desc = safe_ctypes_string(lib.gncEntryGetDescription, entry_ptr)
```

### Step 4: Platform Testing Checklist
You MUST test on all supported platforms — all eleven, which is what
`./scripts/test-all-versions-parallel.sh` runs in one go:
- [ ] Debian 10 (GnuCash 3.4, Python 3.7) - minimum version
- [ ] Ubuntu 20.04 (GnuCash 3.8)
- [ ] Debian 11 (GnuCash 4.4)
- [ ] Ubuntu 22.04 (GnuCash 4.8)
- [ ] Debian 12 (GnuCash 4.13)
- [ ] Ubuntu 24.04 (GnuCash 5.5)
- [ ] Debian 13 (GnuCash 5.10)
- [ ] Fedora 41 (GnuCash 5.13)
- [ ] Ubuntu 26.04 (GnuCash 5.14)
- [ ] Arch Linux (GnuCash 5.15)
- [ ] openSUSE Tumbleweed (GnuCash 5.16)

**Common pattern**: Works on Debian, segfaults on Ubuntu → RTLD_LOCAL issue.

## Common Failure Patterns

### 1. "Missing function" in SWIG
- **Symptom**: `AttributeError: module 'gnucash' has no attribute 'gncTaxTableGetTables'`
- **Cause**: SWIG bindings are incomplete for some C functions
- **Solution**: Use ctypes - the function exists in libgnc-engine.so

### 2. Segfault on Ubuntu but works on Debian
- **Symptom**: Works on Debian 11/12/13, crashes on Ubuntu 22/24
- **Cause**: Python loads GnuCash extensions with `RTLD_LOCAL` on Ubuntu
- **Solution**: Use `engine.py`'s `load_gnc_engine()` which promotes to `RTLD_GLOBAL`

### 3. Const-type mismatch in SWIG
- **Symptom**: Function exists but returns garbage or crashes
- **Example**: `gncEntryGetDescription()` in SWIG has wrong const qualifiers
- **Solution**: Use ctypes version from `lib.gncEntryGetDescription()`

### 4. 64-bit pointer truncation
- **Symptom**: Random segfaults, especially with addresses > 4GB
- **Cause**: Missing `argtypes` in ctypes (defaults to 32-bit C `int`)
- **Solution**: Always set `argtypes = [ctypes.c_void_p]` for pointer arguments

## Reading vs Writing Asymmetry

GnuCash Python bindings have different reliability for reading vs writing:

### Writing (Import) - SWIG Usually Works
- `Customer()`, `Vendor()`, `Invoice()` constructors work
- `SetName()`, `SetAddress()`, `SetCurrency()` work reliably
- **Exception**: Tax table entries need `gnucash_core_c` helpers

### Reading (Export) - Often Needs ctypes
- `gncTaxTableGetTables()`: Missing from SWIG (always ctypes)
- `gncEntryGetDescription()`, `gncEntryGetAction()`: SWIG has const-type bugs
- `xaccAccountGetName()`: Works in ctypes, SWIG version buggy on Ubuntu
- `gnc_account_get_full_name()`: Use ctypes version for raw pointers
- `xaccSplitGetAccount()`: SWIG const-type mismatch on all platforms — always ctypes
- `xaccSplitGetAmount()`: SWIG `split.GetAmount().to_double()` confirmed working on
  Debian 11/12/13, Ubuntu 20/22/24. ctypes (`GncNumericC` restype) also works
  and is used when split_ptr is already in the ctypes domain ("once ctypes, stay ctypes").

## Pointer Lifetime Rules

### Rule 1: Once ctypes, stay ctypes
If you get a pointer from ctypes, use ctypes to read from it:
```python
# ✅ CORRECT
acct_ptr = lib.gncTaxTableEntryGetAccount(tte_ptr)  # ctypes
name = safe_ctypes_string(lib.xaccAccountGetName, acct_ptr)

# ❌ WRONG - SWIG may not wrap raw pointers safely
acct_ptr = lib.gncTaxTableEntryGetAccount(tte_ptr)
account = Account(instance=acct_ptr)  # Dangerous!
```

### Rule 2: SWIG ↔ ctypes bridge via `.instance`
```python
# Safe: SWIG object → ctypes pointer
entry_ptr = int(entry.instance)  # Get raw pointer from SWIG
desc = lib.gncEntryGetDescription(entry_ptr)  # Use ctypes

# Dangerous: ctypes pointer → SWIG object
# Only do this if you KNOW the pointer came from SWIG originally
raw_ptr = lib.gncTaxTableEntryGetAccount(tte_ptr)
# ❌ account = Account(instance=raw_ptr)  # Usually unsafe
```

## Utility Functions in `engine.py`

The `infrastructure/gnucash/engine.py` module provides:

### `load_gnc_engine()`
- Handles RTLD_GLOBAL promotion for Ubuntu compatibility
- Sets mandatory `argtypes` for 64-bit pointer safety
- Tries multiple library paths across distributions

### GList Structure & Iterator
```python
# Use these for safe GList traversal
from infrastructure.gnucash.engine import GList, iterate_glist

# Instead of raw pointer arithmetic:
results = iterate_glist(lib, glist_ptr, lambda lib, ptr: process_item(lib, ptr))
```

### Safe String Decoding
```python
from infrastructure.gnucash.engine import safe_ctypes_string

# Instead of manual null checks:
name = safe_ctypes_string(lib.xaccAccountGetName, acct_ptr, default="?")
```

## Adding New ctypes Functions

When you discover a new function that needs ctypes:

1. Add to `_setup_lib_restypes()` in `engine.py`:
```python
lib.new_function_name.restype = ctypes.c_void_p
lib.new_function_name.argtypes = [ctypes.c_void_p]  # REQUIRED for pointers
```

2. Test on all platforms
3. Document why SWIG failed

## Running the Test Suite

Always run the comprehensive test suite:
```bash
# In Docker (tests all platforms)
./scripts/test-all-versions.sh

# Or test a specific distribution
./scripts/test-in-docker.sh debian:13
```

The test suite will catch platform-specific failures that guide you to use ctypes.

## Commit Message Documentation

When you add ctypes for a function, document WHY in the commit:
```
fix: Use ctypes for gncEntryGetDescription

SWIG's gncEntryGetDescription has const-type mismatches that:
- Work on Debian but return garbage on Ubuntu 22/24
- Discovered during platform testing (test_business_objects_roundtrip)
- ctypes version works reliably across all distributions
```

## Invoice / Bill Payment — Hard-Won Findings

Discovered 2026-03-27 while implementing multi-payment test coverage.

### 1. `ApplyPayment` — always pass `None` for the transaction argument

`gncInvoiceApplyPayment(invoice, txn, ...)` creates the payment transaction
internally when `txn` is `NULL`/`None`. **Never** allocate the transaction
yourself with `xaccMallocTransaction` and pass it in.

```python
# ❌ WRONG — segfaults on GnuCash 3.8 (ubuntu20)
new_txn = Transaction(instance=gc.xaccMallocTransaction(book.instance))
invoice.ApplyPayment(new_txn, bank, amount, exch, date, memo, num)

# ✅ CORRECT — GnuCash allocates and initialises the transaction internally
invoice.ApplyPayment(None, bank, amount, exch, date, memo, num)
```

**Why it segfaults**: `ApplyPayment` calls `xaccTransBeginEdit(txn)` internally.
A transaction created via `Transaction(instance=xaccMallocTransaction(...))` in
Python has not been through the same GnuCash object-initialisation path that
`ApplyPayment` expects. On GnuCash 3.8, this causes a GLib assertion failure
(`g_type_instance_get_private: instance != NULL`) and SIGSEGV.

On GnuCash 4.x/5.x the manually-allocated transaction happened to work
(probably because the object model changed), but the `None` path is correct
and portable on all versions.

### 2. Payment memo lives on the split, not the transaction description

```python
# ❌ WRONG — txn.GetDescription() returns the owner/customer name, not the memo
pay_memo = txn.GetDescription()   # e.g. "Acme Corp" on OpenSUSE GnuCash 5.x

# ✅ CORRECT — read memo from the bank (non-AR) split
for i in range(txn.CountSplits()):
    split = txn.GetSplit(i)
    acct = split.GetAccount()
    atype = gc.xaccAccountGetType(acct.instance)
    if atype not in (gc.ACCT_TYPE_RECEIVABLE, gc.ACCT_TYPE_PAYABLE):
        pay_memo = split.GetMemo() or ''
        break
```

**Why**: `gncInvoiceApplyPayment` calls `xaccTransSetDescription(txn, owner_name)`
unconditionally — the `memo` parameter is stored on the splits, not the
transaction description. On newer GnuCash (Debian 13, Ubuntu 22/24) the
description was incidentally set to the memo by some code path, but on
OpenSUSE/GnuCash 5.x it contains the customer name. Reading from the split is
the only portable approach.

### 3. Pass `''` not `None` for `const char*` parameters on GnuCash 3.8

```python
# ❌ WRONG — None may be passed as NULL, which some GnuCash 3.8 functions
#           do not guard against
num = entry_directive.metadata.get('num', None)
invoice.ApplyPayment(None, bank, amount, exch, date, memo, num)

# ✅ CORRECT — empty string is always safe for optional const char* args
num = entry_directive.metadata.get('num', '')
invoice.ApplyPayment(None, bank, amount, exch, date, memo, num)
```

**Scope**: This pattern applies to any optional `const char*` SWIG binding
parameter where the field may not be present in the input. GnuCash 4.x+ is
generally null-safe, but GnuCash 3.8 on ubuntu20 is not.

### 4. Platform-specific summary for payment operations

| Platform | `ApplyPayment(None, ...)` | `split.GetMemo()` | `''` for optional num |
|---|---|---|---|
| Debian 11–13 (GnuCash 4.4–5.10) | ✅ | ✅ | ✅ |
| Ubuntu 20.04 (GnuCash 3.8) | ✅ | ✅ | ✅ required |
| Ubuntu 22 (GnuCash 4.8), 24 (5.5) | ✅ | ✅ | ✅ |
| OpenSUSE / Fedora | ✅ | ✅ (txn.GetDescription ❌) | ✅ |

## Business-Object ID and GUID — Hard-Won Findings (Q-006, 2026-05-07)

### 1. `Customer(book, id, currency)` does NOT enforce id uniqueness

Calling the SWIG constructor `Customer(book, "C001", currency)` always
creates a new record. There is no precondition check; if a customer with
id `"C001"` already exists, you end up with two records sharing the same
user-facing id but with different GUIDs. The same applies to
`Vendor(book, id, currency)`, and likely to `TaxTable` / `Employee` /
`Job`.

GnuCash keys business objects by **GUID** internally (the QofCollection
hash table), not by the user-facing id. The id is just a string field on
the entity, like `name`. The GnuCash GUI prevents duplicate ids through
UX (the "New Customer" dialog auto-increments and rejects collisions),
but the bindings bypass that constraint entirely.

**Symptom**: `gnucash-plaintext export` after re-importing the same
business-objects file emits N copies of every customer/vendor block.

**Fix in this codebase**: `_resolve_existing_or_none` in
`services/gnucash_importer.py` does `book.CustomerLookupByID(id)` /
`VendorLookupByID(id)` (or a Query when guid lookup is needed) before
the constructor and returns the existing record so the importer
updates fields rather than creating a duplicate.

### 2. GUID is unique book-wide across ALL entity types

GnuCash GUIDs sit in a single book-wide entity table. Two records of
*different* types (e.g. a customer and a transaction) cannot legally
share a GUID. However, `qof_instance_set_guid` does **not** check —
calling it with a GUID already used by some other entity silently
corrupts the book.

**Fix**: `_guid_in_use_anywhere` checks `xaccTransLookup`,
`xaccAccountLookup`, the customer query, and the vendor query before
`_set_object_guid` writes a custom GUID. Any collision raises a clear
error naming the conflicting entity type.

### 3. `Invoice` (SWIG) does not expose `GetGUID()` on all platforms

Where `Customer.GetGUID()` and `Vendor.GetGUID()` work fine via SWIG,
`Invoice.GetGUID()` raises `AttributeError` on debian13/ubuntu24. Use
ctypes via `qof_instance_get_guid(int(invoice.instance))` +
`guid_to_string_buff(buf)` instead. Tax tables only exist via ctypes
(`gncTaxTableGetTables`) so they always need this path.

### 4. `Account(instance=raw_ptr)` from a Query result is unsafe

`Query.run()` for accounts returns raw int pointers. Wrapping them in
`Account(instance=ptr)` segfaults inside the full test suite (state
pollution from earlier tests). The safe alternative: walk the account
tree from `book.get_root_account()` via `acct.get_children()`. Same
pattern presumably applies to other types — prefer iteration over the
SWIG hierarchy when available.

### 5. Plaintext-format quirk: all-digit GUIDs need quotes

`decode_value_from_string` in `infrastructure/gnucash/utils.py`
auto-converts all-digit field values to Python `int`. So
`guid: 22222222222222222222222222222222` (32 hex chars all `2`) decodes
to int `22…22`, losing the original digit count — `0000…0022` and `22`
both decode to int `22`.

The exporter emits `guid: "<hex>"` (quoted) so this never bites the
round-trip. Hand-written files must quote all-digit GUIDs; mixed-hex
forms like `b2b3…b4` work unquoted because the parser keeps strings as
strings.

`_normalise_guid` rejects non-string inputs with a message asking the
user to quote.

### 6. `book.InvoiceLookupByID(id)` does NOT find vendor bills (Q-007, 2026-05-07)

GnuCash's customer invoices and vendor bills are both stored in the
`gncInvoice` collection, distinguished only by their owner-type field
(2 = Customer, 4 = Vendor). One might assume `book.InvoiceLookupByID(id)`
queries the entire collection. It does not — it returns only customer
invoices and silently returns `None` for bills, even when a bill with
that exact id exists in the book.

**Symptom**: an idempotency check like

```python
if book.InvoiceLookupByID(bill_id) is not None:
    return  # skip; already imported
```

…is a no-op for bills. Re-importing the same bill fixture creates a
fresh duplicate every time, accumulating bills with the same id and
different GUIDs. The pre-Q-007 importer hit exactly this bug and
nobody noticed because the existing tests only checked presence
(`'bill "BILL-001"' in exported`), never count.

**Fix**: drop `InvoiceLookupByID` for bills entirely; use a `Query` over
`gncInvoice` filtered to owner-type 4. (Q-007's
`_find_bills_by_id` / `_find_bill_by_guid` in
`services/gnucash_importer.py`.)

**Verified**:

```
>>> b.InvoiceLookupByID('BILL-001')
None
>>> # …yet a Query over gncInvoice returns:
>>>   id='BILL-001'  owner_type=4
```

It's worth running the same Query-based replacement for customer
invoices too, even though `InvoiceLookupByID` does work there — having
both code paths use the same lookup shape avoids future surprises if
the SWIG behaviour changes or if a query needs to detect legacy
duplicates (multiple invoices with the same id, returned as a list).

### 7. Tax tables are not enumerable via QofQuery (Q-008, 2026-05-07)

Customer/vendor/invoice/bill objects all live in standard QOF entity
collections and are reachable via `Query.search_for(...)`. Tax tables
are not — they live in a per-book hash table accessed through
`qof_book_get_data(book, "gncTaxTable")`, and the only Python-reachable
way to enumerate them is the ctypes call:

```python
glist_ptr = lib.gncTaxTableGetTables(int(book.instance))
# returns a GList* of GncTaxTable* pointers
```

A previous session confirmed `Query().search_for('gncTaxTable')` returns
zero results. This means:

- Any "find tax tables by name/guid" code must use `gncTaxTableGetTables`
  + `iterate_glist` (ctypes), not `Query`.
- Tax-table identity work (Q-008) keeps the entire find/check path
  in ctypes per the "once ctypes, stay ctypes" rule. The resolver
  receives raw pointers and uses ctypes-aware callbacks
  (`get_id_str=_taxtable_name_str`, `get_guid_str=_taxtable_guid_str`)
  rather than SWIG `record.GetID()`/`record.GetGUID()`.

`gncTaxTableLookupByName(book, name)` (the C builtin) does work, but
returns at most one match — useless if you need to detect legacy
duplicates or build a list. Use the Query-equivalent ctypes iteration
above when you need a multi-match lookup.

### 8. `gncEntryDestroy` does NOT remove from the parent invoice/bill (2026-05-08)

`Entry.Destroy()` (which wraps `gncEntryDestroy`) sets `do_free` on the
entry's QofInstance and removes it from the QofCollection. It does
**not** detach the entry from the parent invoice/bill's internal entry
list. So:

```python
for old_entry in list(invoice.GetEntries()):
    old_entry.Destroy()
# invoice's entry list still contains dangling pointers!
invoice.PostToAccount(...)   # iterates the list → segfault on GnuCash 3.8
```

Reproduced on ubuntu20 / GnuCash 3.8. Newer GnuCash either has memory-
layout luck or has gained null-checks; the bug exists on every platform,
just doesn't always crash visibly.

**Fix**: detach before destroying.

For customer invoices:

```python
for old_entry in list(invoice.GetEntries()):
    invoice.RemoveEntry(old_entry)   # SWIG → gncInvoiceRemoveEntry
    old_entry.Destroy()
```

For vendor bills the SWIG `Invoice.RemoveEntry` wraps the
*customer-only* `gncInvoiceRemoveEntry`, which is a no-op (or worse) on
bills — same wrong-API trap as `book.InvoiceLookupByID` (#6 above).
Bills need `gncBillRemoveEntry` directly via ctypes:

```python
lib = ctypes.CDLL(None)
lib.gncBillRemoveEntry.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
for old_entry in list(bill.GetEntries()):
    lib.gncBillRemoveEntry(int(bill.instance), int(old_entry.instance))
    old_entry.Destroy()
```

The fix is in `services/gnucash_importer.py` as
`_bill_remove_all_entries`. See the post-mortem in
`docs/post-mortems/2026-05-08-bill-postto-account-segfault.md`.

## Summary

1. **No prediction possible** - test to discover failures
2. **SWIG first, ctypes when it fails** - pragmatic workflow
3. **Test all platforms** - Ubuntu/Debian differences are common
4. **Document the failures** - helps future maintainers
5. **Use engine.py utilities** - safe ctypes patterns
6. **`ApplyPayment(None, ...)`** - never pass a manually-allocated transaction
7. **Payment memo on split** - never read from `txn.GetDescription()`
8. **Business-object constructors don't dedupe by id** - lookup-before-create
9. **GUIDs are unique book-wide** - check across all entity types before forcing
10. **`Account(instance=raw_ptr)` from a Query result is unsafe** - walk the tree instead
11. **All-digit GUID values need quoting** - parser auto-converts to int
12. **`book.InvoiceLookupByID` does not find bills** - use a Query filtered by owner-type
13. **Tax tables are not in QofQuery** - enumerate via `gncTaxTableGetTables` (ctypes-only)
14. **`gncEntryDestroy` does not detach from parent invoice/bill** - call `RemoveEntry` first; bills need `gncBillRemoveEntry` via ctypes

This approach has proven necessary for maximum compatibility across Ubuntu 20/22/24 and Debian 11/12/13.