---
id: T-001
title: print-invoice command has no dedicated test file
category: tests
severity: high
status: closed
---

## Problem

`cli/invoice_print_cmd.py` is the only CLI command without a dedicated integration test
file. Every other command has a corresponding `tests/integration/test_cli_<command>.py`.
The only coverage today is a single happy-path invocation in
`tests/integration/test_business_objects.py:174`.

## Missing test cases

- Invalid `--invoice-id` (non-existent ID) → expect `UsageError` / non-zero exit
- Unposted invoice → expect a clear error (GnuCash cannot print unposted invoices)
- Output directory does not exist → expect meaningful error, not a traceback
- `weasyprint` not installed → expect a clear dependency error, not `ImportError`
- Bill passed where an invoice is expected (different type)

## Affected files

- `cli/invoice_print_cmd.py`
- `services/invoice_renderer.py`

## Suggested fix

Create `tests/integration/test_cli_print_invoice.py` following the same pattern as
`test_cli_export.py`. Use the existing `gnucash_file` fixture from `conftest.py` and
build a posted invoice inside the fixture to exercise the happy path, then add
separate parametrised cases for all error scenarios above.
