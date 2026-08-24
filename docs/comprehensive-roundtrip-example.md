# Comprehensive roundtrip example

This walkthrough goes through a complete `export` → fresh-book `import --new` cycle for a book that exercises every plaintext surface the project supports: account hierarchy with multiple commodities, customers and vendors, tax tables, invoices and bills in several payment shapes (cash-on-import, partial payment, overpayment with prepayment credit, credit consumption via `auto_apply_credit`, and the multi-invoice-one-bank-tx shape), plus regular bank transactions. After Q-016 the reconstructed book is structurally identical to the source down to per-split GUIDs.

If you only need the simple "post an invoice, record a payment" workflow, the [README](../README.md) is enough. This doc is the reference for the tricky cases — anything that mixes multiple invoices, customer credits, or pre-existing bank transactions.

## Scope of this example

A single source book is built in pieces, exported to one plaintext file, and re-imported into a fresh empty GnuCash file. After the re-import the two books should be **semantically identical**: same accounts, same balances, same lot structure, same GUIDs on every customer, vendor, invoice, bill, transaction, and split.

The source book contains, in roughly the order the importer processes them:

1. A multi-account chart of accounts in CAD.
2. One customer (`C-EX-001` Acme), one vendor (`V-EX-001` Supplier Co), one tax table (`HST-13`).
3. Four pre-existing bank transactions (the kind you'd typically get from a QFX import) and one cash-payment bank tx (created by `ApplyPayment` during the cash-payment invoice import).
4. Five customer invoices for Acme exercising every payment shape:
   - `INV-EX-A-100` ($100) — overpaid by $30 (Q-015 `prepayment:`).
   - `INV-EX-CASH-50` ($50) — paid in cash via `ApplyPayment` on import, no pre-existing bank tx.
   - `INV-EX-CONSUME-30` ($30) — consumes Acme's $30 prepayment credit via Q-015 `auto_apply_credit: true`.
   - `INV-EX-B-120` ($120) — partial $50 (linked bank tx) then $70 (Q-016 multi-invoice).
   - `INV-EX-C-180` ($180) — full $180 via the same Q-016 multi-invoice $250 wire as `INV-EX-B-120`'s remainder.
5. One vendor bill `BILL-EX-001` ($75 + 13% HST = $84.75) — paid via a Q-004 `txn_guid:` link.

That covers cash payment, a partial payment from a linked bank tx, overpayment with credit residual, credit consumption, multi-invoice shared bank tx, taxed bill, and bill payment from a linked bank tx — every payment shape Q-004/Q-014/Q-015/Q-016 added.

## Step-by-step setup

The full plaintext for the source book is split into smaller files only for the convenience of the walkthrough — in practice you'd write whatever subset matches your workflow.

### Accounts

```
2026-01-01 open Assets
  type: Asset
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
  type: Accounts Receivable
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
  type: Bank
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Liabilities
  type: Liability
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Liabilities:Accounts Payable
  type: Accounts Payable
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Liabilities:HST Payable
  type: Liability
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Income
  type: Income
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
  type: Income
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Expenses
  type: Expense
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
2026-01-01 open Expenses:Supplies
  type: Expense
  commodity.namespace: "CURRENCY"
  commodity.mnemonic: "CAD"
```

### Tax table, customer, vendor

```
taxtable "HST-13"
  type: percentage
  rate: 13
  account: "Liabilities:HST Payable"

customer "C-EX-001"
  name: "Acme"
  currency: CAD

vendor "V-EX-001"
  name: "Supplier Co"
  currency: CAD
```

### Pre-existing bank transactions

These would normally come from a QFX import. They sit on the bank account independent of any invoice/bill until the user wires them up via a `txn_guid:` link.

```
2026-04-10 * "Acme — INV-A overpay"
  Assets:Bank  130.00 CAD
    memo: "Overpayment for INV-EX-A-100"
  Assets:Accounts Receivable  -130.00 CAD

2026-05-04 * "Acme — INV-B partial"
  Assets:Bank  50.00 CAD
    memo: "Partial payment for INV-EX-B-120"
  Assets:Accounts Receivable  -50.00 CAD

2026-05-15 * "Acme — wire covering B-remainder + C"
  Assets:Bank  250.00 CAD
    memo: "Multi-invoice wire"
  Assets:Accounts Receivable  -70.00 CAD
    memo: "Remainder of INV-EX-B-120"
  Assets:Accounts Receivable  -180.00 CAD
    memo: "Full payment of INV-EX-C-180"

2026-06-01 * "Supplier Co — bill payment"
  Assets:Bank  -84.75 CAD
    memo: "Payment for BILL-EX-001 (with HST)"
  Liabilities:Accounts Payable  84.75 CAD
```

### Invoices

```
invoice "INV-EX-A-100"
  customer_id: "C-EX-001"
  currency: CAD
  date_opened: 2026-04-01
  entry:
    date: 2026-04-01
    description: "Service A"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 100
    taxable: false
    tax_included: false
  posted:
    date: 2026-04-02
    due: 2026-05-02
    ar_account: "Assets:Accounts Receivable"
    memo: "INV-EX-A-100"
    accumulate: true
  payment:
    date: 2026-04-10
    amount: 130
    bank_account: "Assets:Bank"
    txn_guid: "<guid of the 2026-04-10 bank tx>"
    txn_split_guid: "<guid of the -130 AR split on that tx>"
    prepayment: 30
    memo: "Overpayment for INV-EX-A-100"

invoice "INV-EX-B-120"
  customer_id: "C-EX-001"
  currency: CAD
  date_opened: 2026-05-01
  entry:
    date: 2026-05-01
    description: "Service B"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 120
    taxable: false
    tax_included: false
  posted:
    date: 2026-05-02
    due: 2026-06-01
    ar_account: "Assets:Accounts Receivable"
    memo: "INV-EX-B-120"
    accumulate: true
  payment:
    date: 2026-05-04
    amount: 50
    bank_account: "Assets:Bank"
    txn_guid: "<guid of the 2026-05-04 bank tx>"
    txn_split_guid: "<guid of the -50 AR split>"
    memo: "Partial payment for INV-EX-B-120"
  payment:
    date: 2026-05-15
    amount: 70
    bank_account: "Assets:Bank"
    txn_guid: "<guid of the 2026-05-15 $250 wire>"
    txn_split_guid: "<guid of the -70 AR split on that wire>"
    memo: "Remainder of INV-EX-B-120"

invoice "INV-EX-C-180"
  customer_id: "C-EX-001"
  currency: CAD
  date_opened: 2026-05-01
  entry:
    date: 2026-05-01
    description: "Service C"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 180
    taxable: false
    tax_included: false
  posted:
    date: 2026-05-02
    due: 2026-06-01
    ar_account: "Assets:Accounts Receivable"
    memo: "INV-EX-C-180"
    accumulate: true
  payment:
    date: 2026-05-15
    amount: 180
    bank_account: "Assets:Bank"
    txn_guid: "<guid of the 2026-05-15 $250 wire>"
    txn_split_guid: "<guid of the -180 AR split on that wire>"
    memo: "Full payment of INV-EX-C-180"

invoice "INV-EX-CASH-50"
  customer_id: "C-EX-001"
  currency: CAD
  date_opened: 2026-04-20
  entry:
    date: 2026-04-20
    description: "Cash service"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 50
    taxable: false
    tax_included: false
  posted:
    date: 2026-04-20
    due: 2026-05-20
    ar_account: "Assets:Accounts Receivable"
    memo: "INV-EX-CASH-50"
    accumulate: true
  payment:
    date: 2026-04-25
    amount: 50
    bank_account: "Assets:Bank"
    memo: "Cash"

invoice "INV-EX-CONSUME-30"
  customer_id: "C-EX-001"
  currency: CAD
  date_opened: 2026-05-10
  auto_apply_credit: true
  entry:
    date: 2026-05-10
    description: "Small service consuming credit"
    action: "Hours"
    account: "Income:Sales"
    quantity: 1
    price: 30
    taxable: false
    tax_included: false
  posted:
    date: 2026-05-10
    due: 2026-06-10
    ar_account: "Assets:Accounts Receivable"
    memo: "INV-EX-CONSUME-30"
    accumulate: true
```

`INV-EX-CONSUME-30` has no `payment:` block — `auto_apply_credit: true` consumes the $30 of pre-payment credit `INV-EX-A-100` left on Acme's account, fully closing the invoice.

### Bill

```
bill "BILL-EX-001"
  vendor_id: "V-EX-001"
  currency: CAD
  date_opened: 2026-05-15
  entry:
    date: 2026-05-15
    description: "Office supplies"
    action: "Material"
    account: "Expenses:Supplies"
    quantity: 1
    price: 75
    taxable: true
    tax_included: false
    tax_table: "HST-13"
  posted:
    date: 2026-05-16
    due: 2026-06-15
    ap_account: "Liabilities:Accounts Payable"
    memo: "BILL-EX-001"
    accumulate: true
  payment:
    date: 2026-06-01
    amount: 84.75
    bank_account: "Assets:Bank"
    txn_guid: "<guid of the 2026-06-01 -84.75 bank tx>"
    txn_split_guid: "<guid of the +84.75 AP split>"
    memo: "Payment for BILL-EX-001 (with HST)"
```

## End state of the source book

After all six payment events:

| Invoice/Bill | Lot state | Bank tx |
|---|---|---|
| `INV-EX-A-100` | closed at $0 | 2026-04-10 $130 wire (5 splits after Q-015 prepay split: bank +$130, AR -$100 in invoice lot, AR -$30 in prepay lot) |
| `INV-EX-CASH-50` | closed at $0 | A new $50 bank tx created by `ApplyPayment` (no `txn_guid:`) |
| `INV-EX-CONSUME-30` | closed at $0 | Same 2026-04-10 wire — the $30 prepay split is now half in the prepay lot, half consumed into INV-EX-CONSUME-30's lot |
| `INV-EX-B-120` | closed at $0 | Two payment splits — $50 from 2026-05-04 + $70 from 2026-05-15 wire |
| `INV-EX-C-180` | closed at $0 | $180 from 2026-05-15 wire |
| `BILL-EX-001` | closed at $0 | 2026-06-01 $84.75 wire (linked via `txn_guid:` + `txn_split_guid:`) |

Open AR lots: none after `INV-EX-CONSUME-30` consumes the $30 credit. Open AP lots: none. All five bank transactions are still in place (the QFX-imported $130 + $50 + $250 + $84.75 wires, plus the cash-payment $50 that `ApplyPayment` created for `INV-EX-CASH-50`).

## Export

```
gnucash-plaintext export source.gnucash exported.txt --include-business-objects
```

`exported.txt` contains, in order:

1. Commodity declarations (here: CAD).
2. Account declarations with `guid:`.
3. Tax table `HST-13` with `guid:` and rate.
4. Customer and vendor with `guid:`.
5. Invoice and bill business-object blocks. Every `payment:` block carries `txn_guid:` and `txn_split_guid:`. Where a payment overpays, `prepayment:` records the residual. Where a separate invoice consumes that residual, the consuming invoice has `auto_apply_credit: true` and `payment: none`.
6. All standalone `*` transactions — including the QFX-imported bank txs, the $50 bank tx that `ApplyPayment` created for the cash payment, and the invoice posting txs that are emitted as a side effect of the business-object pass. Every transaction carries `guid:` and every split carries its own `guid:`.

The full file is long enough not to inline here, but a representative slice — the multi-invoice wire and its three claimants — looks like this:

```
invoice "INV-EX-B-120"
  guid: "422d0aff90d341bf977f60904f3fd61c"
  ...
  payment:
    date: 2026-05-04
    amount: 50
    bank_account: "Assets:Bank"
    txn_guid: "8a3b9c0d1e2f4a5b6c7d8e9f0a1b2c3d"
    txn_split_guid: "9c1f2d3e4b5a6c7d8e9f0a1b2c3d4e5f"
    memo: "Partial payment for INV-EX-B-120"
  payment:
    date: 2026-05-15
    amount: 70
    bank_account: "Assets:Bank"
    txn_guid: "5f6e7d8c9b0a1f2e3d4c5b6a7c8d9e0f"
    txn_split_guid: "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
    memo: "Remainder of INV-EX-B-120"

invoice "INV-EX-C-180"
  ...
  payment:
    txn_guid: "5f6e7d8c9b0a1f2e3d4c5b6a7c8d9e0f"   ← same as INV-EX-B's second payment
    txn_split_guid: "7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f"  ← different split

2026-05-15 * "Acme — wire covering B-remainder + C"
  guid: "5f6e7d8c9b0a1f2e3d4c5b6a7c8d9e0f"
  txn_type: P
  owner: customer:C-EX-001
  Assets:Bank 250.00 CAD
    guid: "f3c561adfe1c4296bd6ed114773b7518"
    memo:"Multi-invoice wire"
  Assets:Accounts Receivable -70.00 CAD
    guid: "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
    memo:"Remainder of INV-EX-B-120"
  Assets:Accounts Receivable -180.00 CAD
    guid: "7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f"
    memo:"Full payment of INV-EX-C-180"
```

Two invoices (`INV-EX-B-120` and `INV-EX-C-180`) carry payment blocks referencing the same `txn_guid:` — that's the multi-invoice signature. Their `txn_split_guid:` fields point at different splits of that one shared bank transaction.

## Fresh-book re-import

```
gnucash-plaintext import --new reconstructed.gnucash exported.txt --include-business-objects
```

The importer runs in this order (Q-016):

1. **Account hierarchy** — every `open` directive creates an account, restoring the declared `guid:` so business-object cross-references resolve.
2. **Customers, vendors, tax tables** — created with their declared GUIDs.
3. **Standalone `*` transactions** — every bank transaction is recreated with its declared `guid:` and each split with its declared `guid:`. AR/AP-side splits are LOOSE at this point (no lot membership) — that's normal because invoice posting hasn't happened yet.
4. **Invoices and bills** — for each:
   - Entries and posting block create the invoice/bill and its posted lot.
   - Each `payment:` block looks up the bank tx by `txn_guid:` (found in step 3) and the specific split by `txn_split_guid:` (also found), then attaches that split to the invoice/bill's posted lot. The lot closes when its split sum hits zero.
   - When `auto_apply_credit: true` is set, after posting and any explicit payment blocks, `gncInvoiceAutoApplyPayments` runs to consume open prepay credit lots toward this invoice's remaining balance.
   - When `prepayment:` is set, the importer validates the resulting prepay lot's balance matches.

Net effect: the reconstructed book has the same five bank transactions (same GUIDs, same split GUIDs, same memos), the same five invoices, the same bill, and the same lot structure as the source.

## What's special about each shape

**Cash payment** (`INV-EX-CASH-50`) — no `txn_guid:` in the payment block, so the importer uses the `ApplyPayment` path which creates a new bank tx on the fly. Round-trip preserves the GUID of that auto-created tx because the exporter emits it as a standalone `*` block too, and the re-import sees `txn_guid:` and uses the standalone tx instead of creating another.

**Linked bank transaction** (`INV-EX-B-120`'s first payment, `BILL-EX-001`) — `txn_guid:` points at a bank tx the user pre-created (typically from a QFX import). The importer attaches the specific split via `txn_split_guid:` rather than creating a duplicate bank tx.

**Overpayment** (`INV-EX-A-100`) — `prepayment:` field on the payment block records the residual. The importer creates the invoice lot plus a new prepay lot for the residual, leaving an open credit on AR.

**Credit consumption** (`INV-EX-CONSUME-30`) — `auto_apply_credit: true` on the invoice, no explicit `payment:`. The importer posts the invoice, then calls `gncInvoiceAutoApplyPayments` which finds the open prepay lot from `INV-EX-A-100`'s overpayment and consumes it.

**Multi-invoice payment** (`INV-EX-B-120`'s second payment + `INV-EX-C-180`) — both invoices reference the same `txn_guid:`. The shared bank tx's three AR splits each go in the right invoice's lot via per-invoice `txn_split_guid:`.

**Bill payment from a linked bank transaction** (`BILL-EX-001`) — symmetric to the invoice side but on AP with opposite signs.

## What would go wrong without Q-016

If you exported a book like this with a pre-Q-016 build and re-imported into a fresh book:

- `INV-EX-CASH-50` would survive because the cash-payment path didn't change.
- `INV-EX-A-100` would lose the link to its $130 bank tx (the exporter dropped `txn_guid:` when the user originally linked one). On re-import, `ApplyPayment` would create a duplicate $130 bank tx, and the original would either be deduped or become an orphan depending on date/amount heuristics. The `prepayment: 30` residual would still appear because it's a Q-015 field, but the lot structure would be inconsistent.
- `INV-EX-CONSUME-30` would still consume credit (`auto_apply_credit:` survives), but it would consume from the duplicate prepay lot.
- `INV-EX-B-120`'s two payments would each get their own new bank tx; the $50 and $250 wires would be either duplicated or skipped via dedup.
- `INV-EX-C-180` likewise.
- `BILL-EX-001`'s payment would either work (if the 2026-06-01 -$84.75 bank tx survives dedup) or, more likely, double-pay the bill.

Net: bank transaction duplication, mismatched lot membership, and a book that no longer reflects the real-world money movement. Q-016 closes all of this by always emitting the GUIDs needed for deterministic re-import.

## Backward compatibility

Files written by pre-Q-016 versions still import — the `payment:` block falls back to the Q-015 iterative linking mechanism when `txn_split_guid:` is absent, and the importer order swap is benign for any plaintext that doesn't use cross-block GUID references. New plaintext should always include the full GUID set on export; hand-authored plaintext can omit `txn_split_guid:` for single-invoice cases and let the iterative linking handle it, though for multi-invoice you should include it.
