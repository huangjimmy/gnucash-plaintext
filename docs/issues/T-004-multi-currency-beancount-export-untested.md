---
id: T-004
title: Multi-currency beancount export has no integration test
category: tests
severity: medium
status: open
---

## Problem

The beancount exporter emits `price` directives for foreign-currency splits, but
there is no integration test that exercises a book containing more than one
currency. This is the most common real-world use case for the project owner
(CAD/HKD/CNY/JPY/USD book) yet it has never been verified end-to-end.

Potential failure modes that are currently invisible:
- Price directive emitted with wrong base/quote currency order
- Missing or duplicate `price` directives for the same FX pair
- Beancount rejects the output because commodity declarations are missing

## Missing test cases

- Book with two currencies (e.g. CAD and USD) → export-beancount → verify price
  directives appear and beancount can parse the output
- Transfer between a CAD account and a USD account with an explicit exchange rate
- Split whose amount and value are in different commodities

## Affected files

- `services/beancount_converter.py`
- `tests/integration/test_beancount_roundtrip.py`

## Suggested fix

Add a `multi_currency_gnucash_file` fixture in `conftest.py` that creates a book
with two commodities and at least one cross-currency transaction. Add a test in
`test_beancount_roundtrip.py` (or a new `test_cli_export_beancount.py`) that
exports it and validates the output with beancount's own parser if available,
or at minimum checks the price directive format with a regex.
