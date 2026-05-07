---
id: Q-006
title: Business object IDs are not unique on re-import; GUIDs are not exported
category: quality
severity: high
status: open
---

## Problem

Re-importing a plaintext file that contains business objects produces
**duplicate** records every time. After N imports of the same `customer "C001"`
directive, the book contains N customers all with `id="C001"` and N different
GUIDs.

The same applies to `vendor` directives. Tax tables likely too. Invoices and
bills are already protected via `book.InvoiceLookupByID()` (added in Q-004
work).

### Confirmed via CLI exploration (2026-05-06)

Importing the same one-customer fixture three times into the same book and
reloading after each:

```
After 1st import: count=1
   id='C001'  guid=9f14a498cc894d50931f855a9a31d594
After 2nd import: count=2
   id='C001'  guid=bb63928499924429a0283205cc1f1278
   id='C001'  guid=9f14a498cc894d50931f855a9a31d594
After 3rd import: count=3
   id='C001'  guid=f66df24e6e75424ba08c2b0a47ec292c
   id='C001'  guid=bb63928499924429a0283205cc1f1278
   id='C001'  guid=9f14a498cc894d50931f855a9a31d594
```

Subsequent `export --include-business-objects` emits **three** `customer "C001"`
blocks — the duplicates are persisted to disk and round-trip through export.

## Root cause

In `services/gnucash_importer.py`:

```python
def import_customer(directive, book):
    customer = Customer(book, directive.props['id'], ...)   # always creates
    customer.SetName(directive.metadata['name'])
    ...
```

`Customer(book, id, currency)` in the GnuCash bindings calls
`gncCustomerCreate` + `gncCustomerSetID` with **no uniqueness check**. GnuCash
keys customers by GUID internally, so any number of records can share the same
user-facing `id`. `import_vendor` is structurally identical and has the same
bug. `import_taxtable` likely too.

## Why our tests miss this

`test_business_objects_persisted_when_imported_into_existing_file`
(`tests/integration/test_business_objects.py:437`) actually imports the same
customer twice into one file but the only assertion on the customer side is:

```python
assert 'customer "1"' in exported_biz or 'Test Customer' in exported_biz
```

This passes whether the export contains **one** customer block or **three**.
We never count.

KVP-related tests (`tests/integration/test_kvp_all_objects.py`) all use
distinct IDs (`CUST-010`, `CUST-011`, …), so they never re-import the same ID.

## Conceptual point: ID is not really an ID

GnuCash treats GUID as the primary key. The `id` field on a customer is just
a user-facing number that the GUI happens to require to be unique through UX
(the New Customer dialog auto-increments and rejects collisions). Programmatic
creation via the bindings bypasses that constraint.

For our plaintext format we should enforce ID uniqueness **at the importer
layer** because:

1. The plaintext `customer "C001"` directive uses ID as the natural handle —
   the user reads and edits the file by ID, not GUID.
2. Invoices reference customers by ID (`customer_id: "C001"`). If two
   customers share that ID, the lookup `book.CustomerLookupByID("C001")`
   returns whichever GnuCash finds first, which is non-deterministic. Invoice
   posting could attach to the wrong customer.
3. The user's mental model is "one ID = one customer". Silently allowing
   duplicates breaks that contract.

## Proposed fix

### 1. Idempotent update on re-import (decision: update, not skip)

On re-import, mutable fields (name, address, active flag, custom KVP) are
**updated** on the existing record. This matches the user's mental model that
"edit the text and re-import" should propagate changes. The Q-004 invoice
idempotency was driven by "don't create a new lot for an already-paid
invoice", which doesn't apply here — customer/vendor/tax-table fields are
plain user data.

### 2. ID and GUID are both immutable handles — conflicts must be errors

Once a customer/vendor exists in GnuCash, two things cannot be changed
programmatically without surprising the user:

- **GUID** — GnuCash's internal primary key, immutable by design.
- **Customer number / ID** — semantically the user-facing handle. The user's
  mental contract is "one number = one customer". We refuse to silently
  rename a customer because that would corrupt invoices that reference the
  old number.

So if a re-import directive provides both a `guid:` and an `id` (the
directive header), they must agree with whatever is already in the book.
Anything else is a user mistake we surface, not a thing we paper over.

**Resolution table** for `import_customer` (vendor/taxtable analogous):

| `guid:` provided? | GUID lookup | ID lookup | Action |
|---|---|---|---|
| no | — | not found | **create** new customer with given id |
| no | — | found (1 match) | **update** fields on the matched customer |
| no | — | found (multiple matches) | **error**: book has pre-existing duplicates for this id; user must resolve in GnuCash GUI |
| yes | not found | not found | **create** new (and use the supplied GUID — see §3) |
| yes | not found | found | **error**: directive's GUID is unknown but its id matches an existing customer; refusing to rebuild because we cannot assign that GUID without overwriting the existing one. User intent is ambiguous (rename? new entity? typo?) |
| yes | found, id matches | (matches same record) | **update** fields |
| yes | found, id mismatch | — | **error**: GUID resolves to customer with id=X but directive says id=Y; refusing to rename because Y may be in use by another record or referenced by invoices |

The "error" rows are the safety net the user is asking for: any time the
directive's claims don't line up with the book, halt before mutating anything.

### 3. Export GUID alongside ID for every business object

The plaintext export currently emits:

```
customer "C001"
	name: "Acme"
	currency: CAD
```

…with no GUID. This means a user editing the file cannot disambiguate two
customers if duplicates somehow exist, and the plaintext format silently
loses information that survives across GnuCash UI sessions.

Add `guid:` as an optional field for `customer`, `vendor`, `taxtable`,
`invoice`, `bill` — emitted on export, accepted on import, but not required
in hand-written files:

```
customer "C001"
	guid: 9f14a498cc894d50931f855a9a31d594
	name: "Acme"
	currency: CAD
```

When `guid:` is present and points to a customer that doesn't yet exist in
the book (e.g. round-trip into a fresh book), we honour it via
`qof_instance_set_guid` immediately after `Customer(book, id, currency)`.
This keeps GUIDs stable across export → fresh-book → import cycles, the same
property transactions already have.

### 4. Cross-object references export both id and guid; import requires agreement

Each business object block declares its own GUID via the universal `guid:`
field (§3). On top of that, the two cross-object references in the
business-object format — invoice → customer, bill → vendor — export **both**
the referenced object's id and its guid:

```
invoice "INV-001"
	customer_id: "C001"
	customer_guid: 9f14a498cc894d50931f855a9a31d594
	currency: CAD
	date_opened: 2026-01-01
	...
```

```
bill "BILL-001"
	vendor_id: "V001"
	vendor_guid: f66df24e6e75424ba08c2b0a47ec292c
	currency: CAD
	...
```

**Import resolution rule** (parallels §2). For each cross-reference (writing
generically as `<role>_id` / `<role>_guid` where `<role>` is `customer` or
`vendor`):

| `<role>_id` provided? | `<role>_guid` provided? | Action |
|---|---|---|
| yes | no | look up by id; error if not found or multiple matches (the latter only happens in legacy hand-written files; see §5) |
| no | yes | look up by guid; error if not found |
| yes | yes | look up by guid, then verify the matched record's id equals `<role>_id`; error on any mismatch (`customer_guid points to record with id "C002", but directive says customer_id "C001"`) |
| no | no | error: invoice/bill missing required customer/vendor reference |

The double-reference is for round-trip safety: the id keeps the file
human-readable, the guid is the precise key the importer trusts, and the
agreement check catches manual edits where one was changed but not the
other.

**Other cross-references stay unchanged.** Accounts in `entry: account:` /
`posted: ar_account:` / `payment: bank_account:` / etc. are looked up by
full name; tax tables in `entry: tax_table:` are looked up by name;
commodities by `(namespace, mnemonic)`. These do not get guid pairs because
GnuCash's structural rules already enforce uniqueness for them
(parent-child enforced for accounts, name-keyed for tax tables, composite
key for commodities). If a future test proves otherwise, that's a separate
issue.

### 5. Books with pre-existing duplicates surface at import time

Plaintext-driven flows after this fix never create duplicates. A book that
*already* contains duplicates (legacy import done before this fix, manual
book edits, etc.) is caught by the "found (multiple matches)" row in §2's
resolution table — the importer halts with a clear error and asks the user
to resolve in the GnuCash GUI before re-running. No export-side warning
needed.

## Scope

| Object type | Has unique-by-ID lookup? | Bug present? |
|---|---|---|
| Customer | `book.CustomerLookupByID()` exists, not used in import | Yes |
| Vendor | `book.VendorLookupByID()` exists, not used in import | Yes |
| Tax table | `gncTaxTableLookupByName()` exists | Likely (untested) |
| Invoice | `book.InvoiceLookupByID()` used since Q-004 | No |
| Bill | `book.InvoiceLookupByID()` used since Q-004 | No |

## Files to change

| File | Change |
|---|---|
| `services/gnucash_importer.py` | `import_customer`/`import_vendor`/`import_taxtable`: lookup by ID before create; on hit, update rather than create. Honour optional `guid:` directive field for precise lookup. |
| `use_cases/export_business_objects.py` | Emit `guid:` field for every business object block. |
| `tests/integration/test_business_objects.py` | Strengthen `test_business_objects_persisted_when_imported_into_existing_file` to assert exactly one block per ID. Add explicit re-import-creates-no-duplicate test. |
| `tests/fixtures/business_objects_only.txt` | Add `guid:` lines after the regenerated export uses them. |
| `README.md` | Document the new optional `guid:` field on customer/vendor/etc. blocks; mention re-import semantics (update fields, no duplicates). |

## Out of scope

- Backfilling fixes for books that already have pre-existing duplicates
  (those need manual cleanup in the GnuCash GUI).
- Customer/vendor *deletion* on re-import when a directive disappears from
  the file — covered by F-011 archive/delete commands.
- Employees and Jobs — not currently imported.

## Open questions

1. Should `customer_id:` references in invoices be validated against the
   set of declared customer IDs at parse time? Probably yes, but a separate
   issue from this one.
2. Setting a fresh customer's GUID via `qof_instance_set_guid` requires
   `BeginEdit/CommitEdit` semantics — needs verification on all platforms
   (the same ctypes-vs-SWIG pitfalls that bit Q-004's
   `xaccSplitSetAccount` likely apply here).

---

**Created**: 2026-05-06
