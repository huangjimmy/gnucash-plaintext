---
id: Q-017
title: "`print-invoice` plaintext format with tax totals; multi-invoice selection"
category: quality
severity: low
status: closed
---

## Pain point

Today the only way to see *structured* invoice totals (subtotal, tax, total) is to render to HTML or PDF. The canonical plaintext export (`export --include-business-objects`) carries `entry: quantity/price + tax_table:` only — to audit "how much GST did Acme charge me in Q1" you must either re-run the tax-table math yourself or open every rendered PDF. A `git diff` on last quarter's invoices shows only the structural changes, not the tax-amount deltas that matter for compliance review.

A second pain point came out of the same conversation: `print-invoice` accepts a single `--invoice-id` only. Printing a quarter of invoices into one PDF for the auditor requires a shell loop and external concatenation.

## Decision (from the design discussion)

One plaintext format — the existing canonical one — with **informational** fields added. The renderer (`print-invoice`) emits the same plaintext syntax but with derived totals populated; the canonical exporter (`export`) keeps emitting only the source-of-truth fields. Re-importing a render-output plaintext recomputes the informational fields from the source-of-truth fields and **errors loudly on mismatch** — so the format has tamper detection without dual-source-of-truth ambiguity.

Same ticket also adds multi-invoice selection to `print-invoice` (and composes selection logic across all output formats — plaintext, pdf, html) so both improvements ship together.

## Format spec — source-of-truth vs informational fields

### Source of truth (already emitted by `export`)

| Field | Where | Notes |
|---|---|---|
| `entry: quantity` | per-entry | what you charged for |
| `entry: price` | per-entry | unit price |
| `entry: tax_table` | per-entry | named reference; rate stored in tax-table object |
| `entry: tax_included` | per-entry | true = price already includes tax |
| `posted: ar_account` | per-invoice | AR account; tax-account is on the tax-table entries |

### Informational (new — emitted by `print-invoice --format plaintext`)

| Field | Where | Computed from |
|---|---|---|
| `entry: entry_amount` | per-entry | `quantity × price` (net of tax_included adjustment); the line subtotal |
| `entry: entry_tax` | per-entry | per-entry total tax; sum of `entry_amount × rate` across the tax-table entries |
| `entry: breakdown:` | per-entry, repeatable | one nested block per tax-table entry (so `breakdown:` repeats for a combined HST table): `account`, `rate`, `amount`. Audit-friendly: shows which government received which dollar from this line. |
| `invoice_subtotal` | per-invoice | sum of all `entry_amount` |
| `invoice_tax_total` | per-invoice | sum of all `entry_tax` |
| `invoice_total` | per-invoice | `invoice_subtotal + invoice_tax_total` |

Bills get analogous `bill_subtotal`/`bill_tax_total`/`bill_total` fields. Same rules.

Example informational block for an entry with a combined HST (5% GST + 8% PST) on a $100 line:

```
entry:
  quantity: 1
  price: 100
  tax_table: "HST"
  tax_included: false
  entry_amount: 100.00
  entry_tax: 13.00
  breakdown:
    account: "Liabilities:Tax:GST"
    rate: 5.0
    amount: 5.00
  breakdown:
    account: "Liabilities:Tax:PST"
    rate: 8.0
    amount: 8.00
```

`breakdown:` is a repeatable nested block (one instance per tax-table entry) — same shape as how `entry:` repeats inside a `taxtable` block today, so the parser handles it via the existing indented-children path.

### Import-side validation

On import, every informational field is **recomputed from source-of-truth fields**. If the recomputed value differs from the declared value by more than 0.01 of the invoice's currency unit, the importer raises an error naming the field and both values. The recomputed value is what the book stores — declared informational fields never override.

For `breakdown:` blocks under an entry, the importer enumerates the named `tax_table`'s entries and validates: (a) each declared `account` exists as a tax-table entry on that table, (b) each declared `rate` matches the table's stored rate within 0.001%, (c) each declared `amount` equals `entry_amount × rate`. Missing or extra breakdown blocks are also errors.

Rationale: the informational field is for the human (grep, diff, audit). The source-of-truth fields are for the machine (round-trip). Mismatch means something was tampered with; better to fail loud than pick a winner silently. This is the same shape as Q-015's `prepayment:` cross-check.

### Draft (unposted) invoices

Drafts have no posted tax splits. `print-invoice --format plaintext` on a draft emits `invoice_subtotal` only (per-entry `entry_tax` and the tax totals require posting). Same constraint the HTML/PDF renderer has today (the DRAFT badge signals exactly this).

## CLI — multi-invoice selection

`print-invoice` learns to accept multiple invoices via any of these (mutually composable except the positional + glob forms, which are alternatives):

```
print-invoice book.gnucash INV-001 INV-002 INV-003 -o combined.pdf
print-invoice book.gnucash --from 2026-01-01 --to 2026-03-31 -o q1.pdf
print-invoice book.gnucash --customer C-001 -o acme.pdf
print-invoice book.gnucash 'INV-2026-*' -o year.pdf
```

Selection options:
- Positional `[invoice_ids...]` — zero or more invoice IDs
- `--from DATE` / `--to DATE` — date range (date_opened)
- `--customer ID` / `--customer-guid GUID` — all invoices for one customer
- Glob form in any positional argument (`INV-2026-*`, `*-Q1-*`)
- All selectors are AND-composed; result must be non-empty (error otherwise)

`--invoice-id` is kept as a single-value alias for back-compat (deprecated but functional).

## CLI — output composition

`--format {pdf,html,plaintext}` defaults to `pdf` (back-compat).

| `--output` value | pdf | html | plaintext |
|---|---|---|---|
| `file.ext` | combined multi-page pdf | combined html file with `<section>` per invoice | combined plaintext stream |
| `dir/` | one file per invoice in `dir/` | one file per invoice in `dir/` | one file per invoice in `dir/` |
| `-` | (error — pdf is binary) | (error — interactive html) | stream to stdout |

The combined-pdf path uses WeasyPrint's "render multiple HTML strings → one PDF" mode (already supported by the lib). Combined-html wraps the per-invoice fragments in a minimal shell (`<html><body>`). Combined-plaintext is a literal concatenation with a blank line between invoice blocks.

## Implementation outline

### Files changed

- `cli/invoice_print_cmd.py` — add `--format`, selector flags, multi-output; keep `--invoice-id` working.
- `services/invoice_renderer.py` — extract a per-entry tax-amount helper from the tax-table (currently only the label is read). Add `render_to_plaintext(invoice, book, company_info) → str` that emits the canonical plaintext-syntax representation populated with informational fields.
- `services/gnucash_importer.py` — recognise `entry_tax`, `invoice_subtotal`, `invoice_tax_total`, `invoice_total` on invoice/entry directives (and the bill analogues). Recompute, cross-check, error on mismatch.
- `infrastructure/gnucash/kvp.py` — add the new field names to the known-field sets so they don't fall into the custom-KVP path.
- `use_cases/print_invoice.py` (new) — selection logic shared across formats; output-composition dispatcher.

### Tests (`tests/integration/test_q017_*.py`)

- `test_print_invoice_plaintext_format_emits_informational_fields` — a posted invoice with one HST 13% line; assert `entry_amount: 100.00`, `entry_tax: 13.00`, `invoice_subtotal: 100.00`, `invoice_tax_total: 13.00`, `invoice_total: 113.00` are present with correct values.
- `test_print_invoice_plaintext_emits_tax_breakdown_combined_table` — invoice with one entry against a combined-HST tax table (5% GST + 8% PST); assert `entry_tax_breakdown:` lists both tax-account/rate/amount lines with the right per-account dollars.
- `test_render_plaintext_roundtrips_via_import` — `print-invoice --format plaintext > out.txt`, then `import --new fresh.gnucash out.txt`, succeeds with no diff.
- `test_tampered_informational_field_errors_loudly` — same as above but hand-edit `invoice_tax_total: 13.00 → 99.00`; re-import must fail with an error naming the field and both values.
- `test_draft_invoice_plaintext_subtotal_only` — unposted invoice; `print-invoice --format plaintext` emits `invoice_subtotal:` and NO `entry_tax`/`invoice_tax_total`/`invoice_total`.
- `test_multi_invoice_by_ids` — 3 invoices, print combined pdf, assert 3 page-groups (verify with pdfinfo or similar).
- `test_multi_invoice_by_date_range` — 5 invoices, `--from`/`--to` selects 2; assert output has exactly 2.
- `test_multi_invoice_by_customer` — 4 invoices across 2 customers; `--customer` filters to 2.
- `test_multi_invoice_glob` — `INV-2026-*` selects only the matching ones.
- `test_output_dir_emits_one_file_per_invoice` — `--output dir/`, assert `dir/INV-001.pdf`, `dir/INV-002.pdf` exist.
- `test_plaintext_stdout` — `--format plaintext --output -` writes to stdout (capture and check).
- `test_bill_plaintext_emits_informational_fields` — bill equivalent (if `print-bill` exists; otherwise scope to invoices only).

Each fixture in `tests/fixtures/q017_*.txt`, one scenario per file with distinct amounts.

### Docs

- `README.md` — update the print-invoice section: new `--format`, multi-invoice flags, one-paragraph note on the informational fields.
- `docs/gnucash-beancount-format.md` (or wherever the field reference lives) — add an "Informational fields" subsection with the table from this issue doc.
- `docs/comprehensive-roundtrip-example.md` — note the new format exists; canonical example unchanged.

## Out of scope

- Bill multi-print — depends on whether `print-bill` exists. (Research note: no `print-bill` today. If users want bill printing, that's a separate ticket — scope creep here would multiply the surface.)
- Bank-tx printing or transaction reports — different surface entirely.

## Related

- **Q-011** — invoice action optional + custom XSLT template. The XSLT pipeline this builds on.
- **Q-012** — `print-invoice` on unposted invoices (draft mode). The draft constraint above inherits from Q-012.
- **Q-015** — `prepayment:` cross-check is the same validation pattern this issue uses for informational tax fields.
