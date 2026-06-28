---
id: Q-032
title: Income statement breaks once books are closed; no balance sheet; no combined report
category: feature
severity: high
status: reopened
---

## Problem

Three interlocking gaps around financial statements, surfaced together:

1. **The income statement breaks the moment you close the books.** `close-books` created a closing transaction with only a `"Closing entry (…)"` description — it never set GnuCash's `xaccTransSetIsClosingTxn` flag. And `income-statement` summed *every* split in the period. So after closing (the closing entry zeroes Income/Expense on the fiscal-year-end date, inside the period), the income statement included those closing entries and reported ~0. The statement was only correct *before* closing.

2. **The closing flag didn't round-trip plaintext.** Even once set, the flag persisted to the native `.gnucash` XML but the plaintext exporter/importer ignored it — so an `export → import` silently un-closed the books, re-breaking the income statement.

3. **No balance sheet (F-002), and no way to get both statements at once.** T2/GIFI prep needs the income statement *and* the balance sheet as of the same period, but there was no balance-sheet command and no combined run — meaning N command runs and N (expensive) book opens.

## Fix

Closing entries are now first-class, the income statement excludes them, the flag round-trips, and there's a `balance-sheet` command plus a `report` runner.

### Closing entries are first-class
- `close-books` sets `xaccTransSetIsClosingTxn(tx, True)` on each closing transaction (persists to XML). `is_closing_txn(tx)` recognises a closing entry by the **flag** (authoritative) or the legacy description, so `--force`/`--status` also find GUI-created closings.
- `income-statement` excludes splits whose transaction `is_closing_txn` — so it reports the true period result whether the books are closed, not closed, or stale-closed.
- The closing flag round-trips plaintext: the exporter emits `closing: #True` on closing transactions, the importer re-applies it via `xaccTransSetIsClosingTxn` (`closing` is now a known tx key). A roundtrip no longer un-closes the books.

### Balance sheet (F-002)
- `balance-sheet <book> --as-of DATE [--fx-rates] [--output]` — Assets / Liabilities / Equity as of the date, with a computed **Current Year Earnings** line so it balances whether or not the books are closed. It always balances by the fundamental identity (every split nets to zero ⇒ Assets = Liabilities + Equity + net income); closing just moves the net income from the earnings line into Equity (Retained Earnings).
- It reuses the income statement's section renderer, so the two statements look identical (indented account tree, subtotals).

### Combined report
- `report <book> income-statement balance-sheet [--fiscal-year-end | --start --end] [--as-of] [--fx-rates] [--output]` — you **name** the statements explicitly (no opaque bundle; `report` is GnuCash's own term), and they run against **one** read-only book open, output combined. The income statement covers the period; the balance sheet is as of the period end. Read-only — no save/history/versioning (unlike `migrate`).

## Files touched

| File | Change |
|---|---|
| `services/book_closer.py` | Set the closing flag on creation; `is_closing_txn`; find closings by flag. |
| `services/income_statement.py` | Exclude closing splits from period balances. |
| `infrastructure/gnucash/kvp.py` | `closing` is a known tx metadata key. |
| `use_cases/export_transactions.py` | Emit `closing: #True` on closing transactions. |
| `services/gnucash_importer.py` | Re-apply the closing flag on import. |
| `services/balance_sheet.py`, `services/balance_sheet_renderer.py`, `cli/balance_sheet_cmd.py` | New balance-sheet (F-002), reusing the income statement section renderer. |
| `cli/report_cmd.py`, `cli/main.py` | New `report` runner; register `balance-sheet` + `report`. |
| `README.md` | Document closing-entry handling, `balance-sheet`, `report`. |

## Tests

`tests/integration/test_closing_entries.py`: income statement is **byte-identical before and after close**; `close-books` sets the flag (real activity isn't flagged); the flag **survives a plaintext roundtrip** (asserted via `xaccTransGetIsClosingTxn`, not just the description); `--force` re-close finds the prior closing by flag. `tests/integration/test_reports.py`: the balance sheet **balances before and after close** (Current Year Earnings pre-close, Retained Earnings post-close); `report` runs both statements in one invocation; an unknown statement is rejected. Existing income-statement (21) and close-books (70) suites still pass. Passing on GnuCash 3.8 and 5.10.

## Related issues

- **F-002** — "No balance-sheet command" — closed by the `balance-sheet` command here.

---

## Reopened: balance sheet disagreed with `account-balance`

A user reported the balance sheet disagreeing with the figures they had read from `account-balance` before closing, and showing **NOT BALANCED**.

### Cause

The balance sheet classified accounts by matching only the bare `ACCT_TYPE_ASSET` and `ACCT_TYPE_LIABILITY`. GnuCash has many concrete asset and liability types — Bank, Cash, Stock, Mutual Fund, A/Receivable on the asset side; Credit Card, A/Payable on the liability side (plus the deprecated Checking/Savings/MoneyMrkt/CreditLine/Currency codes still found in long-lived books). Any account of those types fell through to the `else` branch and was **silently dropped**, so a real book showed near-empty Assets/Liabilities and failed to balance, while `account-balance` (which reads raw balances of every account) reported the correct figures. The original `report`/`balance-sheet` tests passed only because their fixture used the bare `Asset` type.

### Fix

`services/balance_sheet.py` now classifies against comprehensive `_ASSET_TYPES` / `_LIABILITY_TYPES` sets covering every asset-like and liability-like type, including A/Receivable and A/Payable. The deprecated codes are resolved with a defensive `getattr` lookup (`_type_set`) so the module loads on every binding (3.8–5.x) whether or not it exports a given legacy symbol.

Account balances are bucketed by the currency each split's **value** is denominated in (the transaction currency, what `xaccSplitGetValue` returns), not by the account's own commodity. For a security (Stock / Mutual Fund) account that puts the cost in the report currency (e.g. CAD) instead of mislabelling it under the ticker, so a securities book balances.

### Securities valuation: cost by default, market with `--prices`

A commodity account defaults to **cost basis**. Passing `--prices PRICES.yaml` (same shape as `--fx-rates`: one `MNEMONIC: price` per security) values each holding at **shares × price**. The price is read in the currency the holding was bought in (CAD stock → CAD price, USD stock → USD price), and `--fx-rates` converts a foreign holding's market value to CAD; pricing a foreign holding with no matching FX rate stops with an actionable error rather than mis-valuing it. The revaluation (market − cost) isn't booked anywhere, so a single **Unrealized Gains** equity line absorbs it — exactly as GnuCash's own market-value balance sheet does — keeping `Assets = Liabilities + Equity`. Unpriced securities stay at cost. The option lives on `balance-sheet` and `report` and reuses the `FxRates` loader.

### Pre-commit AI review timeout

A real review of a substantial diff reads the touched sources and takes ~4 minutes; the old 150s cap in `scripts/review-commit.sh` made the gate silently skip on every non-trivial commit. Raised to 300s (and the tip text to 5 minutes).

### Tests

- `tests/unit/services/test_balance_sheet_classification.py` — enumerates **every** `ACCT_TYPE_*` posting constant the running binding exposes and asserts each lands in exactly one balance-sheet bucket; a new GnuCash type would fail this loudly instead of being dropped. Spot-checks the asset family (Bank/Cash/Stock/Mutual/Receivable), the liability family (Credit Card/Payable), the A/Receivable↔A/Payable non-collision, and the legacy codes.
- `tests/integration/test_balance_sheet_account_types.py` — the balance sheet's Asset/Liability totals equal the `account-balance` numbers and the accounting equation holds; Retained Earnings grow across two closed years by exactly each year's profit (600 → 1000); a book using every importable account type (incl. Stock & Mutual Fund at cost) balances with no account dropped; `--prices` marks securities to market with an Unrealized Gains line that still balances (on both `balance-sheet` and `report`); a USD-listed holding is priced in USD and converted to CAD via `--fx-rates`, while pricing it with no FX rate raises a clear error; the user's multi-currency repro now balances with its Bank accounts present.
- Fixtures: `tests/fixtures/all_account_types_book.txt`, `tests/fixtures/balance_sheet_book.txt`, `tests/fixtures/balance_sheet_bug_repro.txt`, `tests/fixtures/foreign_security_book.txt`, `tests/fixtures/security_prices.yaml`, `tests/fixtures/foreign_security_prices.yaml`, `tests/fixtures/usd_cad_rates.yaml`. Passing on GnuCash 3.8 and 5.10.

---

**Created**: 2026-06-28
