---
id: F-009
title: "Statement import: ReadyToImportWriter and end-to-end pipeline test"
category: feature
severity: high
status: open
branch: feature/statement-import-pipeline
depends_on: F-008
---

## What to build

`services/ready_to_import_writer.py` — takes the four buckets produced by
`GnuCashFuzzyMatcher` + `ReconcilePreviewReader` and writes `ready-to-import.txt`.

**Interface:**
```python
class ReadyToImportWriter:
    DOC_LINK_BASE: str = "bank_statements"

    def write(
        self,
        path: str,
        new: list[StandardTransaction],
        likely_dup: list[MatchResult],
        partial_match: list[MatchResult],
        unresolved: list[StandardTransaction],
    ) -> None: ...
```

**Output rules:**
- `new`: written as live importable blocks under `===== NEW =====`
- `likely_dup`: fully commented under `===== LIKELY DUPLICATE =====`
- `partial_match`: EXISTING + GENERATED commented, SUGGESTED MERGE live
  (with `guid` from `merged_tx`) under `===== PARTIAL MATCH =====`
- `unresolved`: fully commented with `[UNRESOLVED — DO NOT IMPORT]` header
- **Safety invariant**: no live block anywhere contains `Reconcile:Autopay`

## Unit tests

`tests/unit/services/test_ready_to_import_writer.py`:

| Test | Scenario | Expected |
|---|---|---|
| `test_new_section_live_block` | one NEW tx | uncommented date line in output |
| `test_likely_dup_fully_commented` | one LIKELY_DUP | every line starts with `;;` |
| `test_partial_match_structure` | one PARTIAL_MATCH | EXISTING commented, GENERATED commented, SUGGESTED MERGE live |
| `test_partial_match_guid_in_merge` | PARTIAL_MATCH with guid | `guid:` line in live merge block |
| `test_partial_match_gnucash_category` | PARTIAL_MATCH | live block has GnuCash expense account |
| `test_partial_match_generated_doc_link` | PARTIAL_MATCH | live block has generated doc_link |
| `test_unresolved_do_not_import` | one UNRESOLVED | `[UNRESOLVED — DO NOT IMPORT]` in output |
| `test_unresolved_fully_commented` | one UNRESOLVED | every line starts with `;;` |
| `test_no_live_reconcile_autopay` | mix of all buckets | no live line contains `Reconcile:Autopay` |
| `test_doc_link_prefix` | NEW tx | `doc_link: "bank_statements/..."` |
| `test_cjk_in_output` | tx with `"自動轉賬"` | CJK preserved in written file |
| `test_empty_all_buckets` | all empty | valid file with empty sections, no error |

## Integration tests

`tests/integration/services/test_ready_to_import_writer.py`:

- **NEW section parseable**: take written NEW section, feed into existing
  `PlaintextParser` — parses without error, produces expected tx count
- **End-to-end pipeline**: hardcoded `StandardTransaction` list →
  `StatementReconciler` → `ReconcilePreviewWriter` → `ReconcilePreviewReader`
  → `GnuCashFuzzyMatcher` (temp book) → `ReadyToImportWriter` →
  `ImportTransactionsUseCase` → verify transactions appear in GnuCash book
- **Idempotency**: run the full pipeline twice on the same inputs → second run
  produces no duplicates in GnuCash (`TransactionMatcher` catches them)
- **PARTIAL_MATCH import updates not inserts**: re-import a SUGGESTED MERGE
  block that has a `guid` → existing GnuCash tx updated, not duplicated

## Acceptance

End-to-end integration test passes: a set of hardcoded `StandardTransaction`
objects flows through the full pipeline and lands correctly in a real GnuCash
book, with no duplicates on re-run and no `Reconcile:Autopay` account written
to the book at any point.

## Files

- `services/ready_to_import_writer.py` (new)
- `tests/unit/services/test_ready_to_import_writer.py` (new)
- `tests/integration/services/test_ready_to_import_writer.py` (new)
