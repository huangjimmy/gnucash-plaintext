# Income Statement Feature — Design Note

**Feature branch**: `feature/income-statement`
**Created**: 2026-03-18
**Status**: Approved, implementation pending

---

## Overview

Generate an income statement (profit & loss report) from a GnuCash file, suitable for
CRA (Canada Revenue Agency) T2 corporate income tax filing.

New CLI command: `gnucash-plaintext income-statement`

---

## Design Decisions

### 1. Date Range Input

Support two modes, both accepted in the same command:

**Explicit range** (always works, maximum control):
```bash
gnucash-plaintext income-statement ledger.gnucash \
    --start 2023-04-01 --end 2024-03-31
```

**Fiscal-year-end shorthand** (auto-computes start as `end − 1 year + 1 day`):
```bash
gnucash-plaintext income-statement ledger.gnucash \
    --fiscal-year-end 2024-03-31
# → start = 2023-04-01, end = 2024-03-31
```

The shorthand works for any fiscal year, not just calendar year (Jan–Dec).
CRA allows fiscal year ending on any date.

If both `--start/--end` and `--fiscal-year-end` are given, raise an error.

### 2. Multi-Currency and FX Rates

T2 requires all amounts reported in CAD. The report provides:

1. **Per-currency breakdown** — income and expenses in native currency
2. **CAD total** — all amounts converted to CAD using user-supplied annual average rates

FX rates are supplied via `--fx-rates rates.yaml`:

```yaml
# Annual average exchange rates → CAD
# Source: Bank of Canada (https://www.bankofcanada.ca/rates/exchange/)
HKD: 0.172
CNY: 0.185
JPY: 0.0090
USD: 1.36
CAD: 1.0   # always 1.0
```

- CAD is always 1.0 and need not be listed (assumed if absent)
- CRA accepts Bank of Canada annual average rates for foreign currency conversion
- If `--fx-rates` is omitted, the report is generated **per-currency only** with no CAD
  total (and a warning that T2 filing requires FX conversion)
- If a currency in the ledger has no rate in the file, the command fails with a clear error
  listing which currencies are missing

### 3. Output Formats

Controlled by `--output-format` (default: `text`):

| Flag | Output |
|------|--------|
| `text` | Plain text to stdout (or `--output file.txt`) |
| `html` | HTML file (requires `--output file.html`) |
| `pdf`  | PDF file via WeasyPrint (requires `--output file.pdf`) |

Examples:
```bash
# Plain text to stdout
gnucash-plaintext income-statement ledger.gnucash --fiscal-year-end 2024-12-31

# HTML report
gnucash-plaintext income-statement ledger.gnucash \
    --fiscal-year-end 2024-12-31 \
    --fx-rates rates.yaml \
    --output-format html --output report.html

# PDF report
gnucash-plaintext income-statement ledger.gnucash \
    --fiscal-year-end 2024-12-31 \
    --fx-rates rates.yaml \
    --output-format pdf --output report.pdf
```

### 4. Account Hierarchy Depth

Show the **full account tree with subtotals at every level**.

Rationale: T2 Schedule 125 requires correct categorization of each expense
(advertising, meals & entertainment, professional fees, etc.). Collapsing the tree
risks misclassifying expenses. The full hierarchy lets the user map GnuCash
categories to T2 lines accurately.

Example layout:
```
INCOME
  Income:Salary                        12,000.00 CAD
  Income:Other Income
    Income:Other Income:Cashback           150.00 CAD
    Income:Other Income:PC Points           60.00 CAD
    Subtotal: Other Income                 210.00 CAD
  Total Income                         12,210.00 CAD

EXPENSES
  Expenses-CAN:Dining                    1,200.00 CAD
  Expenses-CAN:Groceries                 3,400.00 CAD
  Expenses-HK:Transport                  1,050.00 HKD     180.60 CAD
  ...
  Total Expenses                                        4,780.60 CAD

NET INCOME                                             7,429.40 CAD
```

### 5. Relationship to Close Books

The income statement **does not require books to be closed**. It computes
income and expense account balances directly from raw transactions within the
date range. The `close-books` command is a separate operation.

### 6. CRA Account Structure

No artificial remapping of accounts to CRA line numbers. The report follows
the user's existing GnuCash account hierarchy, which the user has already
structured to match their CRA categories. The user maps accounts to T2 lines
manually when filing.

---

## Implementation Plan

### New files

| File | Purpose |
|------|---------|
| `services/income_statement.py` | Core service: compute balances per account per currency, apply FX |
| `use_cases/generate_income_statement.py` | Orchestration: open file, call service, render output |
| `cli/income_statement_cmd.py` | CLI command with all options |
| `services/fx_rates.py` | Load and validate FX rates YAML, convert amounts |
| `templates/income_statement.html` | Jinja2 HTML template (also used for PDF via WeasyPrint) |
| `tests/unit/services/test_income_statement.py` | Unit tests for service |
| `tests/integration/test_cli_income_statement.py` | Integration tests |

### Register in `cli/main.py`

```python
from cli.income_statement_cmd import income_statement
cli.add_command(income_statement, name='income-statement')
```

### Reuse existing infrastructure

- `BookCloser.get_balance_as_of_date()` — reuse to compute balances within a date range
  (adapt to filter by start date as well as end date)
- `GnuCashRepository` — open file, get root account, iterate accounts
- `infrastructure/gnucash/utils.find_account()` — account lookup
- WeasyPrint (already in Docker image from `print-invoice` command) — PDF rendering

---

## Open Questions

- **Comparison column**: Should the report optionally show prior-year figures side by side?
  (Deferred — not needed for initial implementation)
- **Partial-year FX**: If a transaction is in a year with a different rate, should we
  support per-year rates? (Deferred — single rate per currency per report is sufficient for now)
