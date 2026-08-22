---
id: Q-019
title: "Draft tax breakdown + `print-bill` + two-sided rendering with company info"
category: quality
severity: medium
status: closed
---

> **The printed page has since changed ([Q-036](Q-036-printed-pages-were-not-gnucashs-own.md)).**
> `print-bill`, the plaintext seller header and the draft tax figures in plaintext stand. The HTML
> and PDF page is GnuCash's own Printable Invoice: it puts the record's owner in one block and
> the seller in the other — a bill is a vendor's invoice, so the vendor is its owner — rather than
> the "Bill From" / "Bill To" headings this project chose, it prices an unposted one from
> its entries itself, and it states tax as one total rather than as named GST and PST rows.

## Three related gaps in the rendering surface

**1. Draft invoices lost their tax breakdown.** A cash-basis invoice (Q-018) doesn't post until cash arrives — and an accrual draft hasn't been posted yet either. Both render through the "is_draft" path, which historically (Q-012) emitted subtotal-only with no `<tax-lines>` and no grand total. For a Canadian small-business filer issuing a cash-basis invoice with GST/HST, this means the rendered PDF shows the wrong amount — line items only, no tax — exactly the case where tax detail matters most.

**2. The plaintext renderer silently dropped seller info.** `render_to_plaintext(invoice, book, company_info=None)` accepted a `company_info=` parameter but never referenced it in its body — every rendered plaintext invoice came out with only the customer block, no "issued by" header. Customers receiving a plaintext invoice had no way to tell who sent it. The HTML/PDF path was correct (the XSLT renders a "From" block when book options carry Company Name), but the plaintext path quietly bypassed it.

**3. Vendor bills had no renderer at all.** `cli/invoice_print_cmd.py:39` explicitly filters out vendor bills ("Customer invoices only — skip vendor bills"). There was no `print-bill` CLI command, no `bill.xslt`, no `bill_renderer.py`. Cash-basis bill audit-print — useful for reviewing what you've recorded against what the vendor sent — was simply not supported.

The three gaps share a single underlying assumption: *the renderer treats GnuCash's post-time data shape as the source of truth*. GnuCash only materialises tax splits at posting; it only stores company info under Business book options that nothing in the plaintext path ever wires up; and bills are GnuCash's `GncInvoice` objects too but routed through different SWIG getters (the `gncEntryGetBill*` family). Q-019 closes all three by computing what we need from primary sources (entries' tax_table, book options, vendor-side getters) rather than waiting for GnuCash to give it to us.

## Resolution

### Draft tax breakdown — computed from entries

`compute_entry_informational` (added in Q-017) already returns `(net_amount, entry_tax, breakdown)` for any invoice entry — it walks the entry's `tax_table` and applies the rate, identical math to what GnuCash does at post time. Q-019 calls this from `invoice_to_xml` on the `is_draft` branch, aggregates per-tax-account totals into `<tax-lines>`, emits a real `<subtotal>`/`<total>`, and adds an empty `<draft-tax-notice/>` element. The XSLT renders the notice as a muted italic row under the tax-lines: *"Tax is computed from line-item tax tables; invoice not yet posted — figures are provisional."*

For the plaintext path, the `if not is_draft:` gates around `entry_amount` / `entry_tax` / `breakdown:` / `invoice_tax_total` / `invoice_total` are dropped — these are emitted for every invoice. Drafts get a leading `# Tax figures are provisional — invoice not yet posted; recomputed at post time.` comment so the recipient knows the numbers will change. The parser was extended to skip lines whose lstrip() starts with `#`, so rendered output re-imports cleanly without the caveats polluting the recipient's book.

The badge logic from Q-018 is preserved: plain accrual draft → DRAFT badge, cash-basis unposted → UNPAID badge. Only the tax-rendering rule changes; both flavors of unposted invoice now show full tax detail.

### Plaintext seller header

`render_to_plaintext` now emits a `# Issued by: <name> | Company ID: <id> | <addr> | <phone> | <email> | <url>` comment line at the top of each invoice block when `company_info` is populated. Comment-line form means the seller info doesn't survive re-import as KVPs — we don't want the recipient's book polluted with the sender's company info. The `Company ID:` label is jurisdiction-neutral (matches the GnuCash slot name verbatim) — the slot value is whatever tax-registration the issuer uses (CRA GST/HST, US EIN, UK VAT, HK BR, JP corporate number); validity of ITC claims depends on the value, not the label.

### `print-bill` CLI + `bill_renderer.py` + `bill.xslt`

`cli/bill_print_cmd.py` mirrors `invoice_print_cmd.py` exactly: same flags (`--format {pdf,html,plaintext}`, `--vendor`, `--from`, `--to`, `--bill-id`, `--report`, `--report-file`, `-o`), same multi-bill selection (positional IDs, globs, date ranges), same combined/per-bill output modes.

`services/bill_renderer.py` uses the Bill-side SWIG getters (`gncEntryGetBillTaxable`, `gncEntryGetBillTaxTable`, `gncEntryGetBillPrice`, etc.) per CLAUDE.md's "Bill Entry API vs Invoice Entry API" rule, and exposes `compute_bill_entry_informational` as the bill analogue of the invoice helper. The posted-bill tax extraction filters by "everything that's not the AP-posting account and not an Expense account is a tax accrual" — this covers both LIABILITY tax-accrual accounts and ASSET ITC-recoverable accounts (Canadian input-tax-credit books).

`services/bill.xslt` mirrors `invoice.xslt` with the address sides swapped:
- **Bill From** = the vendor (the supplier sending us the bill)
- **Bill To** = our company (read from book options via `read_book_company_info`)

The plaintext bill path emits a `# Bill received by: <us>` header plus a `# Bill from vendor: <vendor>` line so the audit reader sees both sides at a glance.

## Two-sided rendering — both sides verified by tests

The bug behind gap #2 ("plaintext silently dropped company info") existed because no test ever populated real Business → Company book options and verified the renderer emitted the From block. The new test suite (`tests/integration/test_q019_two_sided_render.py`) populates real options via the SWIG KvpFrame API (`book.GetSlots().set_slot_path(['options','Business','Company Name'], KvpValue('Acme'))`), then runs `print-invoice` / `print-bill` through the full CLI pipeline — which calls `read_book_company_info` itself. Mocking `company_info` would have left the reader-to-renderer wiring untested, exactly where the original bug hid.

Coverage breakdown:
- **Cash-basis unposted invoice with GST 5% + PST 7%** → HTML shows both tax-line rows (per-account aggregation), correct grand total (200 + 24 = 224), provisional notice. Plaintext shows the `#` caveat, `entry_tax: 24.00`, two `breakdown:` blocks, `invoice_total: 224.00`.
- **Plain accrual draft with single 10% Sales Tax** → DRAFT badge preserved, single tax-line row, `tax-single` CSS class, correct total (300 + 30 = 330).
- **Rendered draft plaintext re-imports without error** → verifies the parser's new `#`-comment handling.
- **Invoice two-sided HTML** → asserts BOTH "Bill To" customer block AND "From" company block present with all populated fields (name, Company ID, address, phone, email, URL).
- **Invoice plaintext seller header** → asserts the first line of the rendered text is `# Issued by: ` followed by every company field.
- **Bill two-sided HTML** → asserts "Bill From" = vendor and "Bill To" = us; verifies the same tax-line + provisional-notice behaviour on the bill side.
- **Bill plaintext** → asserts both `# Bill received by: <us>` and `# Bill from vendor: <vendor>` headers + `bill_subtotal` / `bill_tax_total` / `bill_total` fields.

The generic GST 5% + PST 7% and single 10% Sales Tax tables (rather than Ontario HST 13%) keep the fixtures meaningful across the user's multi-jurisdiction book set.

## Files touched

| File | Change |
|---|---|
| `services/invoice_renderer.py` | `invoice_to_xml`: compute draft tax from entries via `compute_entry_informational`, emit `<tax-lines>` + `<draft-tax-notice/>`. `render_to_plaintext`: drop `if not is_draft:` gates, prepend `# Issued by:` seller header from `company_info`, prepend `# Tax figures are provisional` caveat on drafts. New helper `_render_seller_header`. |
| `services/invoice.xslt` | New XSLT template renders `<draft-tax-notice/>` as a muted italic row under tax-lines. |
| `services/plaintext_parser.py` | `parse_iterable` skips lines whose `lstrip()` starts with `#` so rendered caveat lines round-trip through re-import. |
| `services/bill_renderer.py` | New module: `bill_to_xml`, `render_to_html`, `render_to_plaintext`, `compute_bill_entry_informational`, `_read_bill_tax_label`. Uses Bill-side SWIG getters per CLAUDE.md. (A `render_to_pdf` was written here and on the invoice side and never called: `print-bill` and `print-invoice` build their own combined HTML — one shell around several pages — and hand that to weasyprint, so a per-page PDF helper had no caller. Both deleted.) |
| `services/bill.xslt` | New XSLT, mirrors `invoice.xslt` with Bill From/Bill To roles swapped. |
| `cli/bill_print_cmd.py` | New `print-bill` Click command — same flag surface as `print-invoice`. |
| `cli/main.py` | Register `print-bill`. |
| `tests/fixtures/q019_accounts.txt` | Q-019 accounts tree (AR, AP, Expenses, generic tax accounts). |
| `tests/fixtures/q019_unposted_cash_with_tax.txt` | Cash-basis unposted invoice, GST+PST combined tax. |
| `tests/fixtures/q019_unposted_draft_with_tax.txt` | Plain accrual draft invoice, single Sales Tax. |
| `tests/fixtures/q019_unposted_cash_bill.txt` | Cash-basis unposted bill, GST+PST combined tax. |
| `tests/integration/test_q019_draft_tax_render.py` | Draft tax breakdown + re-import smoke. |
| `tests/integration/test_q019_two_sided_render.py` | Two-sided HTML + plaintext seller header for invoice and bill, end-to-end through the CLI with real book options. |
| `docs/issues/Q-018-cash-basis-invoice-kvp.md` | Note that informational fields now ride along on every unposted invoice (cash-basis OR accrual draft). |
| `docs/issues/Q-012-print-invoice-on-unposted-invoice-crashes.md` | Strike the "no per-tax breakdown" known limitation; note `print-bill` shipped. |

## Out of scope

- **Watermarks / "DRAFT" overlay on PDFs.** The XSLT badge plus the new provisional-tax caveat row carry the same information without weasyprint background hacks.
- **Customer-supplied seller info override.** The seller header always comes from book options; we don't accept `--from "Other Co"` overrides. Users who need different seller info per invoice use multiple GnuCash books, one per legal entity.
- **A `print-receipt` command.** A paid cash-basis invoice already renders with a PAID badge and the payment history block; that's a receipt.

---

**Created**: 2026-05-21
