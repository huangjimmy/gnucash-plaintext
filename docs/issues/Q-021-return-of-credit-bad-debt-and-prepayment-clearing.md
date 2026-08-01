---
id: Q-021
title: Return of credit (refund), bad-debt write-off, and prepayment clearing via `lot_owner`
category: quality
severity: high
status: closed
---

## Problem

The plaintext format could *create* an open prepayment credit — Q-015 books an overpayment on an invoice/bill payment into a GnuCash prepayment lot — but it had no way to *dispose* of one. A customer overpays and you refund the difference; a vendor keeps an overpayment you'll never get back (vendor bad debt); a customer abandons a small credit you write off to income (forfeit). None of these were expressible. Separately, an uncollectable invoice could not be written off as bad debt, and a *standalone* credit (money received from an owner with no invoice attached) was invisible in plaintext — it round-tripped to nothing.

Full design and the cross-version engine probes are in [`docs/credit-refund-and-bad-debt-design.md`](../credit-refund-and-bad-debt-design.md), and the mechanism notes are in [`docs/research`](../research). GnuCash itself has no "refund" function: a refund, a bad-debt write-off, and a forfeit are all the same operation — a payment applied against the owner's lot — varying only the transfer account and the sign. The native owner-level auto-apply call (`gncOwnerApplyPaymentSecs` / `gncOwnerAutoApplyPaymentsWithLots`) **segfaults on GnuCash 4.4 (Debian 11) and 4.8 (Ubuntu 22)** in its lot-netting code, so the obvious path could not be used as-is.

## Why it matters

Without these operations the format can record money coming in but not the bookkeeping that closes the loop. An open credit that is never cleared overstates the owner's prepayment balance indefinitely; an uncollectable invoice sits posted forever; a standalone credit booked in GnuCash silently disappears on export → import. All three are everyday business-accounting events, and each must be expressible in a way that re-imports losslessly and works on every supported GnuCash build (3.8 through 5.14), not just the ones where the native auto-apply path happens not to crash.

## Fix

Three additions, each reusing existing machinery rather than inventing a new top-level directive:

**1. Invoice / bill bad debt via the existing `payment:` block.** A payment's transfer account is read from `account:` (canonical) or the legacy `bank_account:` alias; when both are present they must name the same account. The account *type* is validated by side: an invoice payment may go to an asset (cash received) or an expense (bad-debt write-off); a bill payment must go to an asset, because an unpaid bill we owe is debt forgiveness — a gain — which is out of scope. Income on an invoice (a credit memo), equity, and the AR/AP account itself are rejected. Intent is inferred from the account type; no separate write-off keyword.

**2. Clearing a credit reuses the `transaction:` directive and the existing per-split `lot_owner:` KVP.** Clearing a credit *is* an ordinary ledger transaction — a counter account plus an AR/AP split — so it reuses `transaction:` and the Q-014 `lot_owner:` KVP, extended to `lot_owner: kind:id[:guid]`. The counter split's account states the intent with no extra keyword: a bank account ⇒ refund, an expense ⇒ vendor bad debt, an income ⇒ customer forfeit (the legal account-type × owner matrix from fix 1 is enforced). The trailing guid is the **owner's** authoritative key (never a lot guid); it is always emitted on export and optional hand-written, and when present it MUST resolve to the same owner as the id — a mismatch is a hard **error**, never a warning, because `lot_owner:` is structural, not informational.

Import is **join-or-create**: if the owner has an open lot this split reduces (opposite sign) → **join** it (a clearing); otherwise, if the split is itself a credit/payment origin (AR-negative / AP-positive) → **create** a new lot and attach the owner (an orphan payment reconstructed, or a fresh standalone credit — closing the standalone-credit gap); a clearing-shaped split with no credit to reduce → **error**, never a phantom lot. No amount/balance validation on a join: partial (residual stays open), exact (lot closes), and over-applied are all accepted.

**3. Per-account `open_prepayment:` summary on AR/AP accounts.** The exporter emits one block per open, owner-attached, non-invoice lot (owner id, owner guid, amount), oldest first. It is derived and informational: on import it is parsed but not acted on (the per-split `lot_owner:` KVPs are authoritative and rebuild the lots), and a post-import pass recomputes the credits with the same lot walk and **warns to stderr — never fails** — when a declared block disagrees, since the next export self-heals the file.

**Engine path.** Clearing is implemented with the primitive lot-split close (build a 2-split txn, `gnc_lot_add_split` the AR/AP split into the existing credit lot, set `TXN_TYPE_PAYMENT`), and lot creation uses `gnc_lot_new` + `xaccAccountInsertLot` + `gnc_lot_add_split` + `gncOwnerAttachToLot`. This avoids the auto-apply lot-netting that segfaults on 4.4/4.8 and is **verified on all ten supported builds (3.8–5.14)** for full refund, partial refund, vendor bad debt, forfeit, standalone-credit create-then-settle, and export → fresh re-import. Invoice/bill bad debt closes the document's own lot via the existing invoice `ApplyPayment` path and works on every version.

A `clear-prepayment` convenience CLI was considered and **rejected**: it would have to assume the destination account's currency and would hide details (the AR/AP account, the sign) a user writing an import file generally wants to set explicitly. The `transaction:` directive with a `lot_owner:`-tagged split is the single, explicit path.

## Files touched

| File | Change |
|---|---|
| `services/gnucash_importer.py` | `_parse_lot_owner` parses `kind:id[:guid]` (guid = trailing segment iff a valid GUID, so a colon inside the id survives). `_attach_lot_owner_split` is the join-or-create engine: owner-type-by-account validation (customer ⇒ AR, vendor ⇒ AP), authoritative-guid check (mismatch raises), join the owner's oldest open opposite-sign reducible non-invoice lot via the primitive `gnc_lot_add_split` + `TXN_TYPE_PAYMENT`, else create a new lot for an origin-shaped split, else error. Replaces the Q-014 always-create `lot_owner:` handler in `create_transaction`. `_payment_xfer_account_name` reads `account:` / `bank_account:` (both-present-must-agree); `_validate_payment_account_type` enforces asset-or-expense by side. |
| `services/plaintext_parser.py` | New `OPEN_PREPAYMENT` directive type and the `open_prepayment:` sub-block under an open-account directive. `parse_split` returns no match when the candidate account ends in `:`, so a `key: NUM SYMBOL` metadata line (e.g. `amount: 50.00 CAD`) falls through to metadata parsing instead of being read as a split. |
| `use_cases/export_transactions.py` | `open_prepayments_for_account` — shared lot walk returning `(kind, owner_id, owner_guid, amount)` per open owner-attached non-invoice lot, owner resolved via `gncOwnerGetOwnerFromLot` (so standalone credits are seen). `_append_open_prepayments` emits the `open_prepayment:` summary on AR/AP accounts. `_format_split` emits `lot_owner: kind:id:guid` from the lot's owner backref. |
| `cli/import_cmd.py` | `_warn_open_prepayment_mismatches` — post-import pass that recomputes credits with the shared walk and warns (never fails) on a declared/actual mismatch. Surfaces per-transaction error messages. Fixes a pre-existing bug where the account-creation error path read `props['account_name']` (nonexistent → always reported `'?'`) instead of `props['account']`. |
| `README.md` | User-facing docs for the new surfaces: invoice bad-debt via `payment:`-to-expense, the `lot_owner:` credit-disposal directive (refund / vendor bad debt / forfeit), the `open_prepayment:` AR/AP summary, and refreshed `find-prepayments` disposal guidance. |
| `docs/credit-refund-and-bad-debt-design.md` | The feature's design document, reconciled to the shipped `lot_owner` behaviour (status "Implemented and tested"). |
| `docs/issues/Q-021-…md`, `docs/issues/README.md` | This ticket and its Quality-table row. |

## Tests

16 integration tests, all passing on GnuCash 3.8 and 5.10 and (via the pre-commit suite) every supported distro:

`tests/integration/test_prepayment_settlement.py` (13):

- **Clearing closes the credit** (5) — `test_customer_refund_closes_credit` (refund to a bank asset), `test_customer_forfeit_to_income_closes_credit` (forfeit to income), `test_vendor_refund_received_closes_credit` (vendor returns the overpayment to a bank asset), `test_vendor_bad_debt_writes_off_credit` (write a vendor's unreturned overpayment off to an expense), `test_partial_refund_leaves_residual_credit` (smaller amount, residual stays open).
- **Rejections** (3) — `test_clearing_rejected_when_no_open_credit` (clearing-shaped split, nothing to reduce), `test_customer_lot_owner_on_ap_split_is_rejected` (owner type vs account-type mismatch), `test_lot_owner_guid_mismatch_is_rejected` (id↔guid disagreement is a hard error). Each leaves the book untouched.
- **Standalone credit** (2) — `test_standalone_credit_created_then_settled` (the `lot_owner:` create branch makes a credit with no invoice, then a second tx settles it), `test_clearing_roundtrips_into_fresh_book` (create + clear, export, re-import into a fresh book reaches the same settled state).
- **`open_prepayment:` summary** (3) — `test_open_prepayment_summary_in_export_accounts` (emitted by `export-accounts`), `test_open_prepayment_summary_roundtrips` (parsed and ignored on re-import; the credit is rebuilt from `lot_owner:`), `test_open_prepayment_mismatch_warns_but_does_not_fail` (a tampered amount warns to stderr, import still succeeds, book reflects reality).

`tests/integration/test_invoice_bad_debt.py` (3):

- `test_invoice_written_off_to_expense` — AR cleared, the amount booked to the bad-debt expense.
- `test_invoice_payment_to_income_is_rejected` — routing an invoice payment to income (a credit memo) is refused.
- `test_bill_payment_to_expense_is_rejected` — a bill has no bad-debt write-off; paying it to an expense is refused.

Twelve fixtures under `tests/fixtures/q_*.txt` (`q_refund_prepayment`, `q_customer_forfeit`, `q_vendor_refund`, `q_vendor_bad_debt`, `q_partial_refund`, `q_lot_owner_ap_mismatch`, `q_lot_owner_guid_mismatch`, `q_customer_only`, `q_standalone_credit`, `q_invoice_bad_debt`, `q_invoice_pay_to_income`, `q_bill_pay_to_expense`) follow the project convention of plaintext files on disk rather than inlined Python strings. The 45-test Q-014 orphan / payment-roundtrip suite and the broader 102-test parser + payment/prepayment guardrail set still pass, confirming the unified `lot_owner:` handler did not regress orphan reconstruction.

## Also on the branch (tooling, not feature)

- `scripts/test.sh`, `scripts/test-in-docker.sh`, `scripts/lint.sh`, `scripts/fix-lint.sh` — run the container as the invoking host user (`--user "$(id -u):$(id -g)"`, `HOME=/tmp/home`, per-user pip install) so workspace artifacts (`__pycache__`, `.pytest_cache`, `*.egg-info`) are no longer left root-owned, matching what `test-all-versions-parallel.sh` already did.
- `scripts/hooks/pre-commit` — skip the slow cross-version test suite for documentation-only commits (the AI review still runs).

## Out of scope

1. **Refunding an already-paid invoice months later** — that is a separate new transaction, not an unpost-and-refund, and is handled by ordinary ledger entry; this feature targets disposing of *open credits* and writing off *uncollectable* invoices.
2. **Bill "bad debt" as income** — forgiving a bill we owe is debt-forgiveness income, a different accounting event from money owed *to* us going uncollectable. A bill payment is therefore constrained to an asset account; expense (and income) are rejected.

## Related issues

- **Q-014** — introduced the `lot_owner:` per-split KVP for orphan-payment lot reconstruction. Q-021 folds that always-create handler into the unified join-or-create `_attach_lot_owner_split`; the 45-test Q-014 orphan / payment-roundtrip suite still passes, confirming no regression.
- **Q-015** — books overpayment credits into prepayment lots. Q-021 is the disposal side: the credits Q-015 creates are what `lot_owner:` clearing and the `open_prepayment:` summary now act on.
- **Q-016** — full GUID emission and import-order for payment round-trip. Q-021's clearing transactions and `lot_owner:` KVPs round-trip on top of that GUID continuity.
- **Q-004** — `txn_guid:` retarget. The "link an already-imported bank outflow into the clearing rather than duplicate it" path rides the same transaction-GUID identity.

---

**Created**: 2026-06-04
