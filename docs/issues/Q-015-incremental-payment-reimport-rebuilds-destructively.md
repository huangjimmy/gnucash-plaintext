---
id: Q-015
title: Incremental + overpayment + credit-consumption payment workflows on re-import — no orphans, full prepayment-credit support, importer-side orphan warnings, find-prepayments CLI
category: quality
severity: high
status: closed
---

## Problem

Seven closely-related gaps on the import / export path that together broke the "customer pays in instalments / overpays / uses credit toward next invoice" workflow — every real-world payment shape beyond "one cash payment exactly matching invoice total". Three were silent data-corruption defects (rooted in `Unpost(False)` rebuilds and matcher iteration-order dependence); four were missing-feature gaps where overpayment credits and credit consumption couldn't be expressed in plaintext at all.

### 1. Adding a `payment:` block re-imports destructively

Adding a partial payment to a posted invoice/bill through the most natural workflow — edit the plaintext to append another `payment:` block, re-import — silently corrupted the bank balance and broke external references. `services/gnucash_importer.py` classified the directive via `_invoice_matches_directive`; any divergence (including "directive appends one payment to the existing list") fell through to:

```python
existing.Unpost(False)        # destroys posting tx, orphans bank-side splits
# ... full rebuild + repost
```

On a $100 invoice paid $60, then re-imported with `payment: 60` + `payment: 40` added:

| | Before re-import | After re-import |
|---|---|---|
| Bank txs in `Assets:Bank` | 1 ($60) | **3** ($60 orphan + new $60 + new $40) |
| Posting tx GUID | `d711836b…` | `81aaed4e…` (changed) |
| Entry GUIDs | `d17255a0…` | `f7728687…` (changed) |
| Lot payments | original $60 tx | two new $60 + $40 (original orphaned) |

Bank reconciliation surfaces a $60 deposit it can't match; invoice display reads "$40 outstanding" on a paid invoice.

### 2. Every importer-side `Unpost(False)` was silent about the orphan it created

Q-014 shipped a per-record orphan-payment warning from the `unpost-invoices` / `unpost-bills` CLI commands. The same `Unpost(False)` call was made by the importer from **four** other places — Q-010 minimal-unpost (invoice and bill `posted: none` path) and the destructive rebuild (invoice and bill, fired by entry / posted / payment field changes). None warned. A user re-importing a paid invoice with a typo in the entry description silently orphaned the bank tx with no indication.

### 3. Overpayment (pre-payment credit) had no plaintext representation, and the matcher silently duplicated bill overpayments on roundtrip

GnuCash's `ApplyPayment(amount=150)` on a $100 invoice correctly creates two AR lots (invoice closed at $0, pre-payment lot open at -$50). The exporter only emitted `payment: 150`; the $50 credit on AR was invisible. Round-trip preserved it by luck on invoices (the matcher's "find non-AR-split-by-exclusion" heuristic happened to pick the bank split first); on bills the iteration order put the +$50 AP split first, mis-identified it as bank, returned False, fired the destructive rebuild, and **silently duplicated the bank tx**. Retarget (`payment: txn_guid:`) with an over-sized counter-split silently left the invoice lot at balance -$50, semantically malformed.

### 4. The `txn_guid:` retarget path silently malformed lots on overpayment

`_retarget_counter_split_to_lot` moved the entire counter-split into the invoice's lot, regardless of size. For a $150 bank tx retargeted to a $100 invoice, the invoice's lot ended at balance -$50 (overpaid; GnuCash had no auto-split). No error, no warning — just a broken lot the user couldn't see.

### 5. Customer / vendor credits couldn't be consumed via plaintext

A customer with an existing $50 credit on AR (from a prior overpayment) had no way to express "apply the credit toward the next invoice" in plaintext. Manual `ApplyPayment` calls don't auto-consume credit. The user had to fall back to GnuCash UI's Process Payment → "Apply credit" — defeating the plaintext-as-source-of-truth model.

### 6. No way to see open credits without exporting the whole book

A user asking "what credits do I have on file for Acme?" had to export the entire book to plaintext and grep through it, or open the GnuCash UI. No focused CLI for the question.

### 7. Bank-side split lookup was iteration-order-dependent

`_single_payment_matches` walked `tx.GetSplitList()` and picked "the first split that isn't the in-lot AR/AP split" as the bank side. For overpayment txs (bank + invoice-lot AR + prepayment-lot AR = 3 splits) this picked whichever split came first in iteration order — luck on invoices, wrong on bills. The "Defect 3" duplication was just one symptom; any tx with 3+ splits was at risk.

## Reproduction

All seven defects are covered by **58 dedicated integration tests** across seven files (see "Tests" below). Each test is self-contained, uses a per-scenario fixture under `tests/fixtures/q015_*.txt`, and asserts on the user-visible outcome (lot balances, bank tx count, GUID preservation, output text) rather than on internal split identity.

## Fix

### Defect #1 — add-payment fast path

New classifier `_is_only_added_payment_diff_invoice` / `_is_only_added_payment_diff_bill` that returns True iff:

- entries match byte-for-byte (`_invoice_non_payment_matches` / `_bill_non_payment_matches`),
- the `posted:` block matches,
- the directive's payments are a *prefix-preserving superset* of the record's lot payments (every existing payment matches the corresponding directive 1:1; the directive has K > N tail entries).

When True, the caller walks the trailing K-N payment directives and calls `_apply_payment_directive(record, pay_dir, book, is_bill)` on the still-posted record — no Unpost, no rebuild. Posting tx, entry, and existing payment GUIDs are preserved; no orphan; no double bank balance. The bill side mirrors the invoice via `_is_only_added_payment_diff_bill`. The negated-amount `ApplyPayment(-N)` mechanic for AP is factored into `_apply_payment_directive`, which also handles the `txn_guid:` retarget branch.

### Defect #2 — importer-side orphan warning

New helper `_emit_orphan_warning_before_unpost(record, kind, ident, on_orphan_warning)`: called immediately before every `existing.Unpost(False)` in `import_invoice` / `import_bill` (4 callsites). Captures the about-to-be-orphaned payments via the existing Q-014 `find_lot_payment_transactions(rec)` helper and invokes a callback. New plumbing in `import_business_objects` carries an `on_orphan_warning(kind, id, orphans)` callback alongside the existing `on_directive_status`. `cli/import_cmd.py` passes a callback that renders the warning block to stderr.

`format_orphan_warning_block(kind, orphans, ident='')` is factored out of `cli/unpost_cmd.py` into `use_cases/unpost_business_objects.py` so the unpost CLI and the import CLI emit identical warning text.

### Defects #3 + #4 — `prepayment:` field

New optional `prepayment: N` field inside `payment:` blocks. Exporter (`_format_payment`) emits it when a payment tx has AR/AP-side splits outside the invoice/bill's posted lot. Matcher (`_single_payment_matches`) compares the declared value to the actual residual computed from the book.

The importer treats `prepayment:` differently depending on path:

- **`ApplyPayment` path** (no `txn_guid`): GnuCash auto-creates the pre-payment lot when `amount > invoice_remaining`. `prepayment:` is informational and validated by the matcher on re-import.
- **Retarget path** (`txn_guid:`): if `counter_split_amount > invoice_remaining`, `prepayment:` is **required**. The new `_retarget_with_prepayment_split` helper reduces the existing counter-split to `invoice_remaining` (re-accounts to AR/AP, attaches to the invoice lot) and creates a new split for the residual on the same tx, in a fresh lot on the same AR/AP account. Missing `prepayment:` → explicit error naming the bank tx, the counter-split amount, the invoice remaining, and the expected `prepayment` value.

`test_overpayment_path_equivalence.py` (4 tests) asserts the two paths produce **semantically identical end-state** across initial import + double roundtrip — same bank tx amounts, AR lot count, lot balances, lot members. The internal split-identity differs (which physical split keeps which GUID after split-the-counter-split) but nothing in the user-visible surface or the round-trip distinguishes them.

### Defect #5 — `auto_apply_credit:` flag

New optional `auto_apply_credit: true` field on `invoice` / `bill` directives. When set, after `PostToAccount` runs, the importer calls `inv.AutoApplyPayments()` — GnuCash's canonical mechanism for consuming customer / vendor pre-payment lots. Composes cleanly with cash `payment:` blocks: cash applies first; auto-apply consumes credit toward whatever balance remains. The exporter detects the post-auto-apply state (any payment-tx split in this invoice's lot whose parent tx has other splits in another invoice/bill's lot for the same owner) and emits the flag for round-trip stability.

### Defect #6 — `find-prepayments` CLI

New read-only command parallel to Q-014's `find-orphan-payments`. Walks the book for open AR/AP lots that are not attached to any invoice/bill and have non-zero balance; reports per-credit owner, amount, currency, source bank tx, and AR/AP account. Supports `--customer` / `--vendor` filters. Implementation in `use_cases/unpost_business_objects.py` (`find_prepayments_in_book`) reuses Q-014's lot-walking plumbing with the inverse filter.

### Defect #7 — matcher bank-side lookup by account match

`_single_payment_matches` now finds the bank-side split by `bank_account` name match (the directive's declared field is authoritative), not by exclusion of the in-lot AR/AP split. Deterministic, version-stable, robust to any tx-split count.

## Tests

58 integration tests across seven files, all passing on every supported distro (debian11/12/13, ubuntu20/22/24/26, fedora41, opensuse, arch):

- `tests/integration/test_incremental_payment_reimport.py` (6) — add-payment fast path preserves posting/entry GUIDs and the original bank tx; identical re-import is still `unchanged`; modify/remove an existing payment correctly falls through to the rebuild path.
- `tests/integration/test_payment_roundtrip_no_orphan.py` (11) — single/double roundtrip on paid and partial-paid invoices and bills creates zero orphans; pre-existing orphans survive roundtrip and double-roundtrip without duplication.
- `tests/integration/test_importer_destructive_orphan.py` (12) — every importer-side `Unpost(False)` path emits an orphan warning that mentions the orphan's tx GUID and the word "orphan"; idempotent re-runs don't accumulate orphans; negative controls confirm the `unchanged` and add-payment fast paths emit no warning.
- `tests/integration/test_overpayment_handling.py` (11) — invoice and bill overpayment via `ApplyPayment` roundtrips with the new `prepayment:` field; double-roundtrip stable; retarget with explicit `prepayment:` succeeds and creates the right two-lot structure; retarget without `prepayment:` on an oversized counter-split fails with a clear error; exact and underpaying retargets remain unchanged.
- `tests/integration/test_overpayment_path_equivalence.py` (4) — ApplyPayment-overpayment and retarget-with-prepayment produce semantically identical book state across initial import + double roundtrip on four scenarios (basic overpayment, exact, partial, two overpayments).
- `tests/integration/test_auto_apply_credit.py` (7) — `auto_apply_credit: true` consumes existing customer/vendor credit; composes with cash `payment:`; over-consume case partially pays the invoice; roundtrip emits the flag and re-import is idempotent; bill counterparts.
- `tests/integration/test_find_prepayments.py` (7) — empty book reports zero; single customer/vendor credit; multi-credit per owner; `--customer` / `--vendor` filters; after partial consume shows residual.

All 84 fixture files live in `tests/fixtures/q015_*.txt` with distinct invoice/bill IDs and amounts per scenario so a reader can tell at a glance which fixture each test uses.

## Documentation

- `README.md` — new sections on incremental add-payment workflow, overpayment + `prepayment:` field, `auto_apply_credit:` flag, `find-prepayments` CLI with sample output.
- `docs/payment-manual-edit-behavior.md` — new doc characterising importer behaviour under five book/plaintext-divergence scenarios (manual UI edits to splits and txs, plaintext-side edits) with the per-scenario outcome table.

## Related

- **Q-007** — entry-GUID preservation contract.
- **Q-010** — strict 'unchanged' status; mutable posted invoices/bills + `unpost` CLI. Introduced the destructive rebuild path this issue narrows.
- **Q-014** — orphan-payment warning on `unpost-invoices` / `unpost-bills`. Q-015 extends the same warning to every importer-side unpost callsite, factors the formatter into a shared function, and adds the `find-prepayments` companion to `find-orphan-payments`.
- **Q-016** — tightens the `_payment_is_credit_consumption` heuristic this issue introduced. The Q-015 version classified a payment as "credit consumption" (and emitted `auto_apply_credit: true` instead of a regular `payment:` block) when either an "other invoice lot" signature *or* a "prepay lot" signature appeared on the tx. Q-016 requires **both** so that three distinct shapes are emitted distinctly: (a) Q-015 auto-apply consumption (both signatures present) → `auto_apply_credit: true`; (b) Q-015 overpayment (only prepay lot present) → `payment:` with `prepayment:`; (c) Q-016 multi-invoice shared bank tx (only other-invoice lots present) → `payment:` with `txn_guid:` and `txn_split_guid:` for each invoice. Q-016 also generalises GUID emission across all payment-block flavours (`prepayment:`, `auto_apply_credit:`, retarget, multi-invoice) so the export → fresh-book re-import story is uniform.
