---
id: Q-016
title: Full GUID emission (txn + per-split) + standalone-tx-first import order — enables clean roundtrip for single-invoice retarget AND multi-invoice shared bank tx
category: quality
severity: high
status: closed
---

## Problem

Two latent gaps surfaced while designing multi-invoice payment support (one bank tx → N invoices):

### Latent gap #1 — single-invoice `txn_guid:` retarget doesn't roundtrip into a fresh book

Workflow that should work but doesn't:

1. User has a QFX-imported bank tx in the book ($100 wire from Acme).
2. User writes invoice plaintext with `payment: txn_guid: "<bank-tx-guid>"` and re-imports — the retarget mechanism (Q-004) attaches the bank tx's counter-split to the invoice's lot. ✓ works today.
3. User exports the whole book to plaintext.
4. User loads the exported plaintext into a fresh book (no pre-existing data).
5. **Re-import "succeeds" silently but produces duplicate bank transactions.**

Probed in `tests/research/test_txn_guid_fresh_roundtrip_probe.py`. What goes wrong:

- The exporter walks `invoice.GetPostedLot()`, finds the payment tx, emits a `payment:` block — **without `txn_guid:`**. The retarget origin is lost in export.
- The exporter also emits the bank tx as a top-level `*` transaction (because it's a real bank tx in the book).
- On fresh-book re-import: the importer processes business objects FIRST (`cli/import_cmd.py:159`), then standalone transactions (`:178`). The invoice's payment block, having no `txn_guid:`, falls into the ApplyPayment path and creates a NEW bank tx. The standalone tx is then imported separately. Net: two bank transactions where one was expected, plus mismatched lot membership.

The existing roundtrip tests (`test_account_type_roundtrip` etc.) didn't catch this because they used `SINGLE_PAID_INVOICE` (ApplyPayment, no `txn_guid`) and only asserted `exit_code == 0` — never counted bank txs across the roundtrip, never tested a `txn_guid:` retarget scenario through full export/import.

### Latent gap #2 — no plaintext representation for "1 bank tx covering N invoices/bills"

The canonical GnuCash UI workflow "Process Payment → select multiple Documents → pay one amount" produces:

```
Transaction 2026-04-01 — "Acme" (payment)
  Assets:Bank                    +$400.00
  Assets:Accounts Receivable     -$100.00   (in INV-A lot, closes it)
  Assets:Accounts Receivable     -$120.00   (in INV-B lot, closes it)
  Assets:Accounts Receivable     -$180.00   (in INV-C lot, closes it)
```

One bank tx with 4 splits, 3 invoice lots closed. Our plaintext today expresses this not at all. The closest workaround is the Q-015 `prepayment:` + `auto_apply_credit:` chain (overpay INV-A by $300, then auto-consume the $300 credit toward INV-B + INV-C) — arithmetically correct but tells a wrong audit story ("INV-A was overpaid, credit applied elsewhere"). Bank reconciliation still sees one $400 deposit but the per-invoice payment provenance is fictional.

Researched in `tests/research/test_multi_invoice_payment_probe.py`. The hand-rolled link works (uses the same primitives Q-015's `_retarget_with_prepayment_split` uses), but the iterative-retarget approach ("each invoice in plaintext order takes the next portion of the counter-split") has fragility risks when invoice amounts collide or when plaintext order doesn't match the original routing order. Per-split GUIDs in the export disambiguate cleanly.

## Why both gaps belong together

The fix shape is the same for both: the exporter must emit enough GUID information that the importer can reconstruct the exact split structure deterministically. With per-tx and per-split GUIDs in plaintext, re-import becomes mechanical lookup-and-attach — no inference, no order-dependence.

Once you commit to that, the multi-invoice case falls out for free: the bank tx has N AR splits, each with its own GUID, each declared by exactly one invoice's payment block. No retarget inference needed.

## Design

### Exporter changes

1. **Standalone `*` transaction blocks emit per-split GUIDs.** The split's
   own GUID uses the same `guid:` field name as the transaction-level
   `guid:` — self-identification, mirroring the customer/invoice/taxtable
   convention. Only foreign references (`txn_guid:`, `txn_split_guid:`,
   `customer_guid:`, `vendor_guid:`) carry a typed prefix naming the kind
   of object they point at.
   ```
   2026-04-01 * "Acme"
     guid: "<tx-guid>"
     Assets:Bank  400.00 CAD
       guid: "<bank-side split guid>"
       memo: "..."
     Assets:Accounts Receivable  -100.00 CAD
       guid: "<ar-side split 1 guid>"
     Assets:Accounts Receivable  -120.00 CAD
       guid: "<ar-side split 2 guid>"
     Assets:Accounts Receivable  -180.00 CAD
       guid: "<ar-side split 3 guid>"
   ```

2. **Invoice/bill `payment:` blocks ALWAYS emit `txn_guid:` of the underlying bank tx.** Today this is only emitted when the user originally used retarget; we generalise to always-emit so the source-of-truth for the bank tx is unambiguous.

3. **Invoice/bill `payment:` blocks emit `txn_split_guid:` identifying the specific AR/AP-side split** that belongs to this invoice/bill. For a single-invoice payment this is unambiguous; for multi-invoice this is the disambiguation.

4. **When a bank tx is referenced by at least one business-object payment block**, the exporter emits it as a top-level `*` transaction (so the standalone-tx import pass can recreate it with the right GUID). The standalone emission is the canonical form; the payment block is the lookup-and-attach pointer.

### Importer changes

1. **Order swap: process standalone transactions BEFORE business objects.** Single-line change in `cli/import_cmd.py`. The business-object path will now find any tx referenced by `txn_guid:` already in the book.

2. **Generalise `_set_object_guid` to accept any `QofInstance`** — splits, transactions, lots — not just business objects. Same ctypes `qof_instance_set_guid` call. Use it when creating splits if a split-level `guid:` is declared.

3. **Payment block resolution with `txn_split_guid:`.** When set, the importer:
   - Looks up the tx by `txn_guid:` (must exist after the standalone-tx pass)
   - Looks up the specific split by `txn_split_guid:` (must be a split of that tx)
   - Calls `xaccSplitSetLot(split, invoice.GetPostedLot())` to attach
   - No new splits created; no retargeting math; no inference

4. **Backward-compatibility — payment block with `txn_guid:` but no `txn_split_guid:`** keeps the existing iterative-retarget mechanic so plaintext written before Q-016 still loads.

### Lots

Not exported as GUIDs. Lots are derived artifacts:

- Invoice/bill posted lots are accessible via `inv.GetPostedLot()` after the invoice is posted.
- Pre-payment lots are recreated as a side effect of splits being attached to a fresh lot created by the importer.
- Lot GUIDs change across runs in GnuCash anyway; trying to preserve them across roundtrip would be brittle and unnecessary for our semantic needs.

## Tests

Integration tests for the full surface, all asserting on the end-state of an export → fresh-book re-import cycle:

- **`test_single_invoice_txn_guid_fresh_roundtrip`** — the gap #1 fix: 1 invoice + 1 retargeted bank tx, export, re-import into fresh book, assert exactly 1 bank tx (same GUID as original), no orphan, invoice closed.
- **`test_multi_invoice_one_payment_fresh_roundtrip`** — 3 invoices ($100/$120/$180) all closed by 1 bank tx ($400). Export, re-import into fresh book, assert: 1 bank tx with 4 splits (preserved GUIDs), 3 closed lots with the right split routing, exit code 0.
- **`test_multi_bill_one_payment_fresh_roundtrip`** — symmetric for vendor bills (AP, opposite signs).
- **`test_mix_retarget_and_apply_payment_fresh_roundtrip`** — a book with some invoices using `txn_guid:` retarget and others using ApplyPayment, roundtrip cleanly.
- **`test_overpayment_with_retarget_fresh_roundtrip`** — combines Q-015's `prepayment:` field with the new `txn_guid:` always-emit; assert the prepay lot survives roundtrip with the residual still attributed to the right source tx.
- **`test_backward_compat_legacy_payment_without_split_guid`** — a plaintext file generated by pre-Q-016 code (no per-split `guid:`, no `txn_split_guid:`) imports cleanly via the iterative-retarget fallback. Ensures we don't break existing user files.
- **`test_two_invoices_same_amount`** — the fragility scenario for iterative retarget: two invoices both for $200 paid by one $400 bank tx. With per-split GUIDs each invoice claims its specific AR split unambiguously regardless of plaintext order.

All tests must pass on every supported distro (debian11/12/13, ubuntu20/22/24/26, fedora41, opensuse, arch).

## Documentation

- `README.md` — document the new payment block fields (`txn_guid:` always present on export; `txn_split_guid:` for shared bank txs), the multi-invoice payment workflow, and the import-order guarantee.

## Related

- **Q-004** — `txn_guid:` retarget mechanism. Q-016 closes a roundtrip gap in Q-004's implementation.
- **Q-014** — orphan-payment warning. Same `find_orphan_payments_in_book` plumbing (lot-walking) is reused; no behavioural change expected.
- **Q-015** — incremental + overpayment + credit-consumption payment workflows. Adds `prepayment:` and `auto_apply_credit:` fields; Q-016 generalises GUID emission across all payment block flavours so the roundtrip story is uniform.

## Surfaced by

User design conversation post-Q-015 merge: "customer pays 3 invoices $100/$120/$180 in 1 bank tx amount $400 — how do we model this?"
