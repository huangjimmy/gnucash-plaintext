---
id: Q-018
title: "`cash_basis: true` invoice marker for cash-basis tax filing"
category: quality
severity: low
status: closed
---

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

The flag does NOT expose the issuer's tax-method classification to the customer. Cash basis vs accrual basis is internal to the issuer's filing; the customer paying the bill doesn't see "cash basis" anywhere in the rendered output. The literal string `cash_basis` never appears in the customer-facing HTML/PDF, and the document title stays "Invoice" — no "Sales Receipt" relabel.

For **posted** invoices (the same-day post+pay path), customer-facing rendering is fully unchanged regardless of the flag — the existing PAID badge already says everything that matters.

The `--format plaintext` output (Q-017) doesn't change either — the existing informational fields (`entry_amount`, `entry_tax`, `breakdown:`, invoice totals) cover all the audit numbers; the flag rides along as a header KVP slot for the issuer's own tooling. Q-019 generalises the informational-field emission so they're present on every unposted invoice (cash-basis or accrual draft), not only on posted ones.

The GnuCash UI continues to show the invoice in its normal posted/paid state — the flag lives in the KVP slot, not in GnuCash's invoice schema.

## What this issue actually adds

1. **A blessed name in the format spec.** Documenting `cash_basis: true` as the canonical KVP marker for cash-basis intent, so all tools / scripts / future features that filter by tax-method use the same spelling. Without blessing, three different users would pick three different names (`cash_basis`, `tax_method`, `revenue_basis`) and downstream tooling would have to guess.

2. **The canonical workflow recipe (paid-on-receipt).** Cash-basis filers commonly want "post and pay on the same day from an already-imported bank tx." This works today via Q-016 retarget — set `posted.date == payment.date == bank-tx.date` and use `txn_guid:` + `txn_split_guid:` in the payment block to link the existing bank tx. We document the recipe so users don't have to reinvent it.

3. **A render adjustment for the UNPOSTED case.** A cash-basis invoice doesn't post until cash arrives — but the customer still needs a payable document in the meantime. Today's Q-012 path renders any unposted invoice with a DRAFT badge, which is the wrong label for a real bill awaiting payment. When `cash_basis: true` is set on an unposted invoice, the renderer now emits an **UNPAID** badge instead of DRAFT. The Q-012 draft path is preserved for invoices that do NOT carry the flag (work-in-progress drafts still render with the DRAFT badge, unchanged).

4. **An optional `due_date:` KVP slot.** For unposted cash-basis invoices, the `posted:` block is absent so there's no `posted.due` to pull a due date from. An optional `due_date: YYYY-MM-DD` line on the invoice header provides the customer-facing due date. The renderer reads it only when the invoice is unposted — once posted, the GnuCash `posted.due` field takes over and `due_date` KVP is ignored. The XSLT renders the "Due:" meta row only when the date is non-empty, so a cash-basis invoice with no `due_date` KVP gets no "Due:" line at all.

5. **An integration test suite pinning the round-trip and the render.** `tests/integration/test_q018_cash_basis_marker.py` (7 cases): same-day post+pay produces invoice posted+paid with AR balanced same-day and a single bank tx; `cash_basis: true` survives import → export → fresh-book re-import as a KVP slot; partial payment with the flag still applies (no validator); the literal string `cash_basis` never appears in customer-facing HTML; unposted cash-basis with `due_date` KVP renders UNPAID + the date; unposted cash-basis without `due_date` renders UNPAID with no due-date row; unposted invoice WITHOUT the flag still renders DRAFT (Q-012 regression).

Code touched: `services/invoice_renderer.py::invoice_to_xml` (reads the KVP, decides between draft/unpaid badge, falls back to `due_date` KVP for unposted invoices); `services/invoice.xslt` (the "Due:" meta row is now conditional on a non-empty value). No importer/exporter/CLI changes — the KVP path stores `cash_basis: true` and `due_date: <date>` automatically via the existing custom-metadata mechanism.

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
- `test_cash_basis_flag_does_not_appear_in_pdf_or_html` — for the **posted** path, rendered HTML for an invoice with the flag is byte-identical (after stripping non-deterministic IDs) to the same invoice without the flag, and the literal string `cash_basis` never appears in customer-facing HTML.
- `test_unposted_cash_basis_with_due_date_renders_unpaid` — fixture with `cash_basis: true` and `due_date: 2026-05-30` on an unposted invoice; assert UNPAID badge present, DRAFT badge absent, the date appears in the meta row, and the literal "cash_basis" stays out of the HTML.
- `test_unposted_cash_basis_without_due_date_renders_unpaid_no_due_row` — same flag, no `due_date` KVP; UNPAID badge present, and the `<strong>Due:</strong>` label omitted entirely.
- `test_unposted_invoice_without_cash_basis_still_renders_draft` — Q-012 regression: an unposted invoice with no Q-018 flag still renders DRAFT.

## Intentionally not supported: bank tx that already has the income/tax breakdown

If the user imports a bank transaction that already carries the FULL cash-sale legs — `Bank: +113`, `Income:Sales: −100`, `Liabilities:Tax:HST: −13` with NO `Accounts Receivable` split at all — Q-018 cannot link it to an invoice. The paid-on-receipt workflow relies on Q-016 retarget, which requires an AR-side split on the bank tx to move into the invoice's posted lot. A bank tx without an AR leg has nothing to retarget.

We deliberately don't build a "linked payment" feature for this shape. The right machinery would have to (a) validate the bank tx's Income split account matches each invoice entry's `account:`, (b) enumerate the invoice entry's `tax_table` entries and verify each maps to a tax-account split on the bank tx with the right amount, (c) maintain a KVP linkage that the renderer overrides `gncInvoiceIsPaid()` against. The validation surface is large, the audience is narrow (users who keep their books in this specific pre-broken-down shape AND want invoice documents for the same sale), and a simple workaround exists.

**Workaround for users in this situation**: restructure the bank tx to the standard "Bank + AR" cash-sale shape:

```
2026-05-20 * "Acme cash sale"
  Assets:Bank                  113.00 CAD
  Assets:Accounts Receivable  -113.00 CAD
```

Then post the invoice through the standard Q-018 paid-on-receipt workflow. The GnuCash-generated posting tx will create the Income and Tax splits on the same date, the Q-016 retarget will close the AR lot, and the books end up with two same-day transactions (bank + posting) that net to a clean cash-basis P&L. The shape the user gave up is exactly the shape Q-018 doesn't need.

For users who genuinely cannot restructure (e.g. the bank tx came from a QFX import that they need to preserve byte-identically for reconciliation), the fallback is the unposted path documented above: leave the invoice unposted with `cash_basis: true` (renders UNPAID until they manually post) and treat the link between the invoice document and the bank tx as documentary only (via memo / notes), not via GnuCash's posting machinery.

## Out of scope

- Per-payment tax-method classification (a single invoice with one cash-basis payment + one accrual-basis prepayment) — not a real-world pattern; deferred.
- Reporting tools that filter on the flag — different surface, separate ticket if/when a user needs them.
- Bills — analogous `cash_basis: true` on the bill side works exactly the same way via the existing KVP path; not separately blessed here because bills are less commonly a tax-method concern (vendors' invoices to you are receipts of expense, not revenue).

## Related

- **Q-016** — the `txn_guid:` + `txn_split_guid:` retarget mechanism. Q-018's canonical workflow depends on it.
- **Q-017** — `print-invoice --format plaintext` and informational totals. Q-018 confirms the `cash_basis` flag does NOT affect Q-017's rendered output.
