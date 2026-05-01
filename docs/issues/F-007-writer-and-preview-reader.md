---
id: F-007
title: "Statement import: ReconcilePreviewWriter and ReconcilePreviewReader"
category: feature
severity: high
status: open
branch: feature/statement-import-pipeline
depends_on: F-006
---

## What to build

`services/reconcile_preview_writer.py` — writes `_reconcile.txt` from the
three output buckets of `StatementReconciler`.

`services/reconcile_preview_reader.py` — reads `_reconcile.txt` back into
`(resolved, unresolved)` buckets for Phase 2. Does NOT use `PlaintextParser`.

**Writer interface:**
```python
class ReconcilePreviewWriter:
    DOC_LINK_BASE: str = "bank_statements"

    def write(
        self,
        path: str,
        resolved: list[StandardTransaction],
        unresolved: list[StandardTransaction],
        normal: list[StandardTransaction],
    ) -> None: ...
```

**Reader interface:**
```python
class ReconcilePreviewReader:
    def read(self, path: str) -> tuple[
        list[StandardTransaction],  # importable — no Reconcile:Autopay
                                    # (includes both resolved autopay and
                                    #  normal transactions — both feed into
                                    #  GnuCashFuzzyMatcher identically)
        list[StandardTransaction],  # unresolved — contain Reconcile:Autopay
    ]: ...
```

**`_reconcile.txt` format** (full annotated example in `docs/statement-import-pipeline.md`
Output Format section):
```
;; ===== RESOLVED =====
;; bochk-2026-04.pdf

2026-03-29 * "薪金入賬 / FPS/JUNTECH..."
	doc_link: "bank_statements/bochk-2026-04.pdf"
	currency.mnemonic: "HKD"
	Assets:...:BOC HKD Saving 18110.00 HKD
	Income:Salary:HKD -18110.00 HKD

;; For merged autopay transactions where source_pdfs has 2 entries:
;; doc_link uses source_pdfs[0] (card PDF); source_pdfs[1] (bank PDF)
;; is stored as a second metadata line:
;;   doc_link: "bank_statements/boci-0012-2026-04.pdf"
;;   doc_link_bank: "bank_statements/bochk-2026-04.pdf"

;; ===== UNRESOLVED =====

2026-04-02 * "自動轉賬 / BOC CREDIT CARD (INT"
	...
	Reconcile:Autopay 125.00 HKD
```

**Reader parsing contract:**
- All `;;` lines skipped (section headers are `;;` lines — also skipped)
- Transaction block: starts with date line `YYYY-MM-DD * "..."`, followed by
  tab-indented metadata and split lines, terminated by blank line
- Classification by account name only: any split account == `"Reconcile:Autopay"` → unresolved;
  all others (resolved autopay AND normal) → importable. The two are indistinguishable
  after serialization and both feed into GnuCashFuzzyMatcher identically.
- Section position has no effect on classification
- File written with UTF-8; read with UTF-8

## Unit tests

`tests/unit/services/test_reconcile_preview_reader.py`:

| Test | Scenario | Expected |
|---|---|---|
| `test_round_trip_resolved` | write resolved tx → read | same `StandardTransaction` in importable list |
| `test_round_trip_unresolved` | write unresolved tx → read | same tx in unresolved list |
| `test_section_position_irrelevant` | unresolved tx written under RESOLVED header | still in unresolved |
| `test_comment_lines_skipped` | `;;` header lines | not leaked into any tx field |
| `test_empty_file` | empty `_reconcile.txt` | returns `([], [])` |
| `test_normal_tx_in_importable` | write normal tx → read | tx in importable list, not dropped |
| `test_importable_never_contains_autopay` | mixed write | importable list has no `Reconcile:Autopay` |
| `test_doc_link_prefix` | write tx → read | `doc_link` contains `DOC_LINK_BASE` prefix |
| `test_cjk_preserved` | tx with `"自動轉賬"` description | description unchanged after round-trip |
| `test_three_splits_round_trip` | tx with 3 splits | all splits preserved |
| `test_guid_round_trip` | tx with `guid="abc123"` | guid preserved |

## Integration tests

`tests/integration/services/test_reconcile_preview_reader.py`:

- **Full pipeline round-trip**: `StatementReconciler.reconcile()` →
  `ReconcilePreviewWriter.write()` → `ReconcilePreviewReader.read()` →
  verify `len(importable) + len(unresolved)` equals total transactions written
  (no transaction silently dropped)
- **CJK UTF-8 on disk**: write file with CJK in Docker environment, read back —
  no encoding error, characters identical
- **Resolved section parseable**: take reader's resolved output, serialize to
  plaintext, feed into existing `PlaintextParser` — parses without error

## Acceptance

Round-trip test passes: `len(importable) + len(unresolved)` returned by the
reader equals the total transactions written. No transaction is silently
dropped. Importable list contains no `Reconcile:Autopay` account.

## Files

- `services/reconcile_preview_writer.py` (new)
- `services/reconcile_preview_reader.py` (new)
- `tests/unit/services/test_reconcile_preview_reader.py` (new)
- `tests/integration/services/test_reconcile_preview_reader.py` (new)
