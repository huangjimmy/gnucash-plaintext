# Q-018 — `cash_basis: true` invoice marker for cash-basis tax filing

## Pain point

Cash-basis tax filers (Canadian small businesses below the CRA cash-basis threshold, US Schedule C filers, single-entity service consultancies) recognize revenue when cash is received, not when an invoice is posted. They still issue normal invoices — billing the customer is a separate concern from tax classification — but at tax time they need to know which invoices' revenue should be reported by payment date rather than invoice date.

Today nothing in the plaintext format identifies this intent. A cash-basis filer running `gnucash-plaintext export` gets a uniform stream of invoices with no way to grep "which of these are cash-basis for tax purposes." Their reporting tools (or eyes) have to reconstruct the classification from external knowledge.

## Decision: descriptive KVP flag, not structural

The plaintext format already records arbitrary custom metadata on invoices via the KVP path (any key not in `KNOWN_INVOICE_METADATA_KEYS`). Users can write any field name they like — `cash_basis: true`, `tax_treatment: "cash"`, etc. — and it round-trips through export/import.

Q-018 blesses one canonical name: **`cash_basis: true`**. The flag is purely descriptive — it labels the issuer's tax-method intent for this invoice. It does NOT constrain the invoice's structural shape:

- Partial payments are allowed (cash-basis filers commonly receive installments — each payment recognizes its portion of revenue at its own date).
- Multi-payment, overpayment, prepayment are all allowed for the same reason.
- The flag survives unposting, re-posting, and re-import unchanged.

The structural-validator alternative (require `posted.date == payment.date == bank-tx.date` and full payment when the flag is set) was rejected: that interpretation only fits the "paid-on-receipt" subset of cash-basis workflows and rejects everything else, which doesn't match how cash-basis filers actually operate their books.

## What the flag does NOT change

Customer-facing rendering — `print-invoice --format {pdf,html}` — stays identical regardless of the flag. Cash basis vs accrual basis is a tax-method classification internal to the issuer; the customer paying the bill has no business with it. Same goes for the `--format plaintext` output the issuer might share with bookkeepers — the existing Q-017 informational fields cover all the audit numbers; no new visible markers are added.

The GnuCash UI also continues to show the invoice in its normal posted/paid state — the flag lives in the KVP slot, not in GnuCash's invoice schema.

## What this issue actually adds

1. **A blessed name in the format spec.** Documenting `cash_basis: true` as the canonical KVP marker for cash-basis intent, so all tools / scripts / future features that filter by tax-method use the same spelling. Without blessing, three different users would pick three different names (`cash_basis`, `tax_method`, `revenue_basis`) and downstream tooling would have to guess.

2. **The canonical workflow recipe.** Cash-basis filers commonly want "post and pay on the same day from an already-imported bank tx" (the receipt-time pattern). This works today via Q-016 retarget — set `posted.date == payment.date == bank-tx.date` and use `txn_guid:` + `txn_split_guid:` in the payment block to link the existing bank tx. We document the recipe so users don't have to reinvent it.

3. **An integration test pinning the round-trip.** `tests/integration/test_q018_cash_basis_marker.py` covers: same-day post-and-pay produces invoice posted+paid with AR balanced same-day and a single bank tx (the original retargeted); the `cash_basis: true` flag round-trips through import → export → fresh-book re-import as a KVP slot on the invoice; partial payment with the flag still applies (no validator); customer-facing PDF rendering is unchanged whether the flag is set or not.

No code changes to renderer, importer, exporter, or CLI. This is a format-convention blessing plus documentation plus regression protection. Roughly 200 lines of test + 50 lines of doc.

## Research already done

`tests/research/test_q018_cash_basis_probe.py` (run in worktree/main, then removed once the design crystallised) verified the workflow against the current main branch (Q-016 + Q-017 merged):

```json
{
  "invoice": {
    "found": true,
    "is_posted": true,
    "is_paid": true,
    "posted_lot_balance": 0.0,
    "posted_lot_closed": true
  },
  "bank_tx_count": 1,
  "ar_splits": [
    {"amount": -113.0, "in_lot": true, "tx_guid": "<bank tx>"},
    {"amount":  113.0, "in_lot": true, "tx_guid": "<posting tx>"}
  ]
}
```

Two transactions in the book (the original bank tx + the GnuCash-generated posting tx), both same-day, both in the same closed AR lot. Income recognized on the sale date. Q-016 retarget prevented duplicate bank tx. Back-dating works (probe ran with date 2026-04-15, 35 days before "today"). Custom KVP fields `cash_basis: true` and `tax_treatment: "cash_basis"` survived the round-trip via the existing KVP path.

So the format and importer already support everything; this issue is the convention.

## Canonical workflow

```
# Step 1 — bank tx already exists in the book (QFX import or hand-written)
2026-04-15 * "Acme deposit, paid on receipt"
  Assets:Bank  113.00 CAD
  Assets:Accounts Receivable  -113.00 CAD

# Step 2 — invoice with same-date posted/payment + Q-016 retarget
invoice "INV-CASH-001"
  customer_id: "C001"
  currency: CAD
  date_opened: 2026-04-15
  cash_basis: true                      # ← the Q-018 blessed marker
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
    txn_guid: "<bank tx guid>"
    txn_split_guid: "<bank tx's AR-side split guid>"
    memo: "INV-CASH-001 cash sale"
```

Outcome: invoice posted + paid, AR lot closed at $0 same-day, single bank tx preserved with original GUID, `cash_basis: true` survives as a KVP slot.

## Tests

- `test_same_date_post_pay_via_retarget_produces_paid_invoice` — verifies the basic workflow (probe behavior promoted to a regression test).
- `test_cash_basis_kvp_roundtrips` — `cash_basis: true` survives export → re-import unchanged, queryable via `get_custom_metadata(invoice)`.
- `test_cash_basis_with_partial_payment_is_allowed` — partial payment + `cash_basis: true` produces no error, AR has the expected open balance, the flag still applies to the invoice.
- `test_cash_basis_flag_does_not_appear_in_pdf` — rendered HTML for an invoice with the flag is byte-identical (after stripping non-deterministic IDs) to the same invoice without the flag.

## Out of scope

- Per-payment tax-method classification (a single invoice with one cash-basis payment + one accrual-basis prepayment) — not a real-world pattern; deferred.
- Reporting tools that filter on the flag — different surface, separate ticket if/when a user needs them.
- Bills — analogous `cash_basis: true` on the bill side works exactly the same way via the existing KVP path; not separately blessed here because bills are less commonly a tax-method concern (vendors' invoices to you are receipts of expense, not revenue).

## Related

- **Q-016** — the `txn_guid:` + `txn_split_guid:` retarget mechanism. Q-018's canonical workflow depends on it.
- **Q-017** — `print-invoice --format plaintext` and informational totals. Q-018 confirms the `cash_basis` flag does NOT affect Q-017's rendered output.
