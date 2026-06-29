---
id: F-010
title: "KVP custom metadata for all GnuCash object types"
category: feature
severity: high
status: closed
---

## Summary

Extend the `plaintext_metadata` KVP slot mechanism — already implemented for
`Transaction` and `Split` — to every other GnuCash object type that gnucash-plaintext
imports and exports:

| Object type | Import | Export |
|---|---|---|
| `Transaction` | ✅ done | ✅ done |
| `Split` | ✅ done | ✅ done |
| `customer` | ❌ unknown keys silently dropped | ❌ not emitted |
| `vendor` | ❌ unknown keys silently dropped | ❌ not emitted |
| `invoice` | ❌ unknown keys silently dropped | ❌ not emitted |
| `bill` | ❌ unknown keys silently dropped | ❌ not emitted |
| `open` (account) | ❌ unknown keys silently dropped | ❌ not emitted |

TaxTable is a structured object with no natural free-form metadata slot in the
GnuCash data model; it is out of scope for this issue.

---

## Motivation

June Works uses gnucash-plaintext to manage GnuCash customer objects as the
source of truth for client data.  They need to store structured metadata beyond
the 4-line billing address (`jw.country`, `jw.postal_code`) without breaking
compatibility with the standard GnuCash address fields.

More broadly, any gnucash-plaintext user who extends their workflow with
namespace-prefixed keys (e.g. `crm.salesforce_id`, `erp.cost_centre`) on
**any** object type currently loses that data silently on import and never
sees it on export.  This is a correctness gap: gnucash-plaintext claims to
be a round-trip format, but custom keys on non-transaction objects are not
part of the round-trip.

---

## Current Behaviour

### Import side (`services/gnucash_importer.py`)

`import_customer`, `import_vendor`, `import_invoice`, `import_bill`, and
`create_account` each process a fixed set of known keys from
`directive.metadata`. Any key not in the known set is silently discarded:

```python
# import_customer — known keys only; jw.country silently dropped
customer.SetName(directive.metadata['name'])
addr.SetAddr1(directive.metadata.get('addr1', ''))
customer.CommitEdit()
# ← jw.country, jw.postal_code etc. are gone here
```

### Export side

`_export_customers`, `_export_vendors`, `_export_invoices`, `_export_bills`
(in `use_cases/export_business_objects.py`) and `_format_account`
(in `use_cases/export_transactions.py`) emit only their fixed field sets.
No code reads the `plaintext_metadata` KVP slot on these objects.

---

## Desired Behaviour

Any key on a directive block that is **not** in the object's known set should
be stored in the GnuCash object's `plaintext_metadata` KVP slot (same JSON
format as transactions) and re-emitted on export after the standard fields.

### Example — customer

```
customer "CUST-001"
  name: "Acme Logistics"
  currency: CAD
  addr1: "2000 McGill College Ave"
  addr3: "Montreal"
  addr4: "QC"
  jw.country: "CA"
  jw.postal_code: "H3A 3H3"
```

After import, `jw.country` and `jw.postal_code` are stored in the customer's
`plaintext_metadata` KVP slot.  On export they are emitted after the standard
fields, producing the same text above.

### Example — account

```
2024-01-01 open Assets:Bank:Checking
	guid: "abc123"
	type: "Bank"
	commodity.namespace: CURRENCY
	commodity.mnemonic: CAD
	erp.cost_centre: "DEPT-42"
```

`erp.cost_centre` survives the import → export round-trip via the account's
`plaintext_metadata` KVP slot.

---

## Implementation Plan

### 1. Known-key sets (add to `infrastructure/gnucash/kvp.py`)

```python
KNOWN_CUSTOMER_METADATA_KEYS = frozenset({
    'name', 'currency', 'addr1', 'addr2', 'addr3', 'addr4', 'email',
})

KNOWN_VENDOR_METADATA_KEYS = frozenset({
    'name', 'currency',
})

KNOWN_INVOICE_METADATA_KEYS = frozenset({
    'customer_id', 'currency', 'date_opened', 'billing_id', 'notes',
    'posted', 'payment',
})

KNOWN_BILL_METADATA_KEYS = frozenset({
    'vendor_id', 'currency', 'date_opened', 'posted', 'payment',
})

KNOWN_ACCOUNT_METADATA_KEYS = frozenset({
    'guid', 'type', 'placeholder', 'code', 'description', 'color',
    'notes', 'tax_related', 'commodity.namespace', 'commodity.mnemonic',
    'commodity_scu',
})
```

### 2. Import (`services/gnucash_importer.py`)

For each object type, after `CommitEdit()`, extract unknown keys and call
`set_custom_metadata(obj, custom_meta)`:

```python
# import_customer
custom_meta = {k: v for k, v in directive.metadata.items()
               if k not in KNOWN_CUSTOMER_METADATA_KEYS and v is not None}
if custom_meta:
    set_custom_metadata(customer, custom_meta)
```

Same pattern for `import_vendor`, `import_invoice`, `import_bill`, and
`create_account`.

**Note on invoices/bills**: only top-level `directive.metadata` keys are
considered.  Keys inside sub-directives (`entry:`, `posted:`, `payment:`)
are sub-directive metadata and are not relevant here.

### 3. Export

#### `use_cases/export_business_objects.py`

After emitting all standard fields in `_export_customers`, `_export_vendors`,
`_export_invoices`, and `_export_bills`, append KVP metadata lines:

```python
from infrastructure.gnucash.kvp import get_custom_metadata

custom_meta = get_custom_metadata(cust)
for k, v in sorted(custom_meta.items()):
    lines.append(f'  {k}: "{v}"')
```

#### `use_cases/export_transactions.py` — `_format_account`

After all standard field lines, append KVP metadata using tab indentation
(matching the account block style):

```python
custom_meta = get_custom_metadata(account)
for k, v in sorted(custom_meta.items()):
    lines.append(f'\t{k}: {encode_value_as_string(v)}')
```

### 4. `get_custom_metadata` already works on business objects

`get_custom_metadata` calls `_get_string_slot` → `obj.GetSlots()` (SWIG path)
or `qof_instance_get_kvp` (ctypes path).  Both `Customer` and `Account` are
`QofInstance` subclasses, so the same code path works — no infrastructure
changes needed.

**Verify** that `Customer.GetSlots()` and `Account.GetSlots()` exist on the
supported platforms (Debian 11/12/13, Ubuntu 20/22/24) and fall back to
ctypes correctly if not.

---

## Test Cases

All tests should use real GnuCash sessions (no mocks), following the pattern
in `tests/unit/services/test_kvp_metadata.py`.

Add a new test file: **`tests/integration/test_kvp_all_objects.py`**

### Customer

| ID | Test | Expected |
|---|---|---|
| C-KVP-01 | Import customer with `jw.country: "CA"` and `jw.postal_code: "H3A 3H3"` | Both keys persisted in GnuCash KVP after save/reload |
| C-KVP-02 | Export customer with `jw.country` and `jw.postal_code` in KVP slot | Both keys appear in plaintext output after standard fields |
| C-KVP-03 | Full round-trip: import → save → export | Custom keys survive without loss |
| C-KVP-04 | Two customers: KVP on CUST-001 must not appear on CUST-002 | Isolation between objects |
| C-KVP-05 | Known keys (`name`, `addr1`, `email`) still work correctly | No regression |
| C-KVP-06 | `jw:country` (colon in key) on import raises `ValueError` | Error on import, not silent drop |

### Vendor

| ID | Test | Expected |
|---|---|---|
| V-KVP-01 | Import vendor with `erp.vendor_code: "V-42"` | Key persisted in KVP |
| V-KVP-02 | Export vendor with KVP key | Key appears in output |
| V-KVP-03 | Full round-trip | Key survives |

### Invoice

| ID | Test | Expected |
|---|---|---|
| I-KVP-01 | Import invoice with `jw.po_ref: "PO-2024-001"` | Key persisted in invoice KVP |
| I-KVP-02 | Export invoice with KVP key | Key appears after standard invoice fields |
| I-KVP-03 | Full round-trip | Key survives |

### Bill

| ID | Test | Expected |
|---|---|---|
| B-KVP-01 | Import bill with `erp.ref: "ERP-001"` | Key persisted in bill KVP |
| B-KVP-02 | Export bill with KVP key | Key appears after standard bill fields |
| B-KVP-03 | Full round-trip | Key survives |

### Account

| ID | Test | Expected |
|---|---|---|
| A-KVP-01 | Import account with `erp.cost_centre: "DEPT-42"` | Key persisted in account KVP |
| A-KVP-02 | Export account with KVP key | Key appears after standard account fields (tab-indented) |
| A-KVP-03 | Full round-trip | Key survives |
| A-KVP-04 | Known account keys (`guid`, `type`, `notes`, etc.) are not stored as KVP | No regression |

---

## Acceptance Criteria

1. All C-KVP, V-KVP, I-KVP, B-KVP, A-KVP tests pass on Debian 13 (primary CI target).
2. No regressions in existing business-objects tests (`tests/integration/test_business_objects.py`).
3. No regressions in existing KVP tests (`tests/unit/services/test_kvp_metadata.py`).
4. Known-key constants defined in `infrastructure/gnucash/kvp.py` (not scattered across importer).

---

## Files to Modify

| File | Change |
|---|---|
| `infrastructure/gnucash/kvp.py` | Add `KNOWN_CUSTOMER_METADATA_KEYS`, `KNOWN_VENDOR_METADATA_KEYS`, `KNOWN_INVOICE_METADATA_KEYS`, `KNOWN_BILL_METADATA_KEYS`, `KNOWN_ACCOUNT_METADATA_KEYS` |
| `services/gnucash_importer.py` | `import_customer`, `import_vendor`, `import_invoice`, `import_bill`, `create_account` — write unknown keys to KVP |
| `use_cases/export_business_objects.py` | `_export_customers`, `_export_vendors`, `_export_invoices`, `_export_bills` — emit KVP metadata |
| `use_cases/export_transactions.py` | `_format_account` — emit KVP metadata |
| `tests/integration/test_kvp_all_objects.py` | New comprehensive test file |

---

## Notes

- The `plaintext_metadata` slot name and JSON serialisation format are
  unchanged — all existing transaction/split KVP data on disk is unaffected.
- `get_custom_metadata` already sanitises stored colon keys (drops them with
  a warning), so any legacy data from before the key-validation rule was added
  will not cause failures on export.
- Invoice and bill sub-directives (`entry:`, `posted:`, `payment:`) do **not**
  need KVP support in this issue; they are structural not free-form metadata.
