---
id: F-008
title: "Statement import: GnuCashFuzzyMatcher"
category: feature
severity: high
status: closed
branch: feature/statement-import-pipeline
depends_on: F-007
---

## What to build

`services/gnucash_fuzzy_matcher.py`:
- `MatchStatus` enum: `NEW`, `LIKELY_DUP`, `PARTIAL_MATCH`
- `MatchResult` dataclass: `status`, `existing_tx: gnucash.Transaction | None`,
  `merged_tx: StandardTransaction | None`
- `GnuCashFuzzyMatcher` class

**Interface:**
```python
class GnuCashFuzzyMatcher:
    def __init__(self, repo: GnuCashRepository) -> None: ...
    def match(
        self, tx: StandardTransaction
    ) -> MatchResult: ...
```

**Algorithm (from design doc):**
- Amount normalization: `sum(s.amount for s in tx.splits if s.amount > 0)`
  (same rule on both candidate and GnuCash index sides).
  **Guard**: if normalized amount is `Decimal(0)` (all-negative or zero-amount
  splits — e.g. a full refund), skip index lookup and return `MatchStatus.NEW`
  rather than matching every zero-amount transaction in the book.
- Index: `dict[tuple[date, Decimal], list[gnucash.Transaction]]`
- ±1 day probe: collect all candidates from `date-1`, `date`, `date+1` keys
- **Multi-bucket collision rule**: if multiple GnuCash candidates are found
  across the three keys, prefer exact-date match first, then ±1 day.
  If still multiple after date preference, pick the one with the most
  matching account names. If still tied, return the candidate with the
  earliest post date ascending — deterministic because GnuCash preserves
  insertion order in its transaction list.
  This avoids silent wrong merges while keeping the common case simple.
- LIKELY_DUP: all split account name sets match exactly
- PARTIAL_MATCH: the set of asset/liability accounts (by `account.GetType()`)
  matches exactly between candidate and GnuCash tx, AND the set of
  income/expense accounts differs (at least one account differs). For 3+ split
  transactions: if *any* income/expense account differs → PARTIAL_MATCH,
  regardless of whether other income/expense accounts match.
  `merged_tx` populated using merge rules.
- NEW: no match found → `merged_tx is None`, `existing_tx is None`

**Merge rules for PARTIAL_MATCH** (`merged_tx`):
- `guid`: use `transaction.GetGUID().to_string()` — do NOT use `str()` directly
  on the GUID object as it may not produce the canonical format. Check
  existing usages in `repositories/gnucash_repository.py` for the project's
  established GUID-to-string pattern.
- Account categorization from GnuCash
- `doc_link`: from generated tx. To check if GnuCash tx has an existing
  doc_link, read the `doc_link` KVP slot via the existing `kvp.py`
  infrastructure (`read_tx_metadata(tx).get("doc_link")`).
- Description from GnuCash unless empty
- Date from GnuCash
- Amount from GnuCash

Uses `GnuCashRepository(path, SessionMode.READ_ONLY)` — no writes.

## Unit tests

`tests/unit/services/test_gnucash_fuzzy_matcher.py` — mock `GnuCashRepository`:

| Test | Scenario | Expected |
|---|---|---|
| `test_amount_normalization_2split` | `[+100, -100]` | normalized = 100 |
| `test_amount_normalization_3split` | `[+300, -200, -100]` | normalized = 300 |
| `test_amount_normalization_zero_guard` | all-negative splits (refund) | `MatchStatus.NEW`, no index lookup |
| `test_three_key_probe` | verify index probed at date-1, date, date+1 | 3 calls to mock |
| `test_new_no_candidates` | mock returns empty for all three keys | `MatchStatus.NEW` |
| `test_likely_dup_account_sets_equal` | mock returns tx with identical accounts | `MatchStatus.LIKELY_DUP` |
| `test_partial_match_expense_differs` | same bank account, different expense | `MatchStatus.PARTIAL_MATCH` |
| `test_tiebreak_exact_date_beats_near` | two candidates: one exact date, one ±1 day | exact-date candidate chosen |
| `test_tiebreak_most_matching_accounts` | two ±1-day candidates: one shares 2 accounts, one shares 1 | 2-account candidate chosen |
| `test_tiebreak_earliest_date` | two ±1-day candidates with equal account matches | candidate with earlier post date chosen |
| `test_merged_tx_guid` | PARTIAL_MATCH | `merged_tx.guid == existing_tx.GetGUID().to_string()` |
| `test_merged_tx_category_gnucash_wins` | GnuCash has Dining, generated has Misc | `merged_tx` has Dining |
| `test_merged_tx_doc_link_generated_wins` | GnuCash no doc_link, generated has one | `merged_tx` has generated doc_link |
| `test_merged_tx_none_for_new` | NEW result | `merged_tx is None` |
| `test_merged_tx_none_for_likely_dup` | LIKELY_DUP result | `merged_tx is None` |
| `test_existing_tx_none_for_new` | NEW result | `existing_tx is None` |

## Integration tests

`tests/integration/services/test_gnucash_fuzzy_matcher.py` — real temp `.gnucash` book:

| Test | Fixture contains | Candidate | Expected |
|---|---|---|---|
| `test_new` | nothing matching | salary 18110 HKD | `NEW` |
| `test_likely_dup_exact_date` | identical tx | same tx | `LIKELY_DUP` |
| `test_likely_dup_plus_one_day` | tx at date-1 | same amount+accounts | `LIKELY_DUP` |
| `test_likely_dup_minus_one_day` | tx at date+1 | same amount+accounts | `LIKELY_DUP` |
| `test_two_days_away_is_new` | tx at date-2 | same amount+accounts | `NEW` |
| `test_partial_match` | same bank account, Dining expense | generated has Misc | `PARTIAL_MATCH` |
| `test_partial_match_guid` | PARTIAL_MATCH | — | `merged_tx.guid` matches book tx |
| `test_partial_match_gnucash_category` | GnuCash has Dining | — | `merged_tx` splits include Dining |
| `test_partial_match_generated_doc_link` | GnuCash tx has no doc_link | generated has one | `merged_tx` has generated doc_link |
| `test_multi_split_normalization` | 3-split tx in book | same total | `LIKELY_DUP` |
| `test_custom_account_type_detection` | custom account hierarchy | `GetType()` used | PARTIAL_MATCH correct |

## Acceptance

All integration tests pass inside Docker. A `StandardTransaction` that matches
an existing GnuCash transaction by (date ±1, amount, accounts) is correctly
classified as `LIKELY_DUP` or `PARTIAL_MATCH` with a populated `merged_tx`
that uses GnuCash's category and the generated `doc_link`.

## Files

- `services/gnucash_fuzzy_matcher.py` (new)
- `tests/unit/services/test_gnucash_fuzzy_matcher.py` (new)
- `tests/integration/services/test_gnucash_fuzzy_matcher.py` (new)

---

## Implementation Finding: Session Leak Causes OOM

**Discovered during implementation of F-008.**

### Root Cause

`GnuCashFuzzyMatcher._build_index()` opens a `GnuCashRepository` session
(READ_ONLY) that is **never closed**. `self._index` holds live
`gnucash.Transaction` references, keeping the entire parsed GnuCash book in
memory for the lifetime of the matcher object.

Python's GC does not guarantee timely destruction of GnuCash C extension
objects. In the test suite, each integration test that creates a
`GnuCashFuzzyMatcher` and calls `match()` opens a new session. With 9
integration tests running in sequence, 9 open sessions accumulate on top of
the ~700-test suite's existing GnuCash sessions → OOM kill inside Docker.

### Fix Required Before Implementation Is Complete

Store Python-native data in the index instead of live `gnucash.Transaction`
references, then close the session after `_build_index()` completes:

```python
@dataclass
class _IndexEntry:
    date: date
    amount: Decimal
    account_names: frozenset[str]   # extracted as strings, not GnuCash objects
    guid: str
    description: str
    splits: list[tuple[str, Decimal]]  # (account_name, amount)
    existing_doc_link: str

def _build_index(self) -> None:
    ...
    repo.open(READ_ONLY)
    for tx in repo.get_all_transactions():
        entry = _IndexEntry(...)   # extract all needed data
        self._index[key].append(entry)
    repo.close()   # ← session released; no live GnuCash refs remain
```

`MatchResult.existing_tx` type changes from `gnucash.Transaction | None`
to `_IndexEntry | None` — the live GnuCash object is no longer needed after
index build since all required data is extracted.

### Impact on Tests

PARTIAL_MATCH fixture: the existing transaction must be a credit card charge
`boci → dining` (expense account), NOT `boci → bank` (two asset/liability
accounts). With `boci → bank`, `existing_al = {boci, bank}` but
`candidate_al = {boci}` — they never match and PARTIAL_MATCH returns NEW.
The correct scenario: user manually categorized the charge as Dining;
we generated it as Groceries; shared `boci` liability account triggers match.
