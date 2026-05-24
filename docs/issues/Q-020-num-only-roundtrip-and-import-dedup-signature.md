---
id: Q-020
title: "Num-only roundtrip silently relabels Num as Description, and `import_from_file` dedup ignores `doc_link` / `tx_num` / `owner`"
category: quality
severity: high
status: open
---

## Two coupled bugs on the import/dedup path

**1. `gnucash-plaintext import` skips genuine transactions on the duplicate scan.** The CLI funnels every plaintext file through `ImportTransactionsUseCase.import_from_file()` (`cli/import_cmd.py:196`). That method's inline duplicate scan at `use_cases/import_transactions.py:333-348` builds a 2-tuple `(date, set-of-accounts)` and ignores everything else — including `doc_link`. The matcher in `services/transaction_matcher.py:106-137` documents a 3-tuple contract `(date, sorted_accounts, doc_link)` and explicitly warns that dropping `doc_link` causes "false positives: a second legitimate same-day transaction would be silently dropped as a duplicate of the first". The contract has been live in the matcher but unreachable from the actual import CLI since PR #5 landed in March 2026. Same-day same-account transactions with different `tx_num` (check numbers, statement refs, payee tags) or different `owner` (vendor/customer reference set by the business module on invoice/bill postings) are similarly false-positive-dropped.

**2. Round-trip of a transaction with Num set but Description empty silently relabels Num as Description.** `use_cases/export_transactions.py:469-473` only emits the description slot when `tx_desc` is non-empty:

```python
line = f'{date_str} *'
if tx_num and tx_num.strip() != "":
    line += f' {encode_value_as_string(tx_num)}'
if tx_desc and tx_desc.strip() != "":
    line += f' {encode_value_as_string(tx_desc)}'
```

For `tx_num="CHK-001"`, `tx_desc=""` this writes `2024-01-15 * "CHK-001"` (one quoted string after `*`). The parser at `services/plaintext_parser.py:466-487` interprets a single quoted string after `*` as the description, not the Num:

```python
if second_str is None:
    return date, None, decode_value_from_string(first_str)   # ← desc
```

Round-trip result: `tx_num=""`, `tx_desc="CHK-001"`. Num is silently relabeled as Description.

This bug is **not** detectable by a plaintext-only round-trip check (`export → parse → compare directive props`), because the parsed directive's props faithfully reflect what the plaintext file says — and the plaintext file just has one quoted string in the wrong slot. The bug is only visible when you introspect the re-imported GnuCash transaction directly: `transaction.GetNum()` returns `""` (was `"CHK-001"`) and `transaction.GetDescription()` returns `"CHK-001"` (was `""`).

## Resolution

### Exporter: emit the description slot when Num is set, even if Description is empty

```python
line = f'{date_str} *'
if tx_num and tx_num.strip() != "":
    line += f' {encode_value_as_string(tx_num)}'
    line += f' {encode_value_as_string(tx_desc or "")}'
elif tx_desc and tx_desc.strip() != "":
    line += f' {encode_value_as_string(tx_desc)}'
```

When Num is set, the exporter always writes two quoted strings; the second is `""` when Description is empty. The existing parser already accepts this form (`transaction_pattern2` matches the empty quoted string `""`, returns `tx_num=first, tx_desc=second`) — no parser change needed. The minimal lines `2024-01-15 *`, `2024-01-15 * "Desc"`, and `2024-01-15 * "Num" "Desc"` continue to render identically.

### Matcher: expand the signature to `(date, accounts, doc_link, tx_num, owner)`

`TransactionMatcher.get_signature` is extended from a 3-tuple to a 5-tuple. `get_signature_for_plaintext`, `has_duplicate_signature`, `find_duplicates`, and `get_duplicate_count` accept and pass through the two new fields. All three discriminators (`doc_link`, `tx_num`, `owner`) meet the same criteria the matcher's docstring already requires — explicit, user-set or business-module-set, faithfully round-tripped:

- `doc_link` — explicit author-set link to a receipt or external document. Round-tripped via `SetDocLink`/`GetDocLink`.
- `tx_num` — free-text `Transaction.GetNum()`. Users may store check numbers, statement refs, payee tags, workflow codes — GnuCash itself doesn't prescribe semantics.
- `owner` — `vendor:V001` / `customer:C001`. Set by GnuCash's business module on invoice/bill posting transactions and payments; round-tripped via the `owner:` metadata line. The matcher reads it via `gncOwnerGetOwnerFromTxn` (C-level), with a custom-KVP slot fallback for plaintext-roundtripped transactions (which carry owner in KVP because `gncOwnerCopyOnTxn` is a no-op from Python in GnuCash 5.x — see `infrastructure/gnucash/kvp.py:38-46`).

Empty-equivalent values are normalised to `None` in the signature: `tx_num=""` and `tx_num=None` are treated as equivalent (`GetNum()` returns `""` for unset; the plaintext bookkeeping varies). Same for `doc_link` and `owner`.

### `import_from_file` routes through the matcher

The inline duplicate scan at `use_cases/import_transactions.py:333-348` is deleted. The replacement reads `doc_link`, `tx_num`, and `owner` from the parsed directive and delegates to `self.matcher.has_duplicate_signature(...)`. There is now exactly one duplicate-detection seam in the use case.

The GUID-match branch (lines 316-331) and the `ResolutionStrategy.UPDATE` branch (which returns early at line 310) are untouched.

## Why this went unnoticed

`ImportTransactionsUseCase` has two duplicate-detection codepaths and only one of them goes through `TransactionMatcher`:

| Method | How it dedups | Called from |
|---|---|---|
| `execute(plaintext_transactions: List[Dict], …)` | `self.matcher.find_duplicates(...)` | only `tests/unit/use_cases/test_import_transactions.py` |
| `import_from_file(input_path, …)` | inline `(date, set-of-accounts)` loop | every CLI invocation via `cli/import_cmd.py:196` |

PR #5 upgraded `TransactionMatcher.get_signature` to include `doc_link` and added unit tests for the matcher and for `execute()`. The inline implementation in `import_from_file` was missed. Since the inline scan is the only path the CLI actually walks, the matcher's `doc_link` awareness has been unreachable from `gnucash-plaintext import` since that day.

The Num/Description round-trip bug went unnoticed because every existing fixture and test transaction populates both fields together — and a plaintext-only round-trip check passes (the plaintext file just has the data in the wrong slot, which the parser is consistent about). Detection requires introspecting `GetNum()` and `GetDescription()` on the re-imported GnuCash transaction.

## Tests

`tests/integration/test_q020_num_only_roundtrip.py` — the regression test the user called out by name. The test:

1. Opens a fresh GnuCash file, creates a transaction with `Num="CHK-001"`, `Description=""`, and two splits.
2. Exports the book to plaintext via `ExportTransactionsUseCase.execute()`.
3. Imports the plaintext into a second fresh GnuCash file via `ImportTransactionsUseCase.import_from_file()`.
4. Introspects the re-imported transaction directly: asserts `GetNum() == "CHK-001"` and `GetDescription() == ""`.

This is the test shape the bug demands — a plaintext-only diff check would have passed even with the bug present.

`tests/unit/services/test_transaction_matcher_signature.py` — matcher coverage for the new 5-tuple:

- Different `doc_link` → not duplicate (preserved from existing behaviour).
- Different `tx_num` → not duplicate (new).
- Different `owner` → not duplicate (new).
- All three same → duplicate.
- `tx_num=None` ≡ `tx_num=""` in the signature (post-import re-import scenario where GnuCash stores `""` for unset).
- `owner=None` ≡ no `owner:` line in plaintext.

`tests/integration/test_q020_import_dedup.py` — CLI regression driving `import_transactions` through `CliRunner`:

1. Import a fixture transaction (2024-02-15, `Expenses:Groceries` + `Assets:Bank:Checking`, `doc_link: receipts/trip1.txt`).
2. Re-import the same fixture → reports `Skipped: 1` (genuine duplicate).
3. Import a second fixture: same date, same accounts, **different `doc_link`** → reports `Transactions: 1` (not skipped). This is the case that the buggy inline scan was dropping.
4. Import a third fixture: same date, same accounts, same `doc_link`, **different `tx_num`** → reports `Transactions: 1`.

The test drives the CLI end-to-end so the wiring `cli/import_cmd.py → use_case.import_from_file → matcher` is exercised — exactly the wiring that hid the bug for two months.

Fixtures (`tests/fixtures/q020_*.txt`) follow the project convention of plaintext files on disk rather than inlined Python strings.

## Files touched

| File | Change |
|---|---|
| `use_cases/export_transactions.py` | When `tx_num` is set, always emit the description slot (with `""` if empty). |
| `services/transaction_matcher.py` | Extend signature from 3-tuple to 5-tuple `(date, accounts, doc_link, tx_num, owner)`. Add ctypes-based owner reader with KVP fallback. Normalise empty-equivalent values. Update module docstring. |
| `use_cases/import_transactions.py` | `import_from_file`: delete the inline `(date, set-of-accounts)` loop; route through `self.matcher.has_duplicate_signature(..., doc_link, tx_num, owner)`. Drop the now-unused `get_account_full_name` import. |
| `tests/integration/test_q020_num_only_roundtrip.py` | Regression: Num-only export → re-import → introspect `GetNum()`/`GetDescription()` directly. |
| `tests/unit/services/test_transaction_matcher_signature.py` | Matcher coverage for the new 5-tuple. |
| `tests/integration/test_q020_import_dedup.py` | CLI regression covering re-import (dup), different `doc_link`, different `tx_num`. |
| `tests/fixtures/q020_*.txt` | Plaintext fixtures for the dedup regression. |
| Existing `tests/unit/services/test_transaction_matcher*.py` | Updated for the new signature arity. |
| `docs/issues/README.md` | Add Q-020 row to Quality table. |

---

**Created**: 2026-05-23
