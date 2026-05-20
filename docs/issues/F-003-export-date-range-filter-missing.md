---
id: F-003
title: export command has no date-range filter
category: feature
severity: enhancement
status: closed
---

## Problem

`gnucash-plaintext export` emits all transactions in the book. For a book
spanning many years this produces a very large output file. The most common
need — exporting a single fiscal year for review or hand-off to an accountant
— requires post-processing the output with an external tool.

## Proposed behaviour

```bash
# Export a single fiscal year
gnucash-plaintext export mybook.gnucash ledger.txt --from 2024-01-01 --to 2024-12-31

# Export everything from a date onwards
gnucash-plaintext export mybook.gnucash ledger.txt --from 2024-01-01

# Existing behaviour (no flags = all transactions) remains unchanged
gnucash-plaintext export mybook.gnucash ledger.txt
```

## Implementation notes

- `--from` and `--to` accept `YYYY-MM-DD` strings; `click.DateTime` handles
  parsing
- Filter is applied inside `use_cases/export_transactions.py` before iterating
  splits, not by post-filtering the output string
- Both flags are optional and independent (only `--from`, only `--to`, or both)
- Account `open` directives and `commodity` declarations are always emitted
  regardless of the date filter (they are not transactions)

## Affected files

- `cli/export_cmd.py`
- `use_cases/export_transactions.py`
