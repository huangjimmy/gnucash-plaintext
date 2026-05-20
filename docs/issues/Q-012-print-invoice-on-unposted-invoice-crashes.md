---
id: Q-012
title: `print-invoice` on an unposted invoice crashes with NoneType error
category: quality
severity: medium
status: closed
---

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

## Known limitation (Q-012 v1)

A draft invoice's PDF will show subtotal but **no per-tax breakdown**
(no GST line, PST line, etc.) and no grand total inclusive of tax. To
compute taxes pre-posting we'd need to walk each entry's `tax_table`
and apply the rate (PERCENT/VALUE) per entry, then aggregate by tax
account — non-trivial because GnuCash's `gnc_entry_get_value` /
`gnc_entry_get_tax_value` SWIG bindings are unreliable across versions
(per CLAUDE.md hard-won findings). A future issue can extend this.

For the draft preview use case, showing line items + subtotal is
already a meaningful improvement over "500 Internal Server Error".

## Files to change

| File | Change |
|---|---|
| `services/invoice_renderer.py` | Branch on `posting_txn is None`. Compute subtotal from entries. Skip tax-lines / payments / amount-remaining for drafts. Set `status='draft'`. |
| `services/invoice.xslt` | Add `'draft'` case to the status badge `<xsl:choose>`. Add `.badge-draft` CSS rule. |
| `tests/integration/test_q012_print_unposted_invoice.py` | New test file: print-invoice on unposted → exit 0 + PDF created; rendered HTML contains DRAFT badge; rendered HTML contains entry rows; rendered HTML does NOT contain payment-history table. |

## Out of scope

- Computing tax breakdown for drafts (see Known limitation above).
- A "watermark" / overlay on draft PDFs — `badge-draft` in the header
  is enough signal.
- Bill rendering — there's no `print-bill` command; bills are received,
  not sent.

---

**Created**: 2026-05-08
