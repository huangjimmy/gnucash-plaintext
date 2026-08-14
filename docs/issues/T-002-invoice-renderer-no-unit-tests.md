---
id: T-002
title: invoice_renderer.py has no unit tests
category: tests
severity: medium
status: closed
---

> **Half of what this asked for no longer exists ([Q-036](Q-036-printed-documents-are-not-gnucashs-page.md)).**
> `invoice_to_xml` is deleted with the XSLT page it fed: a printed document is GnuCash's own Printable Invoice, and there is no XML in between to test. What remains of `invoice_renderer.py` — the plaintext render, the tax arithmetic, `read_book_company_info` — is still covered as described here, and the page itself is covered by the tests Q-036 lists, which read what it says rather than how it was built.

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
