---
id: Q-025
title: Editing a transaction by re-import is silently skipped as a "duplicate"
category: quality
severity: low
status: closed
---

## Problem

To edit a transaction in place you re-import it with its `guid:` under `--strategy update`. But under the **default** strategy (`skip`), a transaction whose `guid:` matches an existing one is skipped as a duplicate — and the import summary just says `Skipped: 1 (duplicates)`, with no indication that the incoming content actually *differed*. A user who edits a transaction's splits and re-imports (without knowing about `--strategy update`) sees "Nothing to import", their edit silently dropped, and concludes editing isn't supported.

## Fix

Hint only — no behaviour change. When the default strategy skips a GUID match, compare the incoming directive's splits to the existing transaction; if they differ, count it and print a hint after the summary:

```
  Note: 1 skipped transaction matched an existing GUID but had different
  content — looks like an edit. To apply such edits in place (preserving the
  GUID), re-run with --strategy update.
```

A plain re-import of unchanged transactions does **not** trigger the hint (the content is identical, so it really is a duplicate). The comparison is exact — each split's (account path, `Fraction(num, denom)` amount), never `to_double` — so an unchanged re-import never false-positives and an edited amount always does.

## Files touched

| File | Change |
|---|---|
| `use_cases/import_transactions.py` | `_guid_match_content_differs(child, existing_tx)`; the default-strategy GUID-match branch counts changed-content skips into `ImportResult.guid_changed_skips`. |
| `cli/import_cmd.py` | Emit the `--strategy update` hint to stderr when `guid_changed_skips > 0`. |
| `tests/integration/test_import_edit_hint.py` | Edited GUID match → hint + book unchanged; unchanged GUID match → skipped, no hint; `--strategy update` → edit applied. |

## Tests

On GnuCash 3.8 and 5.10, plus the existing dedup / import / roundtrip guardrails (which must keep skipping unchanged re-imports without the hint).

## Related issues

- **Q-020** — the duplicate-vs-conflict signature matcher; this adds the analogous content check to the GUID-match fast path, which previously skipped unconditionally.

---

**Created**: 2026-06-06
