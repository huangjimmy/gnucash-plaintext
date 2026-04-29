---
id: Q-002
title: read_book_company_info bypasses the repository layer
category: quality
severity: low
status: open
---

## Problem

`services/invoice_renderer.py:read_book_company_info()` parses the raw
`.gnucash` XML file directly using `xml.etree.ElementTree`, bypassing
`GnuCashRepository` entirely. This creates two separate parsing paths for the
same file:

1. `GnuCashRepository.open()` → GnuCash Python bindings → in-memory book
2. `read_book_company_info()` → raw XML parse → dict

Consequences:

- The function is called while the GnuCash session already holds the file
  open (`invoice_print_cmd.py:43`). On most systems this works, but it is
  fragile — particularly on Windows where file locking is stricter.
- If GnuCash ever changes its internal XML schema or KVP storage format, both
  paths must be updated independently.
- The namespace strings (`{http://www.gnucash.org/XML/slot}key`, etc.) are
  hardcoded in the service rather than centralised.

## Suggested fix

Read company info through the already-open `book` object that is available in
`invoice_print_cmd.py`. GnuCash stores book-level KVP slots (including company
name, address, etc.) accessible via the book's slot API. This would eliminate
the second XML parse entirely.

If the SWIG bindings do not expose book-level slots cleanly, use the existing
`infrastructure/gnucash/kvp.py` helper functions which already handle the
ctypes fallback path.

## Affected files

- `services/invoice_renderer.py` (`read_book_company_info`)
- `cli/invoice_print_cmd.py`
