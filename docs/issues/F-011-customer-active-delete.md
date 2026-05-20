---
id: F-011
title: "Customer/vendor active flag round-trip and safe deletion"
category: feature
severity: high
status: closed
---

## Problem

### 1. `active` flag is silently lost on export/import

GnuCash customers and vendors have an `active` boolean (managed via
`SetActive(bool)` / `GetActive()`).  A customer marked inactive
(`SetActive(False)`) is hidden from the GnuCash UI but remains in the book.

Currently:

- **Exporter** never emits the `active` field → inactive customers look
  identical to active ones in the plaintext file.
- **Importer** never calls `SetActive` → re-importing silently resurrects
  every previously deactivated customer/vendor back to active.

A round-trip through plaintext is therefore **data-lossy** for any book that
uses the retire/hide workflow.

### 2. No way to delete a customer that has no invoices

Clients occasionally want to fully remove a customer they created by mistake
(typo in name, duplicate entry, etc.) before any invoices are raised against
it.

> **Note on customer deletion**: deletion is a destructive, irreversible
> operation. The recommended approach for retiring a customer is always
> `archive-customers` (soft-hide via `SetActive(False)`), which preserves all
> invoice history. `delete-customers` should only be used for customers that
> were created by mistake and have never had any invoices raised against them.

GnuCash exposes two options via Python bindings:
- `SetActive(False)` — hides the customer; invoices are unaffected.
- `Destroy()` — hard-deletes the customer from the QOF entity store.

**Research findings** (verified in Docker, GnuCash 5.x):

| Scenario | Customer lookup | Invoice owner after reload |
|---|---|---|
| `SetActive(False)` | found, `active=False` | intact, correct GUID |
| `Destroy()` with no invoices | NOT FOUND | n/a |
| `Destroy()` with invoices | NOT FOUND | `owner:id = 000...000` (null GUID) |

`Destroy()` with linked invoices produces **permanent XML corruption**: the
invoice's `<owner:id>` is written as the null GUID
(`00000000000000000000000000000000`), making it an unrecoverable orphan.
GnuCash itself logs `qof_commit_edit(): unbalanced call` during the destroy.

Safe rule: **only allow `Destroy()` when the customer has zero invoices**.

---

## Proposed Changes

### A. Active flag round-trip (customers and vendors)

#### Exporter (`use_cases/export_business_objects.py`)

Emit `active: false` on the customer/vendor block when `GetActive()` is
`False`. Omit the field entirely when `True` (default — no noise for the
common case).

```
customer "CUST001"
  name: "Retired Corp"
  currency: CAD
  active: false
```

Same for vendor blocks.

#### Importer (`services/gnucash_importer.py`)

After `CommitEdit()`, check for the `active` key and call `SetActive(False)`
when the value evaluates to falsy. Accepted falsy literals: `false`, `0`,
`no`, `False` (case-insensitive). Any other value (or absent key) → leave
active (default `True`).

```python
_FALSY = {'false', '0', 'no'}

def _is_falsy(val: str) -> bool:
    return val.strip().lower() in _FALSY
```

Note: `active` must be added to `KNOWN_CUSTOMER_METADATA_KEYS` and
`KNOWN_VENDOR_METADATA_KEYS` in `infrastructure/gnucash/kvp.py` so it is not
mistakenly written as KVP custom metadata.

### B. CLI commands: `delete-customers` and `archive`

Both operations are imperative and do not belong in the declarative plaintext
format. They are exposed as CLI commands that accept one or more IDs and
report per-ID status.

#### `delete-customers` — hard remove customers (blocked if invoices exist)

> **Vendor deletion is not implemented.** GnuCash's `gncVendorDestroy()`
> does not properly remove the vendor from the XML backend's serialization
> path — the vendor entity persists in the saved file regardless of the
> in-memory state. This is a GnuCash-level issue that cannot be worked around
> from Python. Use `archive-vendors` to soft-hide vendors instead.
> Customer deletion (`gncCustomerDestroy`) works correctly.

```
gnucash-plaintext delete-customers FILE ID [ID ...]
```

Per-ID logic:
1. Look up by ID. If not found → `ID: not found`, mark failed.
2. Query all invoices for this customer (any status — paid, unpaid,
   posted, unposted all count).
3. If any linked → `ID: failed — cannot delete, N invoice(s) linked`, mark failed.
4. If none → call `Destroy()`, save, print `ID: deleted`.

Sample output (same IDs as archive for comparison):
```
CUST001: deleted
CUST002: failed — cannot delete, 3 invoice(s) linked
CUST003: failed — cannot delete, 3 invoice(s) linked
CUST004: not found
```

Note that CUST002 (has invoices) and CUST003 (already archived, but has
invoices) both fail delete for the same reason — the active flag is
irrelevant to whether delete is allowed.

#### `archive` — soft hide via `SetActive(False)` (always succeeds per found ID)

```
gnucash-plaintext archive-customers FILE ID [ID ...]
gnucash-plaintext archive-vendors   FILE ID [ID ...]
```

Per-ID logic:
1. Look up by ID. If not found → `ID: not found`, mark failed.
2. If already inactive → `ID: already archived`, mark failed.
3. Count linked invoices/bills.
4. Call `SetActive(False)`, save.
   - If linked count > 0 → `ID: archived — N invoice(s) linked` (informational, not a failure).
   - Otherwise → `ID: archived`.

Sample output:
```
CUST001: archived
CUST002: archived — 3 invoice(s) linked
CUST003: already archived
CUST004: not found
```

`SetActive(False)` never corrupts linked invoices/bills — the invoice count
is informational only, telling the user why `delete` would have been blocked.
Verified in Docker: invoice owner GUID remains intact after save/reload.

#### Exit codes (both commands)

Exit code `0` only when every requested ID succeeded. Any failed or
not-found ID → exit code `1`.

#### Why payment status does not matter for `delete-customers`

Verified in Docker: `Destroy()` on a customer with a fully **paid** invoice
produces the same null-GUID XML corruption as an unpaid invoice. The invoice
stores the customer GUID as a foreign key regardless of payment state —
once the customer entity is freed, GnuCash writes
`<owner:id type="guid">00000000000000000000000000000000</owner:id>`.

---

## Files to Change

| File | Change |
|---|---|
| `infrastructure/gnucash/kvp.py` | Add `'active'` to `KNOWN_CUSTOMER_METADATA_KEYS` and `KNOWN_VENDOR_METADATA_KEYS` |
| `use_cases/export_business_objects.py` | Emit `active: false` in `_export_customers` and `_export_vendors` when inactive |
| `services/gnucash_importer.py` | Call `SetActive(False)` in `import_customer`/`import_vendor` when `active` field is present and falsy |
| `use_cases/delete_business_objects.py` | New: `DeleteCustomersUseCase`, `ArchiveCustomersUseCase`, `ArchiveVendorsUseCase`; each returns list of `(id, status, detail)` |
| `cli/delete_cmd.py` | New Click commands `delete-customers`, `archive-customers`, `archive-vendors`; print per-ID status; exit 1 if any failed |
| `cli/main.py` | Register the three new commands |
| `tests/fixtures/business_objects.txt` | Add an inactive customer and inactive vendor to the round-trip fixture |
| `tests/integration/test_business_objects.py` | Assert `active: false` survives round-trip |
| `tests/integration/test_delete_business_objects.py` | New: delete succeeds with no invoices; delete fails with linked invoices; archive sets inactive; archive on already-inactive; not-found; exit codes |

---

## Out of Scope

- Deleting invoices/bills (out of scope — too destructive without a full audit trail).
- Deleting tax tables (GnuCash does not garbage-collect orphan tables; out of scope).
- `active` flag on invoices themselves (`gncInvoiceSetActive` exists but is
  internal to GnuCash's posting workflow — not user-facing).

---

## Research Notes

### Compatibility matrix (verified in Docker across all supported distros)

| Distro | GnuCash | `SetActive(False)` persists | `GetActive()` after reload | Invoice owner intact | `Destroy()` (no invoices) removes customer |
|---|---|---|---|---|---|
| Debian 13 (latest) | 5.x | ✅ | ✅ `False` | ✅ | ✅ |
| Debian 12 | 4.13 | ✅ | ✅ `False` | ✅ | ✅ |
| Debian 11 | 4.4 | ✅ | ✅ `False` | ✅ | ✅ |
| Ubuntu 22.04 | 4.8 | ✅ | ✅ `False` | ✅ | ✅ |
| Ubuntu 20.04 | 3.8 | ✅ | ✅ `False` | ✅ | ✅ |

All distros confirmed with save/reload cycle and XML inspection.

**Ubuntu 20.04 API note**: `SessionOpenMode` does not exist on GnuCash 3.8.
The importer and any new CLI commands must use the existing
`make_session`/`reload_session` pattern from `conftest.py` (try/except
`ImportError` on `SessionOpenMode`). The use-case and CLI layers already go
through `GnuCashRepository` which handles this internally — no extra work
needed.

### XML behaviour

- `SetActive(False)` writes `<cust:active>0</cust:active>` to XML.
  Field is omitted entirely when active (default `True`) — no noise.
- QOF query `search_for('gncCustomer')` returns **both** active and inactive
  customers — no filtering needed in the exporter.
- `Destroy()` on a customer with any linked invoice (paid or unpaid) writes
  `<owner:id type="guid">00000000000000000000000000000000</owner:id>` to the
  invoice XML — permanent orphan, unrecoverable after reload.
- `Destroy()` with no linked invoices cleanly removes the customer; zero
  customers found after reload, no XML corruption.

### Why vendor deletion is not supported

`gncVendorDestroy()` was empirically tested across all supported distros and
confirmed broken: despite reporting success in memory (QOF query count drops
by 1 after calling Destroy), the vendor entity is **always re-written to the
XML file** on `session.save()`. After save/reload the vendor count and data
are unchanged, as if Destroy() was never called.

The same test on customers works correctly — `gncCustomerDestroy()` properly
removes the customer from the serialized file.

The root cause appears to be in GnuCash's XML backend serialization path for
vendors (the backend iterates a different internal structure from the QOF
collection for vendor entities). Calling `qof_collection_remove_entity()` via
ctypes before `Destroy()` also does not help — the vendor still reappears
after save.

**This cannot be fixed from Python without modifying GnuCash's C code.**
`archive-vendors` (`SetActive(False)`) works correctly and is the supported
path for retiring vendors.

---

**Created**: 2026-05-05
