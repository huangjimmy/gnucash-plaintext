# Statement Import Pipeline — Design Document

**Feature branch**: `feature/statement-import-pipeline`
**Created**: 2026-05-01
**Status**: Design approved, implementation pending

---

## Overview

A pipeline for importing bank and credit card PDF statements into GnuCash,
with cross-statement autopay reconciliation, fuzzy duplicate detection against
an existing GnuCash book, and human-guided merge of conflicting information.

The pipeline is split into two phases:

- **Phase 1 (native Python, no GnuCash):** Parse PDFs → reconcile autopay
  entries → write `_reconcile.txt` preview
- **Phase 2 (GnuCash READ_ONLY):** Fuzzy-match against `.gnucash` file →
  classify as NEW / LIKELY_DUP / PARTIAL_MATCH → write ready-to-import txt

The ready-to-import txt feeds directly into the existing `import-transactions`
pipeline, which performs exact-match deduplication as a final safety net.

---

## Motivation

Banks such as BOCHK, BOCI (BOC Credit Card), and AEON HK do not provide QFX
downloads. Their monthly PDF statements are the only machine-readable source.
A provider-based PDF parser architecture allows each bank's format to be
supported independently while sharing common reconciliation and dedup logic.

---

## Architecture

### Component Overview

```
┌──────────────────────────────────────────────────────────────┐
│                      PHASE 1 (native)                        │
│                                                              │
│  PDF files                                                   │
│      ↓                                                       │
│  StatementProvider.can_handle() / parse()                    │
│  (one provider per bank format)                              │
│      ↓                                                       │
│  list[StandardTransaction]                                   │
│      ↓                                                       │
│  StatementReconciler.reconcile()                             │
│  (match Reconcile:Autopay pairs across statements)           │
│      ↓                                                       │
│  _reconcile.txt  (preview — all transactions, status marked) │
└──────────────────────────────────────────────────────────────┘
                            ↓ human reviews
┌──────────────────────────────────────────────────────────────┐
│                      PHASE 2 (GnuCash READ_ONLY)             │
│                                                              │
│  _reconcile.txt + .gnucash file                              │
│      ↓                                                       │
│  GnuCashFuzzyMatcher (GnuCashRepository READ_ONLY)           │
│  → NEW / LIKELY_DUP / PARTIAL_MATCH                          │
│      ↓                                                       │
│  ready-to-import.txt                                         │
│  - NEW            → import as-is                             │
│  - LIKELY_DUP     → commented out, note attached             │
│  - PARTIAL_MATCH  → suggested merge shown, human edits       │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│              EXISTING import-transactions pipeline            │
│        (exact-match dedup via TransactionMatcher)            │
└──────────────────────────────────────────────────────────────┘
```

---

## Data Models

### `StandardTransaction`

The common output format for all providers:

```python
@dataclass
class StandardTransaction:
    post_date: date
    description: str
    currency: str
    splits: list[Split]          # at least 2; typically 2 for simple transactions,
                                 # more for split expenses across multiple accounts
    source_pdfs: list[str]       # filename(s) only — merged tx carries both sides
    guid: str | None = None      # set from GnuCash on PARTIAL_MATCH merge so that
                                 # re-import updates the existing tx (not insert)
```

```python
@dataclass
class Split:
    account: str
    amount: Decimal              # use Decimal, not float — float causes ULP mismatches
                                 # in dict key lookups during fuzzy matching
```

`doc_link` paths are constructed by the **output writer** as
`f"{DOC_LINK_BASE}/{source_pdfs[0]}"` — the path prefix is not stored in the
data model. `DOC_LINK_BASE` is defined as a module-level constant in the
public repo's output writer with a default value of `"bank_statements"`. The
private orchestrator (`reconcile_boc.py`) may override it if needed. Using a
fixed default ensures `_reconcile.txt` and `ready-to-import.txt` produce
consistent `doc_link` paths across runs.

`source_pdfs` ordering convention:
- Single-source transaction: `source_pdfs = [pdf_filename]`
- Merged autopay transaction: `source_pdfs = [card_pdf, bank_pdf]` — the
  card-side PDF is always `[0]` (primary `doc_link`); the bank-side PDF is
  `[1]`. The `StatementReconciler` is responsible for populating this order.

`Reconcile:Autopay` is used as a placeholder account name when one side of a
cross-statement payment is known but the other is not yet resolved.

### `MatchResult`

Returned by `GnuCashFuzzyMatcher` for each candidate transaction:

```python
@dataclass
class MatchResult:
    status: MatchStatus                        # NEW | LIKELY_DUP | PARTIAL_MATCH
    existing_tx: gnucash.Transaction | None    # None only for NEW
    merged_tx: StandardTransaction | None      # non-None only for PARTIAL_MATCH;
                                               # None for NEW and LIKELY_DUP
    # No confidence field — match status is deterministic, not probabilistic.
```

```python
class MatchStatus(Enum):
    NEW           = "new"          # not found in GnuCash
    LIKELY_DUP    = "likely_dup"   # same date±1, amount, accounts
    PARTIAL_MATCH = "partial"      # same date±1, amount; different category
```

---

## New Public Repo Components

### `infrastructure/pdf/provider.py` — `StatementProvider` Protocol

```python
class StatementProvider(Protocol):
    autopay_source: dict[str, str]  # currency → bank account funding autopay
                                    # e.g. {"HKD": "Assets:...:BOC HKD Saving"}
    def can_handle(self, filename: str) -> bool: ...
    def parse(self, path: str) -> list[StandardTransaction]: ...
```

Provider registration is explicit — the orchestrator (private script) lists
which providers to try, in order. No dynamic discovery.

### `infrastructure/pdf/standard_tx.py` — Data Classes

`StandardTransaction` and `Split` only. These are pure data models shared
between providers, the reconciler, and the output writer — no GnuCash-specific
types.

`MatchResult` and `MatchStatus` are defined in `services/gnucash_fuzzy_matcher.py`
alongside the matcher that produces them. Keeping them there avoids an upward
dependency from `infrastructure` onto the GnuCash binding type
(`gnucash.Transaction`).

### `services/statement_reconciler.py` — `StatementReconciler`

Resolves `Reconcile:Autopay` placeholder pairs across statements.

**Matching criteria:**
- Both transactions have a `Reconcile:Autopay` split
- One has `Reconcile:Autopay` as positive amount (bank side — debit from savings)
- One has `Reconcile:Autopay` as negative amount (card side — credit to card)
- Same currency
- Date within ±1 day (timezone and travel tolerance)
- Absolute amounts match exactly

**On match:** produce one merged `StandardTransaction` (Phase 1 merge — no GnuCash
involvement yet) using:
- Date, description, doc_link from the card side (credit card statement is primary)
- Bank account from the bank side
- Card account from the card side

Note: this Phase 1 date comes from the card statement. If this merged transaction
later hits a Phase 2 PARTIAL_MATCH against an existing GnuCash entry, the merge
rules table applies and GnuCash's date wins (timezone-corrected by the user).

**Unmatched:** remain in output with `Reconcile:Autopay` still in place, clearly
marked as `[UNRESOLVED]` — a signal that the corresponding statement PDF was
not provided yet (partial run).

**Autopay collision tie-break:** if the ±1 day window produces more than one
match candidate on **either side** of the pairing, the reconciler does **not**
auto-resolve. Both cases emit `[UNRESOLVED]`:

- Same-side collision: two bank entries (or two card entries) for the same
  amount within ±1 day → neither is matched
- Cross-side collision: one bank entry matches two card entries from different
  providers for the same amount within ±1 day → none of the three is matched

Silent wrong merges are worse than visible failures. All collision cases must
produce a human-readable `[UNRESOLVED]` comment identifying the conflicting
entries so the user can resolve by narrowing the date range or inspecting the
statements manually.

### `services/reconcile_preview_reader.py` — `ReconcilePreviewReader`

Reads `_reconcile.txt` and yields transactions for Phase 2. This is the
Phase 1 → Phase 2 bridge. It does **not** use `PlaintextParser` — the
annotation-heavy format of `_reconcile.txt` is incompatible.

**Interface:**

```python
class ReconcilePreviewReader:
    def read(self, path: str) -> tuple[
        list[StandardTransaction],   # resolved — eligible for fuzzy match
        list[StandardTransaction],   # unresolved — contain Reconcile:Autopay
    ]: ...
```

**Parsing contract:**
- Lines starting with `;;` are comments — skipped entirely, including section
  headers (`===== RESOLVED =====`, `===== UNRESOLVED =====`). Section headers
  are for human readability only; the reader does NOT use position within a
  section to classify transactions.
- Transaction blocks are the same format as `ready-to-import.txt` (date line,
  tab-indented metadata and split lines).
- A transaction is classified as **unresolved** if any split account equals
  the literal string `Reconcile:Autopay`; otherwise **resolved**. This is
  the sole classification criterion — not section position.

**UNRESOLVED handling in Phase 2 — critical correctness rule:**

UNRESOLVED transactions (those still containing `Reconcile:Autopay`) are
**never passed to `GnuCashFuzzyMatcher`** and are **never written to
`ready-to-import.txt`** as live transaction blocks. Importing a transaction
with `Reconcile:Autopay` as an account would write a garbage split into the
GnuCash book.

Instead, each UNRESOLVED transaction is written to `ready-to-import.txt` as
a fully commented-out block with a warning header:

```
;; [UNRESOLVED — DO NOT IMPORT]
;; Missing statement: the other side of this autopay was not provided.
;; Re-run with the missing PDF to resolve.
;; 2026-04-02 * "自動轉賬 / BOC CREDIT CARD (INT"
;;     doc_link: "bank_statements/bochk-2026-04.pdf"
;;     ...
;;     Reconcile:Autopay 125.00 HKD
```

---

### `services/gnucash_fuzzy_matcher.py` — `GnuCashFuzzyMatcher`

Uses `GnuCashRepository` in `SessionMode.READ_ONLY` — no GnuCash Python
bindings quirks, no write risk.

**Matching algorithm:**

**Amount normalization (applied symmetrically on both sides):**

For any balanced transaction, the sum of all positive splits equals the sum of
all negative splits. Use the sum of positive splits as the canonical amount:

```
amount = sum(s for s in split_amounts if s > 0)
```

- **Candidate side**: `sum(s.amount for s in tx.splits if s.amount > Decimal(0))`
- **GnuCash side**: `sum(Decimal(str(sp.GetAmount())) for sp in tx.GetSplitList() if sp.GetAmount() > 0)`

This is consistent across both sides regardless of split count or ordering, and
is the sole normalization rule used for index keys and lookup probes.

**Current constraint:** multi-currency splits (where split amounts are in
different currencies) are not yet supported. All splits are assumed to share
the transaction's base currency.

1. Load all existing GnuCash transactions into an index:
   `dict[tuple[date, Decimal], list[gnucash.Transaction]]`
   keyed by `(posted_date, normalized_amount)` using the rule above.
2. For each candidate `StandardTransaction`:
   a. Compute `amount` using the same normalization rule (sum of positive splits).
   b. Look up index entries within ±1 day by probing three keys:
      `index.get((date - 1day, amount), []) + index.get((date, amount), []) +
      index.get((date + 1day, amount), [])`. A single dict lookup on exact date
      would silently miss adjacent-day matches.
   c. For each candidate GnuCash tx:
      - **LIKELY_DUP**: all split account names match exactly (set equality
        across both transactions' split account name lists) → skip on export
      - **PARTIAL_MATCH**: the asset/liability split accounts match but at
        least one income/expense account differs → produce merged suggestion.
        Account type (Asset/Liability vs Income/Expense) is determined via
        `account.GetType()` from the GnuCash Python bindings — not via name
        prefix heuristics — to handle custom account hierarchies correctly.
        For 3+ split transactions, "asset/liability accounts match" means the
        set of accounts where `GetType()` is ASSET or LIABILITY is identical.
      - No match → **NEW**

**Why GnuCash Python bindings (READ_ONLY), not XML parsing:**
- Handles gzip compression, XML schema versions, and encrypted books correctly
- Provides typed account/transaction/split objects rather than raw XML nodes
- `SessionMode.READ_ONLY` guarantees no writes
- Consistent with the rest of the codebase

---

## Autopay Reconciliation Design

### The Problem

When a credit card autopay occurs, two statements record the same real-world
payment from opposite perspectives:

| Statement | What it records |
|---|---|
| Bank (BOCHK) | `Savings account -247.10 HKD` → `Reconcile:Autopay +247.10` |
| Credit card (BOCI) | `BOCI-0012 +247.10 HKD` → `Reconcile:Autopay -247.10` |

Both use `Reconcile:Autopay` as a placeholder. The reconciler finds these pairs
and merges them into one correct double-entry transaction:

```
2026-04-15 * "AUTOPAY INGROUP"
    doc_link: "bank_statements/boci-0012-2026-04.pdf"
    currency.mnemonic: "HKD"
    Liabilities:Credit Card:BOCI-0012        247.10 HKD
    Assets:...:BOC HK:Savings:BOC HKD Saving -247.10 HKD
```

### Known Autopay Relationships (private provider config)

Each provider declares which bank account funds its autopay, by currency:

```python
# BOCI credit card provider
autopay_source = {
    "HKD": "Assets:Current Assets:BOC HK:Savings:BOC HKD Saving",
    "CNY": "Assets:Current Assets:BOC HK:Savings:BOC CNY Saving",
}

# AEON HK credit card provider
autopay_source = {
    "HKD": "Assets:Current Assets:BOC HK:Savings:BOC HKD Saving",
}
```

This config lives in the private provider implementations, not the public repo.

---

## Merge Rules (PARTIAL_MATCH)

When a generated transaction partially matches an existing GnuCash transaction,
the suggested merge follows these rules:

| Field | Winner | Rationale |
|---|---|---|
| `guid` | GnuCash | Enables UPDATE (not INSERT) on re-import |
| Account categorization | GnuCash | Manually verified by user |
| `doc_link` | Generated | GnuCash rarely has PDF statement links |
| Description | GnuCash always, unless empty | Bank descriptions are longer but messier; user's GnuCash description is already cleaned up. Generated description is preserved in the commented `GENERATED` block for reference. |
| Date | GnuCash | Timezone/travel-corrected by user |
| Amount | GnuCash | Authoritative |

The merged suggestion is output as an **uncommented, ready-to-import block**
preceded by commented-out versions of both the existing and generated
transactions for human review.

---

## Output Format

### `_reconcile.txt` — Preview File

Always written to the current directory. Always overwritten on each run —
partial re-runs produce a fresh file. Named with a leading underscore to signal
it is auto-generated and not a source file.

**Note:** `_reconcile.txt` is **not** a valid plaintext import file. It
contains section headers and status comments (`;; ===== RESOLVED =====`,
`[UNRESOLVED]`, etc.) that the existing `PlaintextParser` does not handle.
Phase 2 reads `_reconcile.txt` with a dedicated `ReconcilePreviewReader` that
strips comments and section markers before passing transactions to
`GnuCashFuzzyMatcher`. This reader is part of the new public repo components.

Structure:
```
;; ===== RESOLVED =====
;; Transactions where Reconcile:Autopay was matched across statements

;; bochk-2026-04.pdf

2026-03-29 * "薪金入賬 / FPS/JUNTECH LIMITED/..."
    doc_link: "bank_statements/bochk-2026-04.pdf"
    currency.mnemonic: "HKD"
    Assets:Current Assets:BOC HK:Savings:BOC HKD Saving 18110.00 HKD
    Income:Salary:HKD -18110.00 HKD

;; boci-0012-2026-04.pdf

2026-04-15 * "AUTOPAY INGROUP"
    doc_link: "bank_statements/boci-0012-2026-04.pdf"
    currency.mnemonic: "HKD"
    Liabilities:Credit Card:BOCI-0012 247.10 HKD
    Assets:Current Assets:BOC HK:Savings:BOC HKD Saving -247.10 HKD

;; ===== UNRESOLVED =====
;; Transactions still containing Reconcile:Autopay — re-run with missing PDF

;; bochk-2026-04.pdf

2026-04-02 * "自動轉賬 / BOC CREDIT CARD (INT"
    doc_link: "bank_statements/bochk-2026-04.pdf"
    currency.mnemonic: "HKD"
    Assets:Current Assets:BOC HK:Savings:BOC HKD Saving -125.00 HKD
    Reconcile:Autopay 125.00 HKD
```

### `ready-to-import.txt` — Final Output (`-o` flag)

Structure:
```
;; ===== NEW — ready to import =====

;; ===== PARTIAL MATCH — review merged suggestion =====
;; EXISTING (GnuCash):
;; 2026-04-15 * "AUTOPAY INGROUP"
;;     guid: "abc123..."
;;     Expenses-HK:Dining 247.10 HKD          ← manually categorized
;;     ...
;; GENERATED (statement):
;; 2026-04-15 * "AUTOPAY INGROUP"
;;     doc_link: "bank_statements/boci-0012-2026-04.pdf"
;;     Expenses:Miscellaneous 247.10 HKD
;;     ...
;; SUGGESTED MERGE (edit if needed, then import):
2026-04-15 * "AUTOPAY INGROUP"
    guid: "abc123..."
    doc_link: "bank_statements/boci-0012-2026-04.pdf"
    ...

;; ===== LIKELY DUPLICATE — already in GnuCash =====
;; (commented out, no action needed)
```

---

## Implementation Plan

### New files (public repo)

| File | Purpose |
|---|---|
| `infrastructure/pdf/__init__.py` | Package init |
| `infrastructure/pdf/provider.py` | `StatementProvider` Protocol only |
| `infrastructure/pdf/standard_tx.py` | `StandardTransaction`, `Split` data classes |
| `services/statement_reconciler.py` | Cross-statement `Reconcile:Autopay` matching |
| `services/gnucash_fuzzy_matcher.py` | `MatchResult`, `MatchStatus`; fuzzy match against GnuCash book (READ_ONLY) |
| `services/reconcile_preview_reader.py` | Reads `_reconcile.txt`, strips annotations, yields `StandardTransaction` for Phase 2 |
| `tests/unit/services/test_statement_reconciler.py` | Unit tests |
| `tests/unit/services/test_reconcile_preview_reader.py` | Unit tests — parsing contract, UNRESOLVED detection, comment stripping |
| `tests/unit/services/test_gnucash_fuzzy_matcher.py` | Unit tests |

### Private scripts (not in public repo)

| File | Purpose |
|---|---|
| `convert_bochk_pdf.py` | `StatementProvider` for BOCHK consolidated statement |
| `convert_boci_pdf.py` | `StatementProvider` for BOCI credit card statement |
| `convert_aeon_pdf.py` | `StatementProvider` for AEON HK credit card statement |
| `reconcile_boc.py` | Orchestrator: registers providers, runs pipeline, writes output |

### Existing components reused unchanged

| Component | Role in pipeline |
|---|---|
| `GnuCashRepository(READ_ONLY)` | Read existing transactions for fuzzy match |
| `TransactionMatcher` | Exact-match dedup in final import step |
| `ConflictResolver` | Strategy application in final import step |
| `PlaintextParser` | Reads `ready-to-import.txt` in final import step |
| `ImportTransactionsUseCase` | Final import into GnuCash book |

---

## Implementation Notes

### CJK Character Encoding

BOCHK, BOCI, and AEON HK statements contain Chinese characters in merchant
names (e.g. `财付通`, `自動轉賬`). `pdfplumber` uses `pdfminer` under the hood,
which handles CJK glyph mapping correctly for these banks' PDFs. Implementors
must ensure output files are written as UTF-8 explicitly (`open(..., encoding="utf-8")`).
Do not rely on the system locale default.

---

## Open Questions

- **Same-amount same-day collision in fuzzy match**: if two transactions have
  the same date and amount but different accounts, both could be PARTIAL_MATCH
  candidates for the same generated transaction. Current plan: flag all
  candidates and let the user choose.
- **Currency conversion splits**: AEON and BOCI statements include original
  currency and rate in the description (e.g. `CNY 3.55(rate 1.149295)`). The
  current design records only the HKD amount. A future enhancement could emit
  proper multi-currency GnuCash splits with `share_price`.
- **Encrypted GnuCash books**: `GnuCashRepository` in READ_ONLY mode should
  handle encrypted books if the user supplies the passphrase. Not yet
  investigated.
