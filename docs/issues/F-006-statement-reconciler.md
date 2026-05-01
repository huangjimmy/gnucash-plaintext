---
id: F-006
title: "Statement import: StatementReconciler"
category: feature
severity: high
status: open
branch: feature/statement-import-pipeline
depends_on: F-005
---

## What to build

`services/statement_reconciler.py` — `StatementReconciler` class.

Matches `Reconcile:Autopay` placeholder pairs across a mixed list of
`StandardTransaction` objects from different statement providers.

**Interface:**
```python
class StatementReconciler:
    def reconcile(
        self, transactions: list[StandardTransaction]
    ) -> tuple[
        list[StandardTransaction],  # resolved (autopay pairs merged)
        list[StandardTransaction],  # unresolved (Reconcile:Autopay still present)
        list[StandardTransaction],  # normal (no Reconcile:Autopay involvement)
    ]: ...
```

**Rules:**
- Bank side: `Reconcile:Autopay` split has positive amount
- Card side: `Reconcile:Autopay` split has negative amount
- Match requires: same currency, `abs(amount)` equal, date within ±1 day
- Merged tx: card-side date/description, `source_pdfs=[card_pdf, bank_pdf]`
- All collision cases (same-side or cross-side) → all involved entries unresolved
- Normal transactions: pass through unchanged

## Unit tests

`tests/unit/services/test_statement_reconciler.py` — inputs are hardcoded
`StandardTransaction` objects, no PDF files:

| Test | Scenario | Expected |
|---|---|---|
| `test_clean_match` | bank +247.10 HKD + card -247.10 HKD, same day | 1 resolved, 0 unresolved |
| `test_merged_card_wins` | clean match | description, date from card side |
| `test_merged_source_pdfs` | clean match | `source_pdfs == [card_pdf, bank_pdf]` |
| `test_date_plus_one` | bank day 14, card day 15 | resolved |
| `test_date_minus_one` | bank day 15, card day 14 | resolved |
| `test_date_plus_two` | bank day 13, card day 15 | both unresolved |
| `test_partial_run_bank_only` | bank entry, no card | unresolved |
| `test_partial_run_card_only` | card entry, no bank | unresolved |
| `test_same_side_collision` | two bank entries same amount ±1 day | both unresolved |
| `test_cross_side_collision` | one bank + two card entries same amount | all three unresolved |
| `test_currency_mismatch` | bank HKD + card CNY | both unresolved |
| `test_normal_passthrough` | tx without `Reconcile:Autopay` | in normal list unchanged |
| `test_mixed_batch` | 2 normal + 1 autopay pair + 1 unresolved | correct counts all 3 buckets |
| `test_cny_match` | bank CNY 312.99 + card CNY 312.99 | resolved with CNY currency |

## Integration tests

`tests/integration/services/test_statement_reconciler.py`:

- **Realistic month simulation**: 3 autopay pairs (BOCHK→BOCI-0012,
  BOCHK→BOCI-0113, BOCHK→AEON) + 5 normal transactions hardcoded as
  `StandardTransaction` objects → verify 3 resolved, 0 unresolved, 5 normal

## Acceptance

All unit tests pass. The realistic month simulation produces exactly 3 resolved
transactions with no `Reconcile:Autopay` in any resolved split.

## Files

- `services/statement_reconciler.py` (new)
- `tests/unit/services/test_statement_reconciler.py` (new)
- `tests/integration/services/test_statement_reconciler.py` (new)
