---
id: F-002
title: No balance-sheet command
category: feature
severity: enhancement
status: open
---

## Problem

The tool has an `income-statement` command that reports Revenue and Expenses
for a period, but has no `balance-sheet` command that reports Assets,
Liabilities, and Equity as of a given date. For a complete picture of financial
health, both reports are needed.

All the required data already flows through `use_cases/account_balance.py` and
`services/income_statement.py`. A balance sheet is essentially a filtered,
structured account balance report grouped by account type.

## Proposed behaviour

```bash
gnucash-plaintext balance-sheet mybook.gnucash --as-of 2024-12-31
gnucash-plaintext balance-sheet mybook.gnucash --as-of 2024-12-31 --currency CAD
gnucash-plaintext balance-sheet mybook.gnucash --as-of 2024-12-31 -o report.html
```

Output format mirrors `income-statement`: terminal table by default, HTML with
`-o *.html`.

## Implementation sketch

1. New `use_cases/generate_balance_sheet.py` — queries account balances for all
   Asset, Liability, and Equity accounts as of `--as-of` date; groups and totals
2. New `services/balance_sheet_renderer.py` — reuses Jinja2 template pattern
   from `income_statement_renderer.py`
3. New `cli/balance_sheet_cmd.py` registered as `balance-sheet`

The accounting identity (Assets = Liabilities + Equity) provides a built-in
correctness check — if the equation does not balance, emit a warning.

## Related

- `use_cases/account_balance.py`
- `services/income_statement.py`
- `services/income_statement_renderer.py`
- `cli/income_statement_cmd.py`
