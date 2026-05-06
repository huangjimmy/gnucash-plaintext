# Invoice and Bill Payment Reconciliation

Covers two scenarios where bank transactions and invoice/bill payments need
to be linked without creating duplicate bank entries.

## Background

When an invoice is paid in GnuCash, `ApplyPayment()` always creates a **new**
bank+AR transaction. Similarly, when a vendor bill is paid, it creates a new
bank+AP transaction. If a matching bank transaction was already imported from a
bank feed (QFX, CSV, HTML, etc.), you end up with two bank entries for the
same cash movement — one from the feed, one from the payment.

The `txn_guid` field on a `payment:` block solves this cleanly: instead of
creating a new transaction, the importer **modifies the existing bank
transaction in-place**, retargeting its counter-split to AR (or AP for bills)
and linking it to the invoice/bill lot. All original bank metadata — notes,
description, split memos, FITID — is preserved.

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
invoice "INV-2026-001"
  customer_id: "CUST-001"
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
    txn_guid: 317c8ae6e0084c33951d052b9f1b9f23
```

Only `bank_account` and `txn_guid` are required — `date`, `amount`, and `memo`
are taken from the existing transaction and do not need to be repeated.

### Step 4 — Import the invoice file

```bash
gnucash-plaintext import --include-business-objects ledger.gnucash invoices.txt
```

The importer:
1. Creates and posts the invoice (AR lot opened)
2. Finds the existing bank transaction by GUID
3. Retargets its counter-split to AR and links it to the invoice lot
4. The lot sum reaches zero → invoice is marked paid
5. **No new transaction is created** — the original bank entry survives intact

---

## Vendor bills work the same way

Bills use AP instead of AR. The `payment:` block in a `bill` directive is
identical — just provide `bank_account` and `txn_guid`:

```
bill "BILL-2026-001"
  vendor_id: "VEND-001"
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
    txn_guid: abc123def456abc123def456abc123de
```

Use `find-transactions` with a negative amount to find outgoing payments:

```bash
gnucash-plaintext find-transactions ledger.gnucash \
    --account "Assets:Bank" \
    --date 2026-01-25 \
    --amount 200
```

---

## Error cases

| Situation | Error |
|---|---|
| GUID does not exist in the book | `invoice "X": txn_guid '...' not found in book` |
| Invoice has `posted: none` with a `payment:` block | `invoice "X": cannot have payment: blocks on an unposted invoice` |
| Invoice was created but not posted (no posted: block) | `invoice "X": has no posted lot — must be posted before payment` |
| `bank_account` doesn't match any split in the transaction | `invoice "X": Could not find counter-split in tx '...'` |

---

## Idempotency

Re-importing the same invoice/bill file after a successful `txn_guid` link is
safe — the invoice/bill already exists in the book, so it is skipped without
error and the bank transaction is left untouched.

---

## Without `txn_guid` (invoice-first workflow)

If you import invoices with `payment:` blocks **before** importing the bank
feed, `ApplyPayment()` creates the bank transaction for you. When the bank feed
arrives later, the matching entry will appear as a duplicate. Delete the
bank-feed duplicate using:

```bash
gnucash-plaintext find-transactions ledger.gnucash \
    --account "Assets:Bank" --date 2026-01-15 --amount 500
# → two GUIDs; one has notes "business_generated: true" (the payment tx)
# Delete the bank-feed duplicate:
gnucash-plaintext delete-transaction-by-guid ledger.gnucash <bank-feed-guid>
```

See also: `docs/bank-import-workflow.md` for the full ordering analysis.
