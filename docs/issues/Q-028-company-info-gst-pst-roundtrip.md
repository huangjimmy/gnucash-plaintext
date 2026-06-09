---
id: Q-028
title: Company info (incl. GST/PST registration numbers) is not round-tripped, and there is nowhere to record GST/PST
category: quality
severity: medium
status: closed
---

## Problem

Two related gaps in how seller/company identity is handled.

**1. Company info is read for rendering but never round-tripped.**
`read_book_company_info` (`services/invoice_renderer.py`) reads the GnuCash book-option Business slots — `Company Name`, `Company ID`, `Company Phone Number`, `Company Email Address`, `Company Website URL`, `Company Address` — and `print-invoice` / `print-bill` render them in the seller block (HTML/PDF `<company>` element and the plaintext `# Issued by:` / `# Bill received by:` header). But **nothing exports or imports these fields**: the only writer of Business options, `set_book_string_option` (`infrastructure/gnucash/kvp.py`), is called only from tests; the plaintext exporter emits no company directive and the importer parses none. So an `export → import` into a fresh book silently **loses all company identity** (Company Name, Company ID, address, contact). Company ID in particular is well covered on the read/render side (`test_set_book_string_option.py`, `test_invoice_renderer.py`, `test_q019_two_sided_render.py`) but **has no round-trip test** because there is no round-trip.

**2. GnuCash has no GST/PST field.**
GnuCash's Business options expose exactly one generic identifier, `Company ID` — there is no GST, PST, QST, or VAT registration field. A Canadian filer who must print *both* a GST/HST number and a provincial PST/QST number on the same invoice has only one slot, and ends up cramming the second number into the Company Name or Address string. There is no first-class place to record additional tax-registration numbers, and therefore no way to render them cleanly.

## Fix

Introduce a book-level `company` directive that round-trips the Business → Company options through plaintext, **and** add dedicated GST/PST registration keys stored alongside `Company ID`.

### New company keys (stored as Business option slots)

GnuCash preserves arbitrary string slots under `options → Business`, so the new numbers are stored there next to the native `Company ID`, written via `set_book_string_option(book, 'Business', <key>, <value>)`:

| Plaintext key | Business slot key | Notes |
|---|---|---|
| `gst` | `Company GST Number` | GST/HST registration number — a single value |
| `pst` | `Company PST Number` | Provincial PST/QST — **one slot may hold several** numbers separated by `;` |

`read_book_company_info` gains `gst` and `pst` in its returned dict. The native `Company ID` is preserved unchanged; GST/PST are **additive**, not a replacement.

**Multiple PST numbers.** A filer can be registered for PST/QST in more than one province. GnuCash storage is fundamentally one string slot, so rather than inventing repeated-key parsing (which would flatten to one slot anyway), `pst` carries several numbers in one value separated by `;` — e.g. `pst: "BC PST-1234-5678; SK 9012-3456"`. The renderer splits on `;` and emits one PST row per number; storage and round-trip stay a single verbatim string. `gst` is always one value.

### `company` directive (export + import)

Beyond GST/PST, the directive round-trips **every** native GnuCash Business field — the ones in File → Properties → Business (`name`, `contact`, `id`, `phone`, `fax`, `email`, `url`, and the multi-line address) — because none of them were exported or imported before. The exporter emits a single book-level block as the first section of the business-objects export:

```
company
	name: "Acme Inc."
	contact: "Jane Doe"
	id: "123456789RT0001"
	gst: "123456789RT0001"
	pst: "BC PST-1234-5678; SK 9012-3456"
	addr1: "100 King St W"
	addr2: "Toronto, ON M5X 1A1"
	phone: "+1-416-555-0100"
	fax: "+1-416-555-0199"
	email: "billing@acme.example"
	url: "https://acme.example"
```

Only non-empty fields are emitted (same convention as customer/vendor blocks). On import, each present field is written to its Business slot via `set_book_string_option`; absent fields are left untouched (the directive is the source of truth for the fields it names, like other blocks). The address lines are joined into the single multi-line `Company Address` slot on import and split back into `addr1..4` on export. This block is part of the `--include-business-objects` export/import path.

Import status follows the standard per-record model: `created` when the book had no company option before, `updated` when at least one field changed, `unchanged` on an idempotent re-run (compared field-by-field against the live book via `get_book_string_option`).

### Rendering

The seller/company block renders `gst` and `pst` directly under `Company ID`:

- **HTML/PDF**: new `<gst>` / `<pst>` elements in the `<company>` block (`invoice_to_xml` / `bill_to_xml`) plus the seller-block XSLT.
- **Plaintext**: extra labeled segments in `_render_seller_header`, e.g. `... | Company ID: 123… | GST: 123… | PST: PST-… | ...`.

When `gst`/`pst` are empty the output is unchanged from today.

## Files touched

| File | Change |
|---|---|
| `infrastructure/gnucash/kvp.py` | `get_book_string_option` — read a Business option from the live book via `qof_book_get_string_option` (the inverse of `set_book_string_option`; works on 3.8–5.x). |
| `services/plaintext_parser.py` | `DirectiveType.COMPANY` + `parse_company_head`; the `company` header block whose `key: value` children accumulate as metadata. |
| `services/gnucash_importer.py` | `import_company` writes each field to its Business slot via `set_book_string_option`; dispatched first in `import_business_objects`; `company` added to the per-type counts. |
| `cli/import_cmd.py` | `COMPANY` joins the early import pass; `Company` row in the business-objects summary. |
| `use_cases/export_business_objects.py` | `_export_company` emits the `company` directive (first section) from the book's Business options. |
| `services/invoice_renderer.py` | `read_book_company_info` returns `contact`/`gst`/`pst`/`fax`; shared `build_company_xml` emits `<contact>`/`<gst>`/`<pst>`/`<fax>` (one `<pst>` per number); `_render_seller_header` renders the GST/PST/contact/fax segments; `split_pst_numbers` helper. |
| `services/bill_renderer.py` | Reuses `build_company_xml` for the seller block. |
| `services/invoice.xslt`, `services/bill.xslt` | Render Contact / GST / each PST / Fax rows in the company block. |
| `README.md` | Document the `company` directive and the `gst`/`pst` keys. |

## Tests

`tests/integration/test_company_info_roundtrip.py` (fixture `tests/fixtures/company_full.txt`):

- **Round-trip** (the missing coverage): import the `company` directive → export → import into a fresh book → export again; the `company` block (every native field plus GST and both PST numbers) is byte-for-byte identical. This is the Company ID round-trip test that did not previously exist.
- **Field fidelity**: every field exports with its exact value after import.
- **Render**: `print-invoice` / `print-bill` in plaintext and HTML show the GST value and *each* PST number in the seller block.
- **Baseline**: a book with no company options exports no `company` block.
- All passing on GnuCash 3.8 and 5.10.

## Related issues

- **Q-019** — two-sided rendering + the original `read_book_company_info` / seller-header mechanism this extends.
- **Q-002** — `read_book_company_info` bypasses the repository layer (pre-existing; unchanged here).

---

**Created**: 2026-06-08
