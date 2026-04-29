---
id: F-004
title: No search / find-transaction command
category: feature
severity: enhancement
status: open
---

## Problem

Finding a specific transaction currently requires:
1. Exporting the entire book to plaintext
2. Grepping the output

For large books this is slow and produces a lot of noise. A dedicated search
command would be more ergonomic for day-to-day use.

## Proposed behaviour

```bash
# Find by description (substring, case-insensitive)
gnucash-plaintext find mybook.gnucash --description "grocery"

# Find by amount (exact or range)
gnucash-plaintext find mybook.gnucash --amount 42.50
gnucash-plaintext find mybook.gnucash --min-amount 100 --max-amount 500

# Find by account name (substring)
gnucash-plaintext find mybook.gnucash --account "Expenses:Food"

# Find by date range
gnucash-plaintext find mybook.gnucash --from 2024-01-01 --to 2024-03-31

# Combine filters
gnucash-plaintext find mybook.gnucash --account "Expenses" --from 2024-01-01

# Output format: default is plaintext ledger format (same as export)
gnucash-plaintext find mybook.gnucash --description "grocery" -o results.txt
```

## Implementation notes

- Reuses `repositories/gnucash_repository.py` for book access
- Uses GnuCash's `Query` API with `search_for('Split')` to push filtering
  into the engine rather than loading all transactions and filtering in Python
- Output format is identical to `export` so results can be re-imported or
  diffed

## Priority

Nice-to-have. A workaround exists (export + grep). Implement after F-002 and
F-003 which have broader value.
