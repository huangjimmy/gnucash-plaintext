---
id: Q-011
title: Invoice `action` field forces a hardcode; UNIT column shows nonsense; no template override
category: quality
severity: low
status: closed
---

> **The printed page has since changed ([Q-036](Q-036-printed-pages-were-not-gnucashs-own.md)).**
> A PDF or HTML page is drawn by GnuCash's own Printable Invoice, which decides its own
> columns — an entry's `action:` fills its Action column, and the column is drawn whether or not
> anything fills it. `--template` and the XSLT it took are gone with the second renderer they
> drove; the `action:` field being optional, which is the rest of this issue, is unchanged.

## Decisions

1. **Hide the UNIT column when no entry has an `action` value.**
   If every entry on the invoice has `action == null` or `action == ""`,
   the rendered PDF should drop the column entirely — both header and
   cells — leaving a clean Description / Qty / Unit Price / Amount /
   Tax layout. If at least one entry has a non-empty action, the column
   stays (with blank cells for entries that don't).

2. **Allow power users to pass a custom XSLT** via `--template <path>`
   on `print-invoice`. Default to the embedded `services/invoice.xslt`.
   Users with branded layouts, custom columns, or different languages
   can supply their own without forking the tool.

## Implementation

### Importer: make `action` optional

`services/gnucash_importer.py:1641`:
```python
entry.SetAction(entry_directive.metadata.get('action', ''))
```

The Q-010 matcher (`_entry_matches_invoice_directive`) compares
`md['action']` — needs the same `.get('action', '')` fallback so a
re-imported invoice without an `action` field still reports `unchanged`
when the existing entry's action is empty.

### Exporter: keep emitting `action: ""` even when empty

No change to the exporter. It continues to emit `action: "<value>"`
unconditionally — even when value is `""`. Round-trip fidelity: the
.txt mirrors exactly what GnuCash holds, so a user inspecting the
exported text can tell that the action field is *explicitly* empty (not
forgotten or stripped). The PDF/HTML rendering decides whether to
*display* it; the .txt remains a faithful representation.

**Background**: empirical probe confirmed that GnuCash itself
initialises the action field to `""` (not NULL) for fresh entries.
There is no NULL-vs-empty distinction at the C/SWIG layer; "never set"
and `SetAction("")` produce the same state, and the .txt likewise
treats them as equivalent. The exporter therefore never has anything
"null" to emit — only string values, which may be empty.

### XSLT: conditional UNIT column

Use `count()` over the entries: if `count(entries/entry[action != ''])`
is zero, both the `<th>UNIT</th>` and the per-row cells are skipped.
Two `<xsl:if>` guards.

### CLI: --template flag

`cli/invoice_print_cmd.py` — add a `--template <path>` Click option,
default to the package-relative `services/invoice.xslt`. The
`render_to_pdf` function already takes an `xslt_path` arg, so this is
mostly a CLI-surface change.

### Docs: clarify action is optional

- `README.md` examples that use `action: "Hours"` for non-hours-billed
  examples should drop the line.
- Add a section: "The `action:` field is optional. Leave it empty for
  goods/items; populate with 'Hours', 'Project', etc. when meaningful
  to your invoicing workflow."

## Tests

- Test that an invoice with all-empty actions renders a PDF with no
  UNIT column. Compare cell counts in the rendered HTML.
- Test that a mixed invoice (some entries with action, some without)
  keeps the column.
- Test importer accepts directives with no `action:` field.
- Test exporter omits `action:` line when action is empty.
- Test re-import roundtrip: empty action → no action: line → empty
  action.
- Test `--template <path>` overrides the embedded XSLT (use a stub
  XSLT that emits a known sentinel).

## Out of scope

- Renaming the column header from "UNIT" to "Action" — even when shown,
  "UNIT" is misleading, but that's a docs/UX call separate from the
  immediate bug. Defer to a follow-up if anyone wants it.
- Localising the embedded template — power users can supply their own
  via `--template`.
- Smart defaults like "Item" or "Goods" for missing action — leaves
  the user's intent clearer to leave it blank than to invent a value.

## Related

- **Q-016** — separately makes invoice payment-block roundtrip
  deterministic (`txn_guid:` + `txn_split_guid:` always emitted on
  export). No interaction with the action / UNIT-column work here,
  but invoices touched by both issues will carry both the optional
  `action:` field and the full payment-block GUID set after export.

---

**Created**: 2026-05-08
