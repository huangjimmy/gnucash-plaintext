# Bank Import Workflow with gnucash-plaintext

## The Problem

GnuCash users who manage invoices face a recurring conflict when importing bank
statements: the payment for an invoice may appear in two places simultaneously.

1. **GnuCash Apply Payment** — when you mark an invoice as paid, GnuCash creates
   a double-entry transaction internally:
   ```
   2026-03-15  Payment for INV-2026-001
     Assets:Bank:Chequing          +1,000.00 CAD
     Assets:Receivable:Client      -1,000.00 CAD
   ```

2. **Bank statement (OFX/QFX/CSV)** — your bank also records that same deposit:
   ```
   2026-03-15  TRANSFER REF 12345   +1,000.00 CAD
   ```

If both end up in GnuCash as separate transactions, you have double-counted the
deposit. Your bank account balance will be overstated by $1,000.

---

## Why GnuCash's Built-in OFX Importer Doesn't Fully Solve This

GnuCash's `File → Import → Import OFX/QIF` uses BAYES probabilistic matching to
detect if an imported bank entry already exists as a transaction. When it finds a
match, it marks the existing transaction as cleared (`c`) and discards the OFX
entry — no duplicate is created.

However, BAYES matching **frequently fails for invoice payments** because:

- Invoice payment transactions are created internally by GnuCash with generic
  descriptions like `"Payment"` or an invoice number
- These descriptions have no resemblance to the bank's memo text
  (`"TRANSFER REF 12345"`)
- BAYES has no training history to correlate them

When BAYES fails to match, GnuCash creates a second transaction from the OFX
entry, leaving you with a duplicate bank split and an `Imbalance` account entry
that needs manual cleanup.

---

## Why gnucash-plaintext Cannot Rely on Amount + Date Matching

A natural fallback is to match bank entries to existing transactions by
`(account, date, amount)`. This fails in practice because:

- Two customers can pay the same invoice amount on the same day
- Duplicate charges (e.g., two $50 grocery purchases in one day) are common
- There is no way to enforce import ordering — bank import may happen before or
  after Apply Payment

Any system that auto-matches on amount + date alone will produce silent wrong
matches in these cases.

---

## The Only Reliable Deduplication Key: FITID

Every OFX transaction contains a `<FITID>` field — the Financial Institution
Transaction ID. This is the bank's own unique identifier for the transaction. It
is stable, collision-free, and permanent.

The design principle: **FITID is the primary deduplication key. Nothing else is.**

- If a FITID has already been recorded in GnuCash (as a split KVP), the OFX entry
  is a duplicate and must be skipped entirely.
- If a FITID has not been seen, the OFX entry is new and should be imported.

Invoice payment transactions created by GnuCash's Apply Payment have no FITID.
This is the root of the conflict — the bank knows its FITID, but GnuCash's
payment record does not.

---

## Transaction States

Understanding three states helps reason about the workflow:

### State 1: Bank-anchored (OFX imported, not yet categorized)

The bank entry has been imported. The FITID is stored. The other side of the
transaction is `Imbalance` — a placeholder until the user categorizes it.

```
transaction 2026-03-15
  fitid: abc123
  memo: "TRANSFER REF 12345"
  split Assets:Bank:Chequing          +1000.00 CAD   reconcile=c
  split Imbalance:CAD                 -1000.00 CAD
```

### State 2: Categorized (Apply Payment done, not yet linked to bank entry)

The invoice payment transaction exists in GnuCash with proper accounts. The bank
split has not been matched to a bank statement entry — no FITID yet.

```
transaction 2026-03-15
  memo: "Payment for INV-2026-001"
  split Assets:Bank:Chequing          +1000.00 CAD   reconcile=n
  split Assets:Receivable:Client      -1000.00 CAD
```

### State 3: Fully linked (complete)

The transaction is categorized correctly and the FITID has been recorded. The
bank split is marked cleared. This is the final desired state.

```
transaction 2026-03-15
  fitid: abc123
  memo: "Payment for INV-2026-001"
  split Assets:Bank:Chequing          +1000.00 CAD   reconcile=c
  split Assets:Receivable:Client      -1000.00 CAD
```

---

## The Two Orderings

Since ordering cannot be enforced, both sequences must be handled.

### Ordering A: Apply Payment first, then import bank statement

1. You apply payment on invoice → State 2 transaction created in GnuCash
2. You later import the bank OFX file
3. FITID `abc123` is not found in GnuCash (the invoice payment has no FITID)
4. `import-bank` creates a State 1 transaction → now two bank splits for the same
   real-world deposit exist

Resolution: run `link-bank` (see below) to merge them into State 3.

### Ordering B: Import bank statement first, then apply payment

1. You import the bank OFX file → State 1 transaction created (Imbalance)
2. You later apply payment on the invoice
3. `apply-payment` (via gnucash-plaintext) detects an existing State 1 transaction
   for the same bank account, date, and amount
4. If exactly one candidate: re-categorizes it to State 3 (replaces Imbalance
   with AR, FITID already present)
5. If multiple candidates (same-day same-amount collision): flags for manual
   review — does not auto-resolve

> **Note**: Ordering B automatic resolution only works if `apply-payment` goes
> through gnucash-plaintext. If you use GnuCash's GUI Apply Payment, you will
> always end up needing the `link-bank` step.

---

## The Three Commands

> **Note:** `import-bank`, `apply-payment`, and `link-bank` are proposed
> commands — they do not exist yet in gnucash-plaintext. This section describes
> the intended design so that contributors and integrators can build toward it.

### `import-bank`

Imports OFX/QFX/CSV bank entries into GnuCash.

**Rules:**
- For each entry, check if the FITID is already stored in any split KVP in the
  target account. If yes: skip entirely (idempotent).
- If no FITID match: create a State 1 transaction with `Imbalance` as the other
  split. Store the FITID on the bank split's KVP.
- Never attempts to auto-match by amount or date.

**Result:** safe to run multiple times. Each OFX entry is imported at most once.
Uncategorized transactions accumulate as State 1 until resolved.

---

### `apply-payment` (gnucash-plaintext)

Applies a payment to an invoice and records it in GnuCash.

**Rules:**
- Look for existing State 1 transactions in the bank account with the same date
  and amount.
  - **Zero matches:** create a State 2 transaction normally.
  - **Exactly one match:** re-categorize it to State 3 — replace the Imbalance
    split with the AR split, and the FITID is already attached.
  - **Multiple matches:** create a State 2 transaction and write the ambiguous
    candidates to the `--needs-review` output. Do not auto-resolve.

---

### `link-bank`

A reconciliation pass that links State 1 and State 2 transactions to each other,
producing State 3.

This command handles all unresolved cases left by either ordering.

**What it does:**
1. Finds all State 1 transactions (have FITID, have Imbalance split).
2. Finds all State 2 transactions (no FITID, bank split reconcile=`n`).
3. For each State 1 transaction, finds State 2 candidates by `(bank account,
   date, amount)`.

**Resolution rules:**
- **Zero State 2 candidates:** the bank entry has no matching invoice payment.
  Leave as State 1. User must categorize it manually.
- **Exactly one candidate:** high-confidence match. Automatically resolve to
  State 3: copy FITID to the invoice payment's bank split, mark it `c`, delete
  the Imbalance transaction.
- **Multiple candidates (same date, same amount, same account):** output to
  review file. Do not auto-resolve.

**Review file format for ambiguous cases:**
```
AMBIGUOUS MATCH — manual resolution required
  Bank entry:    2026-03-15  FITID=abc123  memo="TRANSFER REF 12345"  +1000.00 CAD
  Candidate A:   GUID=aaa-111  "Payment INV-2026-001"  AR:Client:AcmeCorp
  Candidate B:   GUID=bbb-222  "Payment INV-2026-003"  AR:Client:OtherCorp

  Resolve with:
    gnucash-plaintext link-bank --fitid abc123 --guid aaa-111
```

---

## Summary: Which Cases Are Automatic vs Manual

| Scenario | Ordering | Auto-resolved? |
|---|---|---|
| Unique amount on the day, OFX first, `apply-payment` via gnucash-plaintext | B | Yes — on `apply-payment` |
| Unique amount on the day, Apply Payment first via GnuCash GUI | A | Yes — on `link-bank` |
| Same-day same-amount, any ordering | A or B | No — review file required |
| Bank entry with no invoice payment (e.g. bank fee) | — | No — user categorizes manually |
| OFX imported twice (same FITID) | — | Yes — skipped on second import |

---

## Reconciliation and the `y` Status

GnuCash tracks each split's reconciliation status:

- `n` — not reconciled (default for all new transactions)
- `c` — cleared (the split has been matched to a bank statement entry)
- `y` — reconciled (the split has been formally balanced against a closing
  statement balance and locked)

`import-bank` sets imported bank splits to `c`. `link-bank` promotes matched
splits from `n` to `c`. The `y` status is set later during GnuCash's formal
monthly reconciliation (`Actions → Reconcile`), where you verify the closing
balance of your statement. Nothing in this workflow skips that step — it remains
the authoritative final check.

---

## Building Interactive Tools on Top of gnucash-plaintext

gnucash-plaintext is intentionally non-interactive — it reads files and writes
files, with no prompts. This makes it scriptable and automation-friendly.

However, the `link-bank` review file is designed as a data contract that
higher-level tools can consume. A tool built on top of gnucash-plaintext can
implement an interactive matching experience:

1. Run `import-bank` and `link-bank --dry-run --output-review review.json`
2. Read the review file to find ambiguous or unmatched State 1 transactions
3. For each unmatched bank entry, ask the user:
   > "This deposit of $1,000.00 on 2026-03-15 (TRANSFER REF 12345) — is this
   > a payment for an invoice?"
4. If the user says yes, present a list of open invoices of that amount/currency
   and let them pick
5. Call `gnucash-plaintext link-bank --fitid abc123 --guid aaa-111` to resolve

This pattern lets any UI layer — a web app, a desktop app, a terminal TUI, or
even a chat-based assistant — drive the matching interactively, while
gnucash-plaintext handles the GnuCash book mutations safely.

The same pattern works for non-invoice categorization: "Is this $45.00 at SHELL
a fuel expense?" → user picks account → tool emits the correct plaintext
transaction and calls `import`.

### Demo: Interactive Matching by Date and Amount

A runnable demo is included at `demos/bank_import_matching/demo.py`. Run it
inside Docker from the repo root:

```bash
./scripts/run.sh latest bash /workspace/demos/bank_import_matching/run.sh
```

The demo:
1. Creates a temporary GnuCash book with sample accounts
2. Creates an invoice payment transaction (State 2 — no FITID)
3. Creates a bank OFX import transaction for the same amount (State 1 — FITID
   stored as metadata on the bank split)
4. Shows the conflict: two splits in the bank account for the same deposit
5. Runs interactive date + amount matching and asks you to confirm the link
6. On confirmation: transfers the FITID to the invoice payment split, marks it
   cleared, and removes the Imbalance transaction
7. Shows the resolved final state (State 3)

> **The date + amount matching in the demo is for illustration only.**
> Same-day same-amount collisions will produce wrong suggestions.
> You are responsible for implementing a matching strategy appropriate
> for your data. The demo shows the shape of the interaction — not a
> production-ready algorithm.

---

## Practical Recommendation

For users managing invoices and bank imports together:

1. Use `import-bank` for all bank OFX/QFX/CSV imports. Do not use GnuCash's
   built-in importer for accounts where you also use Apply Payment.
2. Use `apply-payment` via gnucash-plaintext rather than GnuCash's GUI, so the
   system can detect existing State 1 transactions automatically.
3. Run `link-bank` after any batch of imports or payments to resolve remaining
   State 1 / State 2 pairs.
4. Check the review file for any ambiguous cases and resolve them with the
   provided command.
5. Perform monthly reconciliation in GnuCash as usual to promote `c` → `y`.
