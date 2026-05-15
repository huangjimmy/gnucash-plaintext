# Invoice and Bill Payment Reconciliation

Covers the scenarios where bank transactions and invoice/bill payments need
to be linked without creating duplicate bank entries, and how the GUID-based
identity model affects re-imports.

## Background

When an invoice is paid in GnuCash, `ApplyPayment()` always creates a **new**
bank+AR transaction. Similarly, when a vendor bill is paid, it creates a new
bank+AP transaction. If a matching bank transaction was already imported from
a bank feed (QFX, CSV, HTML, etc.), you end up with two bank entries for the
same cash movement — one from the feed, one from the payment.

The `txn_guid` field on a `payment:` block solves this cleanly: instead of
creating a new transaction, the importer **modifies the existing bank
transaction in-place**, retargeting its counter-split to AR (or AP for bills)
and linking it to the invoice/bill lot. All original bank metadata — notes,
description, split memos, FITID — is preserved.

This document describes:

- [Workflow: Import bank feed first, then reconcile invoices](#workflow-import-bank-feed-first-then-reconcile-invoices)
- [Vendor bills work the same way](#vendor-bills-work-the-same-way)
- [GUID format conventions](#guid-format-conventions)
- [Round-trip identity: the exporter writes back what you imported](#round-trip-identity-the-exporter-writes-back-what-you-imported)
- [Idempotency](#idempotency)
- [Error cases](#error-cases)
- [Without txn_guid (invoice-first workflow)](#without-txn_guid-invoice-first-workflow)

---

## Workflow: Import bank feed first, then reconcile invoices

### Step 1 — Import the bank feed

```bash
gnucash-plaintext import ledger.gnucash bank_feed.txt
```

The bank transaction exists with whatever counter-account the import assigned
(Imbalance, or a pre-categorised expense/income account).

### Step 2 — Find the GUID of the bank transaction

```bash
gnucash-plaintext find-transactions ledger.gnucash \
    --account "Assets:Bank" \
    --date 2026-01-15 \
    --amount 500
```

Output:

```
317c8ae6e0084c33951d052b9f1b9f23  2026-01-15    500.00  "E-transfer from Acme"
```

### Step 3 — Add `txn_guid` to the invoice's `payment:` block

```
customer "CUST-001"
	guid: "9f14a498cc894d50931f855a9a31d594"
	name: "Acme Corp"
	currency: CAD

invoice "INV-2026-001"
	customer_id: "CUST-001"
	customer_guid: "9f14a498cc894d50931f855a9a31d594"
	currency: CAD
	date_opened: 2026-01-01
	entry:
		...
	posted:
		date: 2026-01-01
		due: 2026-01-31
		ar_account: "Assets:Accounts Receivable"
		memo: "Invoice INV-2026-001"
		accumulate: true
	payment:
		bank_account: "Assets:Bank"
		txn_guid: "317c8ae6e0084c33951d052b9f1b9f23"
```

Only `bank_account` and `txn_guid` are required in the `payment:` block —
`date`, `amount`, and `memo` are taken from the existing transaction and do
not need to be repeated.

The `customer_guid:` line is optional in hand-written files but emitted on
every export. When both `customer_id:` and `customer_guid:` are present,
they must resolve to the same customer record (see
[Error cases](#error-cases)).

### Step 4 — Import the invoice file

```bash
gnucash-plaintext import --include-business-objects ledger.gnucash invoices.txt
```

The importer:

1. Creates and posts the invoice (AR lot opened) — or finds the existing one
   by id/guid and updates it
2. Finds the existing bank transaction by GUID
3. Retargets its counter-split to AR and links it to the invoice lot
4. The lot sum reaches zero → invoice is marked paid
5. **No new transaction is created** — the original bank entry survives intact

---

## Vendor bills work the same way

Bills use AP instead of AR. The `payment:` block in a `bill` directive is
identical — just provide `bank_account` and `txn_guid`:

```
vendor "VEND-001"
	guid: "f66df24e6e75424ba08c2b0a47ec292c"
	name: "Office Supplies Co."
	currency: CAD

bill "BILL-2026-001"
	vendor_id: "VEND-001"
	vendor_guid: "f66df24e6e75424ba08c2b0a47ec292c"
	currency: CAD
	date_opened: 2026-01-01
	entry:
		...
	posted:
		date: 2026-01-01
		due: 2026-01-31
		ap_account: "Liabilities:Accounts Payable"
		memo: "Bill BILL-2026-001"
		accumulate: true
	payment:
		bank_account: "Assets:Bank"
		txn_guid: "abc123def456abc123def456abc123de"
```

Use `find-transactions` with a negative amount to find outgoing payments:

```bash
gnucash-plaintext find-transactions ledger.gnucash \
    --account "Assets:Bank" \
    --date 2026-01-25 \
    --amount 200
```

---

## GUID format conventions

`txn_guid`, `customer_guid`, `vendor_guid`, and the universal `guid:` field
on every business-object block all carry GnuCash's 32-char hex GUID. A few
syntactic rules are worth noting:

| Form | Accepted on import | Emitted on export |
|---|---|---|
| Quoted hex (`"317c8ae6…"`) | yes (preferred) | yes |
| Unquoted mixed hex (`317c8ae6…f23`, has letters) | yes | no |
| Unquoted all-digit (e.g. `22222222222222222222222222222222`) | **no — error** | n/a |
| UUID-with-hyphens (`317c8ae6-e008-4c33-951d-052b9f1b9f23`) | yes | no |

**Why all-digit unquoted is rejected**: the plaintext parser auto-converts
all-digit field values to Python integers, which silently loses leading
zeros. `00000000000000000000000000000022` and `22` would both decode to the
number `22`, making the original digit count unrecoverable. The importer
raises a clear error asking you to quote the value:

```
guid must be a quoted string (got int 22…22); unquoted all-digit values
are auto-converted to a number and lose their digit count.
Quote the guid: e.g. guid: "00000000000000000000000000000022"
```

The exporter always emits quoted form, so this only matters for hand-written
files.

---

## Round-trip identity: the exporter writes back what you imported

The export is **identity-preserving** for every business object:

- Customer/vendor/taxtable/invoice/bill blocks each carry a `guid:` field
- Invoices reference their customer with both `customer_id:` and `customer_guid:`
- Bills reference their vendor with both `vendor_id:` and `vendor_guid:`
- `payment:` blocks linked via `txn_guid:` retain that link literally —
  the next export still names the same bank transaction

```
invoice "INV-2026-001"
	guid: "b61b7b200f5b41ad97a8f775e8ef6156"
	customer_id: "CUST-001"
	customer_guid: "9f14a498cc894d50931f855a9a31d594"
	currency: CAD
	date_opened: 2026-01-01
	...
```

Re-importing this exported text into the same book is a no-op for identity
(no new entities) and updates mutable fields in place (name, address,
KVP slots, etc.).

---

## Idempotency

Re-importing the same business-objects file is safe and predictable. The
rules per object type:

| Object | Lookup key | Re-import behavior |
|---|---|---|
| Customer | `customer "ID"` directive header (and optional `guid:` field) | **Update** existing record's mutable fields |
| Vendor | `vendor "ID"` (and optional `guid:` field) | **Update** existing record's mutable fields |
| Tax table | `taxtable "Name"` (and optional `guid:` field) | **Update** existing record |
| Invoice | `invoice "INV-001"` (`book.InvoiceLookupByID`) | **Skip** — invoices have lots and posted state; we never silently mutate posted invoices |
| Bill | `bill "BILL-001"` (same as invoice) | **Skip** |

Why invoices/bills skip rather than update: an invoice that is already
posted has an open AR lot tied to a real transaction. Updating its entries
or `customer_id` mid-flight would corrupt the lot. If you need to amend a
posted invoice, do it through the GnuCash GUI or void+reissue.

For a `payment:` block linked via `txn_guid`, re-importing is safe: the
invoice is already paid, the bank transaction's counter-split is already
retargeted to AR. The importer sees the invoice already exists and skips
the whole block; the bank tx is left untouched.

---

## Error cases

The importer halts on any inconsistency rather than silently doing the wrong
thing. Common cases:

### `payment:` / `txn_guid:` errors

| Situation | Error |
|---|---|
| `txn_guid` does not exist in the book | `invoice "X": txn_guid '…' not found in book` |
| `txn_guid` is not a valid GUID/UUID string | `Invalid GUID format: 'hello'` |
| `txn_guid` is unquoted and all-digit | `guid must be a quoted string (got int …)` |
| Invoice has `posted: none` with a `payment:` block | `invoice "X": cannot have payment: blocks on an unposted invoice` |
| Invoice was created but not posted (no posted: block) | `invoice "X": has no posted lot — must be posted before payment` |
| `bank_account` doesn't match any split in the transaction | `invoice "X": Could not find counter-split in tx '…'` |

### Cross-reference errors

| Situation | Error |
|---|---|
| `customer_id` and `customer_guid` resolve to different records | `customer_guid '…' resolves to customer with id "C002", but customer_id says "C001"` |
| `customer_guid` provided but unknown | `customer_guid '…' does not resolve to any record` |
| Invoice has neither `customer_id` nor `customer_guid` | `missing customer reference (need _id or _guid)` |
| Same patterns apply to bill → vendor refs | (substitute "vendor" for "customer") |

### Object identity errors

| Situation | Error |
|---|---|
| Customer block's `guid:` resolves to record with a different id | `customer "C001": directive guid '…' resolves to a customer with id 'C002' — refusing to rename` |
| Customer block's `guid:` is unknown but its `id` is taken | `customer "C001": directive guid '…' does not exist in the book, but a customer with this id already exists` |
| Book contains pre-existing duplicates of the directive's id | `customer "C001": book already has 2 records with this id; resolve in GnuCash GUI before re-importing` |
| Customer block requests a guid already in use by a transaction/account/vendor | `customer "C001": guid … is already used by an existing transaction in this book` |

---

## Without `txn_guid` (invoice-first workflow)

If you import invoices with `payment:` blocks **before** importing the bank
feed, `ApplyPayment()` creates the bank transaction for you. When the bank
feed arrives later, the matching entry will appear as a duplicate. Delete
the bank-feed duplicate using:

```bash
gnucash-plaintext find-transactions ledger.gnucash \
    --account "Assets:Bank" --date 2026-01-15 --amount 500
# → two GUIDs; one has notes "business_generated: true" (the payment tx)
# Delete the bank-feed duplicate:
gnucash-plaintext delete-transactions ledger.gnucash --by-guid <bank-feed-guid>
```

See also: `docs/bank-import-workflow.md` for the full ordering analysis.
