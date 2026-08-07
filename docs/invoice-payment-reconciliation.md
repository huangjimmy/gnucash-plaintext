# Invoice Payment Reconciliation

Covers the scenarios where bank transactions and invoice payments need
to be linked without creating duplicate bank entries, and how the GUID-based
identity model affects re-imports. For the vendor-bill (Accounts Payable) side, see [docs/bill-payment-reconciliation.md](bill-payment-reconciliation.md).

For the canonical end-to-end roundtrip walkthrough — a single source book exercising every plaintext surface (accounts, customers, vendors, tax tables, invoices and bills, every payment shape from cash through retarget, overpayment, credit consumption, and multi-invoice shared bank tx) exported and re-imported into a fresh book with all GUIDs preserved — see [docs/comprehensive-roundtrip-example.md](comprehensive-roundtrip-example.md).

## Background

When an invoice is paid in GnuCash, `ApplyPayment()` always creates a **new**
bank+AR transaction. If a matching bank transaction was already imported from
a bank feed (QFX, CSV, HTML, etc.), you end up with two bank entries for the
same cash movement — one from the feed, one from the payment.

The `txn_guid:` field on a `payment:` block solves this cleanly: instead of
creating a new transaction, the importer **modifies the existing bank
transaction in-place**, retargeting its counter-split to AR
and linking it to the invoice lot. All original bank metadata — notes,
description, split memos, FITID — is preserved.

The companion `txn_split_guid:` field names the *specific* AR/AP-side split that belongs to this invoice/bill. It's optional in hand-written plaintext (the importer falls back to the iterative-retarget mechanism that walks the bank tx's counter-splits in plaintext order) but is **always** emitted on export so a round-tripped book reconstructs bit-for-bit on a fresh re-import — including the shape where one bank transaction covers several invoices or bills, each claiming one specific AR/AP-side split via its own `txn_split_guid:`.

This document describes:

- [Workflow: Import bank feed first, then reconcile invoices](#workflow-import-bank-feed-first-then-reconcile-invoices)
- Vendor bills (Accounts Payable) are covered in [docs/bill-payment-reconciliation.md](bill-payment-reconciliation.md)
- [Managing a customer credit: consume, refund, or forfeit](#managing-a-customer-credit-consume-refund-or-forfeit)
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
		txn_split_guid: "b6b63193116644cbb33cd72b53980011"
```

Only `bank_account` and `txn_guid` are required in the `payment:` block —
`date`, `amount`, and `memo` are taken from the existing transaction and do
not need to be repeated. `txn_split_guid:` is optional in hand-written files (the importer falls back to the iterative-retarget mechanism that walks the bank tx's counter-splits in plaintext order) but is recommended for multi-invoice bank transactions and is always emitted on export.

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
2. Finds the existing bank transaction by `txn_guid:`
3. Locates the specific AR-side split by `txn_split_guid:` (or, if absent, picks the counter-split via the iterative-retarget fallback)
4. Attaches that split to the invoice's posted lot
5. The lot sum reaches zero → invoice is marked paid
6. **No new transaction is created** — the original bank entry survives intact

A single import call can carry both the standalone bank transaction directive and the invoices that reference it — directives within one file are processed in the order `accounts → customers/vendors/taxtables → standalone transactions → invoices/bills`, so each invoice's `txn_guid:` resolves to a bank tx that already exists in the book by the time its `payment:` block runs.

---

## Cash-basis sales (Q-018): same-day post + pay

Cash-basis tax filers recognize revenue when cash is received, not when an invoice is posted. They still issue normal invoices (the billing document and the tax-method classification are separate concerns), but they typically want each sale's posted date to match the cash-receipt date so the books and the tax filing align.

The mechanic is just the bank-feed-first workflow above with three constraints applied:

- `posted.date == payment.date == bank-tx.date` (the cash-receipt date).
- Exactly one `payment:` block carrying `txn_guid:` + `txn_split_guid:` retargeting the existing bank tx.
- An optional `cash_basis: true` line on the invoice header marking tax-method intent.

```
# Step 1: bank tx already in the book (e.g. from a QFX import)
2026-04-15 * "Acme deposit, paid on receipt"
  Assets:Bank  113.00 CAD
  Assets:Accounts Receivable  -113.00 CAD

# Step 2: invoice posts and pays on the same date
invoice "INV-CASH-001"
    customer_id: "C001"
    currency: CAD
    date_opened: 2026-04-15
    cash_basis: true                     # Q-018 blessed KVP key
    entry:
        date: 2026-04-15
        description: "One-day consulting"
        account: "Income:Sales"
        quantity: 1
        price: 100
        taxable: true
        tax_table: "HST"
    posted:
        date: 2026-04-15
        due: 2026-04-15
        ar_account: "Assets:Accounts Receivable"
        memo: "INV-CASH-001 cash sale"
        accumulate: true
    payment:
        date: 2026-04-15
        amount: 113
        bank_account: "Assets:Bank"
        txn_guid: "<the bank tx guid from step 1>"
        txn_split_guid: "<that tx's AR-side split guid>"
        memo: "INV-CASH-001 cash sale"
```

Post-import the invoice is GnuCash-posted and GnuCash-paid; the AR account sees a same-day debit-and-credit netting to zero in a single closed lot; only one bank tx exists (the original, retargeted — Q-016 prevents the duplicate that the ApplyPayment path would create). Income and any tax-account splits are dated on the cash-receipt date, so a P&L grouped by date matches the cash-basis books.

`cash_basis: true` is a **descriptive** flag — a tax-method label for the issuer's own filing / reporting tools. It does NOT constrain the invoice's structure: partial payments, multi-payment, overpayment, and prepayment are all allowed alongside the flag (cash-basis filers commonly receive installments — each payment recognizes its portion of revenue at its own date). The flag survives import → export → fresh-book re-import as a KVP slot on the invoice.

For the **posted** path above, customer-facing rendering is unchanged — the existing PAID badge already conveys everything that matters; the customer never sees "cash basis" anywhere in the output.

### Unposted cash-basis invoices (waiting for cash to arrive)

In a cash-basis workflow the invoice posts only when cash arrives. Before that, the document still needs to be sent to the customer — they're being billed and haven't paid yet. When `cash_basis: true` is set on an unposted invoice, `print-invoice` renders an **UNPAID** badge (instead of DRAFT, which is the default for unposted invoices) so the customer-facing PDF reads as a real bill rather than a work-in-progress draft.

Because the `posted:` block is absent on an unposted invoice (there's no `posted.due` to read from), an optional `due_date: YYYY-MM-DD` field can be added directly to the invoice header to supply the customer-facing due date:

```
invoice "INV-CASH-002"
    customer_id: "C001"
    currency: CAD
    date_opened: 2026-05-01
    cash_basis: true
    due_date: 2026-05-30            # KVP slot, read only when unposted
    entry:
        ...
    posted: none
    payment: none
```

If `due_date` is omitted on an unposted cash-basis invoice, the rendered output simply has no "Due:" row — the customer sees an UNPAID badge but no calendar date. Once the invoice is posted (cash has arrived), `due_date` is ignored — the GnuCash `posted.due` field takes over.

The Q-012 draft path is preserved for invoices that do NOT carry the `cash_basis: true` flag: an ordinary work-in-progress invoice still renders with the DRAFT badge as before.

### Not supported: bank tx with the income/tax breakdown baked in

If your bank tx is already a "complete" cash-sale entry — `Bank +N`, `Income −x`, `Tax −y` with NO `Accounts Receivable` split at all — Q-018 cannot link it to an invoice via the paid-on-receipt workflow. The Q-016 retarget mechanism needs an AR-side split on the bank tx to move into the invoice's posted lot, and a bank tx without an AR split has nothing to retarget.

The fix is in the bank tx, not the invoice: restructure it to `Bank: +N` / `Accounts Receivable: −N` (no Income or Tax splits on the bank tx). Then the standard Q-018 paid-on-receipt workflow above creates the Income and Tax splits via the invoice's posting tx, and the two same-day transactions net to a clean cash-basis P&L.

If restructuring isn't acceptable (e.g. the bank tx must stay byte-identical to a QFX import for bank reconciliation), the only fallback is to leave the invoice unposted with `cash_basis: true` (renders UNPAID) and treat the link between the invoice and the bank tx as documentary only — via memo / billing-id matching by eye, not via GnuCash's posting machinery. See **[docs/issues/Q-018-cash-basis-invoice-kvp.md § Intentionally not supported](issues/Q-018-cash-basis-invoice-kvp.md#intentionally-not-supported-bank-tx-that-already-has-the-incometax-breakdown)** for the full rationale on why this isn't built as a first-class feature.

---

## Managing a customer credit: consume, refund, or forfeit

When a customer pays more than an invoice, the excess opens a **customer credit** — money you hold that isn't yours and may owe back. GnuCash carries it as an open, **negative** (credit) AR lot attached to no invoice (the overpaying `payment:` block records the residual as `prepayment: N`). It is managed in three ways, all non-destructive (none touches the original overpayment transaction), and the **counter account states the intent**:

| Disposition | How you record it | Counter account | Cash movement | What it means |
|---|---|---|---|---|
| **Consume** on the next invoice | `auto_apply_credit: true` on that invoice's header | — (internal lot move) | none | The customer's next invoice(s) draw the credit down |
| **Refund** (the customer asks for it back) | `lot_owner: customer:C001` on an AR split | an **asset** (bank / cash) | **− out of the bank** | Settle the liability in cash — **not an expense** |
| **Forfeit** (the customer never claims it) | `lot_owner: customer:C001` on an AR split | an **income** account | none | Recognise the gain — the *only* case that hits income |

- **Consume it on the next invoice** — `auto_apply_credit: true` on that invoice's header: GnuCash draws the credit into the customer's next invoice(s), across several in posting order until it runs out.
- **Refund** — the customer asks for their money back and you pay it. Record a normal transaction whose AR split carries a `lot_owner:` KVP; the counter is the bank, so money leaves:

```
2026-02-01 * "Refund overpayment to Acme"
	currency.mnemonic: "CAD"
	Assets:Bank -50.00 CAD
	Assets:Accounts Receivable 50.00 CAD
		lot_owner: customer:C001
```

- **Forfeit** — the customer never claims the credit and you recognise it as income (a gain). Same shape, counter = an income account:

```
2026-02-15 * "Forfeit Acme overpayment to income"
	currency.mnemonic: "CAD"
	Income -50.00 CAD
	Assets:Accounts Receivable 50.00 CAD
		lot_owner: customer:C001
```

The `lot_owner: customer:C001` KVP joins the AR split to the customer's oldest open credit lot and reduces it — an exact amount closes the lot, a smaller amount leaves the residual credit open (a partial refund). A `customer:` KVP must sit on an AR account (a `vendor:` KVP on an AP account); the importer rejects the mismatch.

**What the refund moves, and why it is not an expense.** Observed from the book (invoice $100 paid $150, then we refund $50): the $50 goes **out of the bank and clears the AR credit** — `Assets:Bank` falls by $50 and `Assets:Accounts Receivable` goes `−50 → 0`; the credit lot closes. Nothing else moves — no expense and no reduction of income. This matches the intuition that a customer overpayment is, in effect, a **liability** (money we hold that isn't ours and may owe back): GnuCash carries it as a credit (negative balance) on Accounts Receivable rather than in a separate liability account, and the refund settles it in cash. Only the **forfeit** above touches income — that's the different case where the customer never claims it and it becomes a gain.

Detect open credits with `find-prepayments --customer C001` or the `open_prepayment:` blocks on AR accounts. The whole state round-trips through export via three directives — `prepayment:` (on the overpaying payment), `open_prepayment:` (the per-account credit summary), and `lot_owner:` (the disposal split) — so a credit survives export → fresh-book re-import without manual bookkeeping. This is the exact mirror of the vendor side, sign-flipped: see [docs/bill-payment-reconciliation.md § Managing a vendor credit](bill-payment-reconciliation.md#managing-a-vendor-credit-consume-refund-or-write-off) (there the refund arrives *in* the bank and the write-off goes to an expense).

---

## GUID format conventions

`guid`, `txn_guid`, `txn_split_guid`, `customer_guid`, and `vendor_guid` all
carry GnuCash's 32-char hex GUID. `guid:` is the universal self-identification
field used on every object (transaction, split, customer, vendor, taxtable,
invoice, bill); the typed-reference forms (`txn_guid`, `txn_split_guid`,
`customer_guid`, `vendor_guid`) name a foreign object from inside another
block. A few syntactic rules are worth noting:

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

## Informational fields (Q-017): rendered plaintext vs canonical export

Two commands emit the same plaintext syntax with different field sets:

- **`export --include-business-objects`** — canonical, source-of-truth fields only. What round-trips into a fresh book deterministically.
- **`print-invoice --format plaintext`** — same syntax, **plus** informational totals derived from those source-of-truth fields. What you share with an auditor / customer / yourself for grep-friendly reading.

Informational fields:

| Field | Scope | Meaning |
|---|---|---|
| `entry_amount` | invoice/bill entry | `quantity × price`, net of `tax_included` |
| `entry_tax` | invoice/bill entry | total tax dollars contributed by this line |
| `breakdown:` (repeatable sub-block) | invoice/bill entry | one block per tax-table entry: `account`, `rate`, `amount`. Audit-friendly: shows which government got which dollar |
| `invoice_subtotal` / `bill_subtotal` | invoice/bill | sum of all `entry_amount` |
| `invoice_tax_total` / `bill_tax_total` | invoice/bill | sum of all `entry_tax` |
| `invoice_total` / `bill_total` | invoice/bill | `subtotal + tax_total` |

On re-import the importer recomputes every informational field from the source-of-truth fields (`quantity × price × tax_table`) and errors loudly on any mismatch — so a tampered rendered file fails the import rather than silently storing the wrong totals. Same shape as Q-015's `prepayment:` cross-check.

Draft (unposted) invoices/bills emit only `*_subtotal` since per-entry tax requires posting.

See `docs/issues/Q-017-print-invoice-plaintext-format-and-multi-invoice.md` for the full spec.

---

## Round-trip identity: the exporter writes back what you imported

The export is **identity-preserving** for every business object and every transaction split:

- Customer/vendor/taxtable/invoice/bill blocks each carry a `guid:` field
- Invoices reference their customer with both `customer_id:` and `customer_guid:`
- Bills reference their vendor with both `vendor_id:` and `vendor_guid:`
- Standalone transaction blocks (`* "..."`) carry `guid:` and every split inside carries its own `guid:`
- `payment:` blocks always carry `txn_guid:` (the bank transaction) and `txn_split_guid:` (the AR/AP-side split that belongs to this invoice/bill) — re-imports on a fresh book reconstruct the same bank-tx-to-invoice routing without inference

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
| The transaction has no split outside `bank_account` | `invoice "X": tx '…' has no split outside 'Assets:Bank' to settle it with` |
| Every split outside `bank_account` already settles a document | `invoice "X": every split of tx '…' outside 'Assets:Bank' already settles a document — retargeting one would leave that document unpaid with no figure disagreeing` |
| Several splits could settle it and the block names only `txn_guid:` | `invoice "X": tx '…' carries 2 splits that are not 'Assets:Bank' and could each settle this invoice` |
| `bank_account` names an account no split is on | as the row above: with no split matching the name, every split counts as "not the bank", so a two-split deposit reads as ambiguous. Check `bank_account:` for a typo before adding `txn_split_guid:` |
| `from_credit:` names a split an unpost left loose that a bank had paid — any document's, not only this one's | `invoice "X": the split txn_split_guid names is a settlement a bank paid, left loose when the document it settled was unposted — no credit was spent on it` |
| A split states `orphaned_by_unpost:` | `the split on 'Assets:…': \`orphaned_by_unpost:\` is not a key a file may state on a transaction or a split` |
| A transaction states `orphaned_by_unpost:` (on either arm — a new transaction, or one named by `guid:` under `--strategy update`) | `the transaction dated 2026-04-03: \`orphaned_by_unpost:\` is not a key a file may state on a transaction or a split` |
| A bare `txn_guid:` block's `amount:` covers neither what the split carries nor what the document owes | `invoice "X": this block says 100.00 arrived, but the split it would move on tx '…' carries 60.00 and the invoice is owed 100.00 — so taking it would leave the invoice part-paid out of money this file does not describe` |
| A bare `txn_guid:` block's `amount:` is not a number | `invoice "X": payment amount must be a number, got 'one hundred'` |
| `txn_split_guid:` names a split that already settles another document | `invoice "X": the split txn_split_guid '…' names is in another document's lot — it settles that one, and moving it here would leave that document unpaid` |

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
