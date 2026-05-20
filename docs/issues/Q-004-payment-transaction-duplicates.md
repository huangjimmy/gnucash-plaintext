---
id: Q-004
title: Invoice payment blocks create duplicate bank transactions
category: quality
severity: high
status: closed
---

## Problem

`ApplyPayment()` always creates a **new** bank+AR transaction. This causes
duplicate bank entries in two distinct scenarios.

---

### Case B — bank transaction imported first, invoice payment imported second

When a bank feed (QFX, CSV, HTML, or manual plaintext) is imported first and
then invoices with `payment:` blocks are imported into the same book,
`ApplyPayment()` creates a second bank transaction alongside the existing one.

**Confirmed by test** (`test_bank_first_then_invoice_no_duplicate`, 2026-05-06):

```
Expected 1 bank transaction after invoice import, got 2.
```

**Practical impact**: any user who imports bank transactions first and then
imports historical paid invoices ends up with doubled bank entries, causing
the bank account balance to be wrong.

---

### Case C — same-day same-amount idempotency failure

The transaction importer deduplicates by `(date, account-set)` signature.
Two invoice payments on the same day from the same bank account produce
identical signatures `{Assets:Bank, Assets:AR}`.

On re-import of the same invoice file (e.g. fixing a description and
re-importing), `ApplyPayment()` creates new payment transactions, but the
**old** payment transactions from the previous import are also re-imported
because:
- GUID check: the old GUIDs are not in the book (new ones were just created)
- Signature check: the new transactions already cover the signature, so the
  old ones are correctly skipped for the **first** match, but in the
  same-day same-amount case GnuCash creates doubles

**Confirmed by test** (`test_same_day_same_amount_idempotent`, 2026-05-06):

```
Expected 2 bank transactions after re-import, got 4.
```

---

## Root cause

`ApplyPayment()` in GnuCash always creates a fresh transaction — there is no
API to retroactively link an existing bank transaction to an invoice lot via
the high-level Python bindings.

The signature-based duplicate check in `import_transactions.py` is fragile:
it can handle the common case but fails when two invoices share the same
date+amount+bank combination, or when payment transactions accumulate across
re-imports.

## Current partial fix (in this branch)

A `txn_guid` field on the `payment:` block plus invoice idempotency:

- **Invoice idempotency**: `import_invoice`/`import_bill` skip if the invoice
  ID already exists in the book. This fixes Case C (re-import no longer
  creates duplicate invoices and therefore no duplicate payments).

- **`txn_guid` field**: when present, the importer deletes the pre-existing
  bank transaction before calling `ApplyPayment()`. This solves the
  no-duplicate constraint but **destroys all metadata** on the original bank
  transaction (KVP/FITID, split memos, reconciliation flags, descriptions).

```
payment:
  txn_guid: "317c8ae6e0084c33951d052b9f1b9f23"   ← current impl: deletes this tx first
```

**This is a known limitation of the current implementation.**

## Correct fix for Case B: retarget the existing transaction (no delete)

Verified in Docker (2026-05-06, latest): it IS possible to modify the
existing bank transaction in-place without deleting it:

1. Find the imbalance split on the existing bank transaction (the split
   that points to `Imbalance` or whatever placeholder account the bank
   import assigned)
2. Retarget that split's account to AR (via ctypes — SWIG `xaccSplitSetAccount`
   has a const-type mismatch)
3. Link the split to the invoice's posted lot via `gc.xaccSplitSetLot()`
4. The lot sum goes to zero → `invoice.IsPaid()` becomes `True`

```
Verified result:
  IsPaid: True
  Bank split memo: "QFX memo to preserve"   ← original data intact
  tx description: "E-transfer from Acme"    ← original description intact
  tx notes: "fitid:20260101ABC source:qfx"  ← KVP/FITID intact
```

**`txn_guid` semantics should change**: instead of "delete this tx and
re-create via ApplyPayment", it should mean "find this tx and retarget its
counter-split to AR, linking it to the invoice lot". The bank transaction
survives intact with all its metadata.

### Implementation approach (not yet coded)

```python
# In import_invoice, PAYMENT block with txn_guid:
existing_tx = _find_transaction_by_guid(book, txn_guid)
if existing_tx:
    # Retarget the non-bank (imbalance/placeholder) split to AR
    lot = invoice.GetPostedLot()
    ar_account = invoice.GetPostedAcc()
    existing_tx.BeginEdit()
    for raw_sp in existing_tx.GetSplitList():
        sp_ptr = int(raw_sp.instance)
        acct_type = _split_acct_type(sp_ptr)   # via ctypes
        if acct_type not in (ACCT_TYPE_BANK, ACCT_TYPE_CASH, ...):
            lib.xaccSplitSetAccount(sp_ptr, int(ar_account.instance))
            gc.xaccSplitSetLot(raw_sp.instance, lot.instance)
            break
    existing_tx.CommitEdit()
    # Do NOT call ApplyPayment() — the lot is already closed
else:
    # No pre-existing tx → normal ApplyPayment()
    invoice.ApplyPayment(None, bank_account, amount, ...)
```

### Identifying the "counter-split" safely

The bank import may assign various placeholder accounts (Imbalance, Opening
Balance, or user-categorised accounts). The safest heuristic: find the split
whose account is NOT `ACCT_TYPE_BANK` / `ACCT_TYPE_CASH` (i.e. not the actual
bank account). This is the split to retarget to AR.

## Files to change

| File | Change |
|---|---|
| `services/gnucash_importer.py` | Replace delete+ApplyPayment with retarget approach for `txn_guid`; use ctypes for `xaccSplitSetAccount` and `xaccSplitSetLot` |
| `cli/find_transactions_cmd.py` | Already implemented; no change needed |
| `cli/main.py` | Already done |
| `tests/integration/test_payment_roundtrip.py` | Update `test_bank_first_then_invoice_with_txn_guid` to assert original bank metadata is preserved |

## Out of scope

- Automatic GUID discovery / fuzzy matching — too fragile. `txn_guid` is explicit.
- Vendor bill case — same logic applies to `import_bill`.
- What if the existing tx has more than 2 splits (e.g. a split transaction) —
  needs further research.

## Related

- **Q-016** — Q-004's `txn_guid:` was only emitted when the user originally used the retarget path; an exported book whose payments came from plain `ApplyPayment` lost the bank-tx-to-invoice link on export and re-imported with duplicate bank transactions into a fresh book. Q-016 closes that roundtrip gap by always emitting `txn_guid:` (plus `txn_split_guid:` to identify the specific AR/AP-side split) on every exported `payment:` block, by emitting the bank tx as a standalone `*` transaction with `guid:` on the transaction and on each split, and by swapping the importer order so standalone transactions are created before invoices/bills are processed. Q-016 also generalises Q-004's "what if the existing tx has more than 2 splits" case: the one-bank-transaction-covering-many-invoices shape now round-trips natively via per-invoice `txn_split_guid:`.

---

**Created**: 2026-05-06
