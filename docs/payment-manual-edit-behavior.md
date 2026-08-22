# Payment / lot behavior when the book and plaintext have diverged

This project models plaintext as the source of truth, with `import` and `export` as the only sanctioned ways to move data between the two. In practice the two can drift apart for several reasons:

- the user opens the `.gnucash` file in the GnuCash UI and hand-edits a payment transaction or split,
- another tool (a QFX importer, a third-party reporting utility, a script using `gnucash_core_c` directly) modifies the `.gnucash` file behind our back,
- the user opens the `.txt` plaintext file in a text editor and deletes / changes a `payment:` or `entry:` block before re-importing.

None of these are "supported" workflows in the sense that round-trip is guaranteed, but they all happen. This note records what `gnucash-plaintext import` does in each divergence scenario so the user knows what to expect.

## Plaintext-side edits

Direct edits to the `.txt` file before re-import are well-tested by the Q-015 integration suites — re-importing reconciles the book to whatever the plaintext now says, either via the Q-015 add-payment fast path (entries / payments / posted block all match, only new `payment:` blocks appended) or via the destructive rebuild path with an orphan-payment warning emitted to stderr for every bank-side payment about to be detached. See `tests/integration/test_incremental_payment_reimport.py` and `tests/integration/test_importer_destructive_orphan.py` for the full matrix.

**One edit is refused rather than reconciled**: a change to what a **posted** invoice's or bill's lines say — a description, a quantity, a price, a tax table, a line added or removed. Rebuilding a posted one would unpost it, destroy and rebuild its lines, post it again under a new transaction, and leave its payments settling a transaction that no longer exists. The message names the way through — `unpost-invoices <book> <id>` (or `unpost-bills`), then the import. Everything else about a posted invoice or bill still reconciles: its notes, its billing id, its custom keys, and an appended `payment:` block.

## Book-side edits (GnuCash UI or external tools)

All book-side scenarios below assume the canonical setup:

- **INV-001** for $100, **paid $150** → bank tx `T1` for $150; AR has two lots — the invoice lot (closed, balance $0) and a pre-payment lot (open, balance −$50).
- **INV-002** for $100, **paid $60** → bank tx `T2` for $60; AR lot still open at +$40.
- Original plaintext expresses both invoices including their payments and the `prepayment: 50` on INV-001.

| # | Manual edit in GnuCash UI | What the book looks like after the edit | What re-import does | Outcome |
|---|---|---|---|---|
| 1 | Delete the **bank-side split** of T2 (the $60 partial payment) | T2 becomes unbalanced; GnuCash auto-adds an `Imbalance-CAD` split as the replacement bank side | Importer's matcher compares the directive's `bank_account: "Assets:Bank"` to T2's actual non-AR split, finds `Imbalance-CAD`, returns False. The Q-015 orphan warning fires naming the Imbalance-CAD split, the destructive rebuild runs, ApplyPayment re-creates a clean $60 bank tx. | Recovered. User sees the warning and the resulting orphan-cleanup advice; the original Imbalance-CAD entry remains in the book until the user explicitly deletes it. |
| 2 | Delete the **prepay AR split** (the −$50 on T1) | T1 becomes unbalanced (bank +$150 vs. AR −$100); the pre-payment lot empties; GnuCash may add an Imbalance-CAD split to T1. | Matcher computes actual prepayment = $0, directive declares `prepayment: 50` — mismatch. Orphan warning fires for T1 ($150), destructive rebuild runs, ApplyPayment re-creates the overpayment correctly with both lots. | Recovered. The warning correctly names T1 as the orphan. |
| 3 | Destroy T2 entirely (delete both the bank and the AR splits) | T2 gone. INV-002 lot reverts to just the +$100 posting, balance +$100 (back to unpaid). | Q-015 **add-payment fast path** fires (existing lot has zero payments, directive has one) → applies the $60 via `ApplyPayment` on the still-posted invoice. No Unpost, no destructive rebuild. | Clean recovery. No orphan, no warning, posting/entry GUIDs preserved, single new bank tx for $60. |
| 4 | Destroy INV-001's posting transaction directly | No-op — GnuCash silently blocks direct `Destroy()` on a transaction belonging to a posted invoice. The user *can* unpost from the UI; that produces the same state as our `unpost-invoices` CLI and a subsequent re-import follows scenario 2/3 as appropriate. | Re-import sees nothing changed. | N/A — the UI's "Unpost" is the only practical path; re-importing afterwards goes through the Q-014 orphan warning if the invoice had payments. |
| 5 | Delete only the **AR-side split** of T2, keep the bank-side intact | INV-002 lot reverts to balance +$100 (only the posting remains in the lot); T2 still has the +$60 bank split paired with whatever auto-replacement GnuCash created on the other side. | Q-015 fast path sees lot has zero payments, directive has one → applies a new $60 payment via `ApplyPayment`. A *new* $60 bank tx is created on top of the existing T2 (which is now functionally orphaned). | **Recovers the invoice state but leaves a duplicate $60 bank tx.** This is fringe — the user explicitly mutated split structure outside the importer. The duplicate is discoverable via `find-orphan-payments` (the original T2's AR-side fragment may now be classified as an orphan depending on what auto-replacement GnuCash inserted) or by scanning the bank for unexplained txs. |

## What the importer guarantees vs. doesn't

**Guaranteed:**

- Any time the matcher detects an inconsistency between the directive and the book (account / amount / memo / prepayment / count), the destructive rebuild path fires *with* the Q-014-style orphan warning that names every bank-side payment about to be left dangling. The user always sees what's about to be silently lost.
- Scenarios where the user deleted whole payment transactions outside the importer are recovered cleanly by the Q-015 add-payment fast path — the missing payments are re-applied without rebuilding the invoice/bill.

**Not guaranteed:**

- Single-split surgery (deleting only one side of a balanced transaction, leaving the other half stranded) can leave the book with duplicates after re-import. The importer reasons about lot membership and matches against the in-lot splits; it does not actively scan for "orphaned half-transactions" that lack a counterpart on the lot side.
- The exact account name in the warning depends on what GnuCash chose for its auto-balancing split. On Linux this is typically `Imbalance-CAD` (or whatever the book currency is); the warning surfaces that name verbatim so the user can locate it in the GnuCash UI.

## Recommendation for users

If you must edit a payment in the GnuCash UI, prefer deleting and re-creating the entire payment transaction (scenario 3) over per-split surgery (scenarios 1, 2, 5). The plaintext re-import will then cleanly re-apply the missing payment without leaving behind half-deleted artifacts.

## Q-016 — what changes for re-imports after Q-016

Q-016 made every bank-tx and per-split GUID round-trip natively. The scenarios above (book-side hand-edits in the GnuCash UI) still produce the same recovery shape — the matcher still detects the divergence, the Q-014/Q-015 orphan warning still fires, and the destructive rebuild path still re-applies the payment cleanly. What changes is what survives across a clean `import → export → import-into-fresh-book` cycle when no manual edits happen between exports:

- Standalone bank transactions carry their `guid:` and every split carries its own `guid:` in exported plaintext, so a fresh re-import reconstructs the same transaction objects (same GUIDs) rather than auto-assigning new ones.
- Every `payment:` block carries `txn_guid:` (the bank tx) and `txn_split_guid:` (the specific AR/AP-side split that belongs to this invoice/bill). The fresh-book importer attaches that exact split to the invoice's posted lot — no inference, no order-dependence, no destructive rebuild needed.
- The one-bank-transaction-covering-multiple-invoices shape (which used to require the Q-015 `prepayment:` + `auto_apply_credit:` workaround) round-trips natively: each invoice's `payment:` block claims its own `txn_split_guid:`.

The divergence-recovery scenarios in this note are still correct — they document what the importer does when the book and the plaintext genuinely differ. Q-016 is about the *no-divergence* case (clean round-trip) being deterministic; the manual-edit scenarios continue to fall through to the rebuild path with the orphan warning.

