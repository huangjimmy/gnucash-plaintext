---
id: Q-012
title: `print-invoice` on an unposted invoice crashes with NoneType error
category: quality
severity: medium
status: closed
---

> **The printed page has since changed ([Q-036](Q-036-printed-documents-are-not-gnucashs-page.md)).**
> An unposted document is drawn by GnuCash's own Printable Invoice, which prices it from its
> entries and marks it "Invoice in progress…". The crash and the refusal to drop unposted
> documents stand; the draft badge and the provisional-tax caption described below were part of
> this project's own page and are gone with it.

## Problem

Calling `gnucash-plaintext print-invoice <book> --invoice-id <id>` on an
**unposted** invoice (one with `posted: none` in plaintext, or
unposted in the GnuCash UI) crashes the renderer with a stack trace:

```
File "services/invoice_renderer.py", line 179, in invoice_to_xml
    for i in range(posting_txn.CountSplits()):
                   ^^^^^^^^^^^^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'CountSplits'
```

`inv.GetPostedTxn()` returns `None` for unposted invoices; the renderer
unconditionally calls `.CountSplits()` on the result. Same problem one
loop later for `inv.GetPostedLot().get_split_list()`.

Reported by a real user (Cloudflare Wrangler log, 2026-05-08) when
their frontend asked the API to render an unposted draft invoice as a
PDF preview. The API returned 500 with the trace. The reviewer for
Q-011 noted this pre-existing issue and recommended a separate ticket;
filing now that a real user has hit it.

## Why it matters

Drafts are a normal workflow:

- User creates an invoice in plaintext with `posted: none`
- User wants to preview it (or share with the client) as a PDF before
  posting
- Currently impossible — must post first, then print

Posting is irreversible-ish (creates AR/AP transactions), so forcing
the user to post just to preview is a significant friction.

## Fix

Make the renderer handle unposted invoices without crashing. Strategy:

1. Detect unposted state at the top of `invoice_to_xml`:
   `posting_txn = inv.GetPostedTxn()` is None.
2. Set the invoice's XML `status` attribute to `'draft'` instead of
   `'paid'` / `'unpaid'`.
3. Compute `<subtotal>` from the entries themselves (`quantity * price`
   per entry, summed). Already trivially available — the entry loop
   computes `qty * price` for the per-row `<amount>`.
4. Skip the tax-lines, payments, and amount-remaining elements
   entirely for drafts. Tax breakdown only exists post-posting; payments
   require a posted lot.
5. Set `<total>` equal to subtotal for drafts (no tax breakdown
   yet — see "Known limitation" below).

In the XSLT (`services/invoice.xslt`), extend the existing status
`<xsl:choose>` with a `'draft'` case showing a DRAFT badge. Add a CSS
class `badge-draft` for grey/neutral colouring. The payment-history
section is already conditional (`<xsl:if test="payments/payment">`) so
it naturally vanishes when no payments exist.

## Resolved in Q-019: draft per-tax breakdown

(Originally Q-012 documented a known limitation here: draft invoices
showed subtotal only, no per-tax breakdown, because GnuCash only
materialises tax splits on the posting transaction.) Q-019 resolves
this by walking each entry's tax_table directly via
`compute_entry_informational`, aggregating per-tax-account totals, and
emitting full `<tax-lines>` + grand-total-with-tax on every unposted
invoice. A `<draft-tax-notice/>` element on the XML carries through to
the XSLT as a "figures are provisional" caption so the viewer knows
the numbers will be recomputed at post time.

## Files to change

| File | Change |
|---|---|
| `services/invoice_renderer.py` | Branch on `posting_txn is None`. Compute subtotal from entries. Skip tax-lines / payments / amount-remaining for drafts. Set `status='draft'`. |
| `services/invoice.xslt` | Add `'draft'` case to the status badge `<xsl:choose>`. Add `.badge-draft` CSS rule. |
| `tests/integration/test_q012_print_unposted_invoice.py` | New test file: print-invoice on unposted → exit 0 + PDF created; rendered HTML contains DRAFT badge; rendered HTML contains entry rows; rendered HTML does NOT contain payment-history table. |

## Out of scope (originally — both shipped later)

- ~~Computing tax breakdown for drafts.~~ → Shipped in Q-019.
- A "watermark" / overlay on draft PDFs — `badge-draft` in the header
  is enough signal.
- ~~Bill rendering — there's no `print-bill` command; bills are received,
  not sent.~~ → `print-bill` shipped in Q-019 (audit-print use case).

---

**Created**: 2026-05-08
