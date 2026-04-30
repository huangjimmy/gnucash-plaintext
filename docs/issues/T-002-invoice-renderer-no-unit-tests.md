---
id: T-002
title: invoice_renderer.py has no unit tests
category: tests
severity: medium
status: closed
---

## Problem

`services/invoice_renderer.py` contains two non-trivial functions —
`read_book_company_info()` and `invoice_to_xml()` — that are not covered by any
unit tests. The XML extraction logic in `read_book_company_info` parses raw
`.gnucash` XML using namespace-aware element lookups; a regression here would
silently produce empty company info on PDFs without any test catching it.

## Missing test cases

- `read_book_company_info` with a gzip-compressed `.gnucash` file
- `read_book_company_info` with an uncompressed `.gnucash` file
- `read_book_company_info` when company slots are absent → should return `None`/empty dict
- `invoice_to_xml` with a fully populated invoice (entries, tax, payment)
- `invoice_to_xml` with a minimal invoice (no entries)

## Affected files

- `services/invoice_renderer.py`

## Suggested fix

Add `tests/unit/services/test_invoice_renderer.py`. The functions only need a
small XML string fixture — no real GnuCash session required for
`read_book_company_info`. For `invoice_to_xml`, mock or create a minimal
`gnucash.gnucash_business.Invoice` object.
