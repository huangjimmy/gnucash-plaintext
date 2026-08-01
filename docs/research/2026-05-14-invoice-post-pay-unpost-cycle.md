# Invoice post → pay → unpost → re-post → re-pay: what actually happens

**Date:** 2026-05-14
**Author:** research run on `feature/research-invoice-post-pay-unpost-cycle`
**Harness:** `tests/research/test_post_pay_unpost_cycle.py`
**Snapshots:** `exports/invoice_created.txt`, `invoice_posted.txt`, `invoice_paid.txt`, `invoice_unposted.txt`, `invoice_reposted.txt`, `invoice_repaid.txt`
**Diffs:** `exports/diff_created_to_posted.patch` … `exports/diff_reposted_to_repaid.patch`
**Entry-GUID trace:** `exports/invoice_entry_guid_trace.json`
**Refreshing them:** `GNC_WRITE_EXPORTS=1 ./scripts/test.sh latest tests/research/` — an ordinary test run writes its snapshots to a scratch directory, since each run stamps a fresh date and fresh GUIDs and would otherwise leave these files permanently modified.

## TL;DR

**Re-paying an invoice after unposting it leaves a duplicate, invisible bank-side transaction in the books and breaks plaintext round-trip.** `unpost-invoices` destroys the AR posting transaction and unlinks the payment split from any lot, but the bank-side `2026-01-15 * "Acme"` transaction itself is *not* deleted. Re-posting the invoice and applying a new payment creates a brand-new bank transaction, leaving the orphan behind in the bank account. The plaintext exporter writes both bank transactions in the `transactions` section but the invoice's `payment:` block only references the new one. Net result after the full cycle for a single $100 invoice paid once: **AR balance −$100 (phantom credit), Bank balance +$200 (double-counted deposits), Income $100, and a plaintext file that, when round-tripped, reconstructs only one of the two bank deposits.** Entry GUIDs are also regenerated on every re-import that changes anything except `posted: { ... } → posted: none` — only the dedicated `unpost-invoices` CLI preserves them.

## Scenario setup

Single CAD-only book, one customer, one invoice with one un-taxed entry. Accounts:

```
Assets
  Assets:Bank                  (Bank)
  Assets:Accounts Receivable   (A/Receivable)
Income
  Income:Sales                 (Income)
```

The invoice has one entry: 1 unit × $100 at `Income:Sales`, posting to `Assets:Accounts Receivable` on 2026-01-01. The first payment is $100 on 2026-01-15 from `Assets:Bank`. The second payment (step F) is also $100 from `Assets:Bank`, but dated 2026-02-15 so it shows up as a clearly distinct bank transaction.

All six steps were driven by a single pytest run inside the `gnucash-dev:latest` (debian:13 / GnuCash 5.10) Docker image, with a `time.sleep(1)` between each `import` to avoid the `ERR_FILEIO_BACKUP_ERROR` silent-drop issue documented in CLAUDE.md.

Stable GUIDs across the entire cycle:

| Object | GUID (from this run) | Notes |
|---|---|---|
| Customer `C001` | `17b563c1985d446f9ba4e712dc93c5aa` | unchanged A→F |
| Invoice `INV-001` | (book-specific; unchanged A→F) | unchanged A→F |
| Account `Assets:Accounts Receivable` | `8bdd7730da6e45f8b03a28e8185e2903` | unchanged A→F |
| Account `Assets:Bank` | `69e09c4807814639a04f9db9386898e3` | unchanged C→F (only appears once Bank has a tx) |
| Orphan bank payment tx | `63210942c2d84dde959e4ac640f57c3e` | created in C, survives D, E, F unchanged |

## Step-by-step (with diff evidence)

### A → B: posting

The .txt changes `posted: none` to a `posted: { … }` block. The diff inserts the full accounts section (commodity, four account-`open` declarations) plus one new transaction:

```
+2026-01-01 * "INV-001" "Invoice INV-001"
+	guid: "2e1da9a4f81443528829425d830f2baa"
+	notes: "business_generated: true"
+	Assets:Accounts Receivable 100.00 CAD
+		action: "Invoice"
+		memo:"Invoice INV-001"
+	Income:Sales -100.00 CAD
+		action: "Invoice"
+		memo:"Invoice INV-001"
```

Sign convention: AR is debited (+100, asset increases), Income is credited (−100, equity-style income increases). Standard double-entry.

> **Why the accounts section only appears in step B and not in step A:** the exporter (`use_cases/export_transactions.py`) emits only the accounts that are *touched by a transaction in the result set*. Step A has no transactions, so it has no accounts in the export either — even though the book contains all five Asset/Income accounts created at the `--new` import. This is worth noting on its own (see "Implications for the codebase").

### B → C: paying

The `payment: { … }` block appears under the invoice and **two** new records appear in the transactions section: a bank account-`open` line for `Assets:Bank` (because Bank now has a transaction), plus the payment transaction:

```
+2026-01-15 * "Acme"
+	guid: "63210942c2d84dde959e4ac640f57c3e"
+	Assets:Bank 100.00 CAD
+		action: "Payment"
+		memo:"Payment INV-001 (first)"
+	Assets:Accounts Receivable -100.00 CAD
+		action: "Payment"
+		memo:"Payment INV-001 (first)"
```

The payment tx debits Bank +100 (asset increases — money received) and credits AR −100 (asset decreases — receivable cleared). The two splits sum to zero, closing the AR lot.

**Surprise**: the existing posting transaction's GUID changes from `2e1da9a4…` to `6fae2d73…` even though the entry, the posted block, and the date are all unchanged. The importer takes the "destroy-and-rebuild" path whenever any part of the directive differs from the existing record except for the special-cased `posted: { ... } → posted: none` minimal unpost. Adding a `payment:` block counts as "differs", so the whole invoice is rebuilt and the posting tx is recreated.

The new bank-side payment transaction is in the same lot as the (rebuilt) posting transaction.

### C → D: unposting (via `unpost-invoices` CLI)

Invoked as `gnucash-plaintext unpost-invoices <book> INV-001`. The diff is the key result of this whole research:

**What gets removed:**

```
-2026-01-01 * "INV-001" "Invoice INV-001"
-	guid: "6fae2d73f6ad459381df5c8ffa054db2"
-	notes: "business_generated: true"
-	Assets:Accounts Receivable 100.00 CAD
-	Income:Sales -100.00 CAD
```

— the posting transaction itself is destroyed.

```
-	posted:
-		date: 2026-01-01
-		due: 2026-01-31
-		ar_account: "Assets:Accounts Receivable"
-		memo: "Invoice INV-001"
-		accumulate: true
-	payment:
-		date: 2026-01-15
-		amount: 100
-		bank_account: "Assets:Bank"
-		memo: "Payment INV-001 (first)"
+	posted: none
+	payment: none
```

— the invoice's plaintext form reverts to its A-state body: `posted: none`, **`payment: none`**. The payment block disappears even though the underlying bank transaction does not (next bullet).

```
-2026-01-01 open Assets:Accounts Receivable
-2026-01-01 open Income
-2026-01-01 open Income:Sales
```

— `Income` and `Income:Sales` vanish from the accounts section entirely, because no remaining transaction references them. (The accounts still exist in the book — they're just not in the export's emit set.)

**What survives:**

```
 2026-01-15 * "Acme"
 	guid: "63210942c2d84dde959e4ac640f57c3e"
 	Assets:Bank 100.00 CAD
 	Assets:Accounts Receivable -100.00 CAD
```

— the bank-side payment transaction is **completely untouched**. Both splits — Bank +100 and AR −100 — remain, same GUID as in step C. The AR account therefore retains a −100 balance from this orphan: an unmatched credit with no corresponding posted invoice.

This is the documented behaviour (`cli/unpost_cmd.py` help text: *"splits attached to the AR/Bank/etc. account remain but become orphaned"*), but the consequences for the rest of the cycle are significant.

### D → E: re-posting

Re-importing the step-B fixture against the unposted invoice creates a new AR posting transaction:

```
+2026-01-01 * "INV-001" "Invoice INV-001"
+	guid: "d749c5bc49ac4a48b69163fba84d7f27"
+	Assets:Accounts Receivable 100.00 CAD
+	Income:Sales -100.00 CAD
```

GUID `d749c5bc…` — different from the original B-state posting GUID (`2e1da9a4…`) and from the C-state rebuild (`6fae2d73…`). GnuCash does **not** reattach to anything: this is a brand-new transaction in a brand-new lot. The previously-orphaned bank tx (`63210942…`) is *not* re-linked to the new lot — it stays orphaned. The invoice's payment block remains `payment: none`.

The accounts section flips back to including `Income` and `Income:Sales` since Income is now referenced by a transaction again.

### E → F: re-paying

The .txt now carries a second payment block (`date: 2026-02-15`, amount 100, same bank account). The diff:

```
-	payment: none
+	payment:
+		date: 2026-02-15
+		amount: 100
+		bank_account: "Assets:Bank"
+		memo: "Payment INV-001 (second, after re-post)"
```

```
+2026-02-15 * "Acme"
+	guid: "27dd6e0d507d41d7807e6560777ea8a5"
+	Assets:Bank 100.00 CAD
+	Assets:Accounts Receivable -100.00 CAD
```

The new bank transaction is *additional* — the orphan `2026-01-15` tx is still there with its original GUID `63210942…`. The book now contains:

| Tx | Date | Bank | AR | Income | In invoice's payment block? |
|---|---|---|---|---|---|
| Posting (re-post) | 2026-01-01 | — | +100 | −100 | n/a (it's the posting) |
| Orphan payment   | 2026-01-15 | +100 | −100 | — | **no** |
| New payment      | 2026-02-15 | +100 | −100 | — | yes |

**Net balances at the end of step F:**

- Bank: +200 (double-deposit on the same $100 invoice)
- AR: 100 − 100 − 100 = −100 (phantom credit)
- Income: −100 (single sale, correct)

The book still balances arithmetically — every transaction balances, the orphan included — but the *meaning* of the balances is wrong.

## Answers to the six research questions

### 1. What posting creates (A→B)

A single new transaction touches `Assets:Accounts Receivable` (+100) and `Income:Sales` (−100), dated by the `posted.date` field (2026-01-01). Sign convention is standard double-entry: AR debited (asset up), Income credited (income up). The transaction also carries `notes: "business_generated: true"` and per-split `action: "Invoice"` / `memo: "<the posted block's memo>"`. The bank account is not touched.

The transaction GUID lives only in the exporter output (`guid: "2e1da9a4…"`); the invoice itself has no separate field tying it back to this transaction in the plaintext form — the linkage is GnuCash's internal lot/posting machinery, recovered on re-import via the `posted.date` and `ar_account`.

### 2. What paying does (B→C)

`ApplyPayment(amount=+100)` produces one new transaction dated by `payment.date`: `Assets:Bank` (+100) and the AR account (−100). The payment-side AR split is the *negative* of the posting AR split, so the two splits sum to zero in the same lot — that's how GnuCash marks the invoice paid.

A `payment:` block does **not** cross-reference an existing transaction unless you give it a `txn_guid:` (the Q-004 retarget path). Without `txn_guid`, a brand-new transaction is created on every payment-side import. With `txn_guid`, the existing bank tx's counter-split is retargeted to the AR account in place — see `payment_roundtrip_invoice_txn_guid.txt` and the dedicated `test_payment_roundtrip.py` tests.

A side effect of adding a payment block: the importer rebuilds the invoice, and the posting transaction's GUID changes (`2e1da9a4…` → `6fae2d73…`).

### 3. What unposting does to the posting transaction and the payment (C→D)

- **AR/Income posting transaction:** destroyed. The transaction disappears from `transactions:` entirely; the GUID is gone.
- **Bank payment transaction:** *not* destroyed. The transaction object with both its Bank and AR splits remains in place, same GUID (`63210942…`). It is "orphaned" in the GnuCash sense that it's no longer attached to a lot, but it is still a perfectly valid transaction from the book's perspective. Both splits — bank-side *and* AR-side — survive.
- **`payment:` line in the invoice's plaintext:** **gone**. The exporter renders unposted invoices with `payment: none` and does not back-reference orphan payment transactions, even when they obviously came from this invoice. See `services/gnucash_exporter.py` — orphan bank txs are emitted in the `transactions:` section only, not in any business object.

The book is therefore in an asymmetric state: the bank ledger and the AR ledger both still "see" the payment as money received, but the invoice has no idea any payment ever existed.

### 4. What re-posting does on a previously-posted-and-unposted invoice (D→E)

GnuCash creates a brand-new AR posting transaction with a new GUID (`d749c5bc…`), distinct from the original (`2e1da9a4…`) and from the intermediate rebuild (`6fae2d73…`). The new transaction is in a **new lot**. GnuCash does **not** reattach the orphaned bank tx (`63210942…`) to this new lot. The dates, accounts, amounts, and memo all match the original posting transaction (since the directive matches), but it is a different transaction object.

Date/memo/amount on the new posting are *byte-identical* to the original — the only field that distinguishes them is the GUID.

### 5. What paying again does (E→F)

The second payment block creates a **brand-new** bank transaction (`27dd6e0d…`) dated 2026-02-15. It does *not* merge with the orphan bank-side split from step C (`63210942…`, dated 2026-01-15) — the orphan is in no lot, has no `txn_guid` link to the directive, and GnuCash's idempotency check (Q-004) keys on date+amount+account, so a different-dated payment is always treated as new.

Compared to the paid state, the bank account after re-paying has **two** entries of +100 instead of one. Quote from `invoice_repaid.txt`:

```
2026-01-15 * "Acme"
	guid: "63210942c2d84dde959e4ac640f57c3e"
	Assets:Bank 100.00 CAD
		action: "Payment"
		memo:"Payment INV-001 (first)"
	Assets:Accounts Receivable -100.00 CAD
		action: "Payment"
		memo:"Payment INV-001 (first)"
2026-02-15 * "Acme"
	guid: "27dd6e0d507d41d7807e6560777ea8a5"
	Assets:Bank 100.00 CAD
		action: "Payment"
		memo:"Payment INV-001 (second, after re-post)"
	Assets:Accounts Receivable -100.00 CAD
		action: "Payment"
		memo:"Payment INV-001 (second, after re-post)"
```

If the user re-imports this exported plaintext into a fresh book, only the 2026-02-15 payment is reconstructed (it's the only one inside the invoice's `payment:` block). The 2026-01-15 orphan is *not* in any business-object block — it is only carried in the free-form `transactions:` section, and the importer's business-object pass won't recreate it as a payment of `INV-001`.

In short: **the re-pay-after-unpost cycle is non-idempotent and plaintext round-trip is lossy.**

### 6. Entry GUIDs across the cycle

Recorded by reading the book directly at each step (the plaintext export doesn't emit entry GUIDs). Full trace in `exports/invoice_entry_guid_trace.json`:

| Step | Entry GUID for INV-001's single entry |
|---|---|
| A | `dcd1bd5f5db44897be1cae7956d60754` |
| B | `ae0e9e768cbf4654b7fe5bf5f4dba14b` |
| C | `1c303806f9af4c3095ecd84dfd35138a` |
| D | `1c303806f9af4c3095ecd84dfd35138a` ← **same as C** |
| E | `09f7962b52914d0bad003ae79d5827f3` |
| F | `5db491a9787e40a7b827530aab9f38de` |

Five distinct GUIDs across six steps. The only preserved transition is **C → D**, which is the `unpost-invoices` CLI path — exactly matching the Q-010 spec ("Entry GUIDs are preserved — non-destructive on entries"). Every other transition — including A→B (add a posted block to an unposted record), B→C (add a payment), D→E (re-post), E→F (add another payment) — goes through the destroy-and-rebuild path in `services/gnucash_importer.py` and regenerates the entry GUID.

For consumers relying on entry GUIDs for stable references (e.g. a PDF render pipeline that caches entry-level data), only the `unpost-invoices` / `unpost-bills` paths and the minimal `posted: { … } → posted: none` re-import (per `tests/integration/test_unpost_invoice_bill.py`) provide stability. Anything else is best treated as a fresh entry.

## Implications for users

1. **Treat `unpost-invoices` as a destructive operation against the bank ledger, not just against the invoice.** It does not remove the bank-side payment transaction. If you intend to redo the payment, you must manually delete the orphan bank transaction first — currently via the GnuCash UI or a future `delete-transactions` flow (no CLI exists for orphan-payment cleanup as of this branch).

2. **Re-paying after unposting will silently duplicate your bank deposit if you don't clean up the orphan first.** The book will still balance, so reconciliation against a bank statement won't catch it — both halves of the duplicate are journal-internal. The user-visible symptoms are: AR balance goes negative on a "paid-in-full" customer, and total bank deposits exceed total recorded income.

3. **Don't round-trip a book through plaintext after this kind of cycle and assume it's lossless.** The orphan bank tx survives an export but does **not** reattach to the invoice on re-import. Re-importing the exported `.txt` into a fresh book gives you the 2026-02-15 payment only; the 2026-01-15 orphan is reconstructed as a free-standing bank transaction, but it won't be associated with the invoice's lot. Plaintext is a reasonable backup format for a *clean* book, but not for a book that has unposted records with surviving payment splits.

4. **If you want a re-pay-after-unpost workflow that doesn't duplicate, use the `txn_guid:` retarget pattern** (Q-004, `payment_roundtrip_invoice_txn_guid.txt`): leave the orphan bank tx alone, set `txn_guid: "<that orphan's guid>"` inside the new `payment:` block, and `ApplyPayment` will retarget the orphan's AR-side split into the new posted lot instead of creating a second tx. This is the only currently-supported way to re-link the orphan without duplication.

## Implications for the codebase

These are candidate issues, not commitments — flagged for review.

1. **No CLI guard against the duplicate-payment trap.** Q-010 documents that `unpost-invoices` orphans the bank-side split, and `cli/unpost_cmd.py` hints at a future "destroy orphan payment txns" cleanup ("can add a 'destroy orphan payment txns' cleanup if that turns out to be common"). This research is evidence that *it is common* — any post → pay → unpost → re-post cycle that re-imports a new `payment:` block (rather than the `txn_guid:` retarget) hits the trap silently. Options:
   - Print a warning at unpost time: *"N orphan payment transactions remain in the bank account; re-paying without `txn_guid:` will create duplicates"*.
   - A new `--cleanup-payments` flag on `unpost-invoices` that deletes the bank-side splits along with the AR posting.
   - A new top-level `cleanup-orphan-payments <book> <invoice-id>` command.

2. **Plaintext export loses orphan-payment provenance.** The exporter writes the orphan bank tx into `transactions:` with nothing recording that it *used to be* an invoice payment. The receiving importer has no way to reattach it on round-trip. Options:
   - On export, include the orphan tx's original posted-lot-pre-unpost association (e.g. as a `notes:` entry `originally_paid: "INV-001"` or via a KVP slot).
   - Surface orphan payments under the invoice's `payment:` block with a `orphan: true` flag so the user at least *sees* it in plaintext and can decide to re-link with `txn_guid:` on re-import.
   - Document the limitation in `docs/invoice-payment-reconciliation.md`.

3. **Accounts-section emission is transaction-driven.** Steps A and D omit account-`open` lines for accounts that exist in the book but have no transactions in scope. This is not a bug per se (`--all-accounts` opts in to full emission), but it surprised the research — going from B to D, four accounts visibly disappear from the export even though none of them was deleted. Worth a note in the export-command docstring, or worth flipping the default for `--include-business-objects` mode (since "import-ready" output should presumably include all accounts).

4. **Entry-GUID stability is brittle.** Only the C→D transition (Q-010 CLI unpost) and the minimal `posted: { ... } → posted: none` re-import preserve entry GUIDs. Any other re-import that touches the invoice — even a `payment:`-only change that leaves the entries themselves byte-identical — destroys-and-rebuilds. This is fine for the in-place editing flow that the importer was designed for, but it is a gotcha for any downstream tooling that wants to *reference* entries by GUID (e.g. a PDF cache, a per-entry tax note, an external ID mapping). Recommendation: add a note to Q-010 or the importer module docstring spelling out exactly which transitions preserve entry GUIDs, and document the import-summary status for these transitions (Q-009 / Q-010).

5. **`payment: none` after unpost is misleading.** From the plaintext file's perspective after `unpost-invoices`, the invoice looks pristine — `posted: none`, `payment: none`. But the book it came from still has a bank deposit that the invoice used to pair with. The natural intuition ("I unposted, so the invoice is back to draft and the payment is gone") doesn't match reality ("I unposted, the invoice is back to draft but half the payment transaction is still floating around"). At a minimum this should be called out in the `unpost-invoices` help text; at most, the export could render the orphan as a *paint-on* payment in the invoice's block (see point 2 above).

## Cross-references

- **Q-004** — `docs/issues/Q-004-payment-transaction-duplicates.md`. Defines the `txn_guid:` retarget mechanism that this cycle's duplicate-payment trap could use as a workaround.
- **Q-009** — `docs/issues/Q-009-import-summary-business-objects.md`. The import summary should probably distinguish "re-posted via rebuild" from "unchanged" — this research observed several destroy-and-rebuild transitions that report as `updated`.
- **Q-010** — `docs/issues/Q-010-strict-updated-status-on-no-change-reimport.md` and `cli/unpost_cmd.py`. The CLI help text already mentions the orphan-payment caveat; this research shows the downstream cost.
- **Q-012** — `docs/issues/Q-012-print-invoice-on-unposted-invoice-crashes.md`. Step D leaves the invoice unposted; `print-invoice` against it would have crashed before Q-012's fix.
- **Q-013** — `docs/issues/Q-013-delete-unposted-invoice-bill.md`. Provides `delete-invoices` for the unposted record after step D, which is half of a "true clean slate" cycle — the other half (delete the orphan bank tx) is still missing.
- **Q-014** — `docs/issues/Q-014-orphan-payment-warning-on-unpost.md`. Implements the "print a warning at unpost time" recommendation from this research's "Implications for the codebase" section — `unpost-invoices` and `unpost-bills` now list the orphan bank transactions about to be created, with GUIDs, accounts, and amounts.
- **Q-015** — `docs/issues/Q-015-incremental-payment-reimport-rebuilds-destructively.md`. Closes the entry-GUID stability gap surfaced in this research (any `payment:`-only change destroyed-and-rebuilt entries) via the add-payment fast path, and extends the Q-014 orphan warning to every importer-side `Unpost(False)` callsite — so the "destroy-and-rebuild silently orphans bank txs" scenarios observed here now print the same warning the dedicated unpost CLI does.
- **Q-016** — `docs/issues/Q-016-full-guid-emission-and-import-order-for-payment-roundtrip.md`. The plaintext-export gaps observed in step F (the orphan bank tx is emitted in the `transactions:` section but the invoice's `payment:` block only references the new bank tx) and the re-import gaps (re-importing the exported plaintext into a fresh book reconstructs only one of the two bank deposits) are addressed at the format level: exported `payment:` blocks always carry `txn_guid:` and `txn_split_guid:`, standalone bank-tx blocks carry per-split `guid:` on every split (mirroring the transaction-level `guid:`), and the importer processes standalone transactions before invoices/bills so a single `import` call resolves the references. The destructive-rebuild scenarios this research described — including the one-bank-tx-covering-many-invoices shape — round-trip cleanly into a fresh book after Q-016 lands.

## Repro

```
./scripts/test.sh latest tests/research/test_post_pay_unpost_cycle.py
```

The test is intentionally over-asserting at the "smoke" level; it locks in the *current* behaviour of the six-step cycle so a behavioural change (e.g. orphan cleanup added to `unpost-invoices`) will surface in the test diff.

Snapshots and diffs are checked in alongside this doc for review.

## Follow-up: can we track the orphan?

**Headline:** Yes — the orphan is reliably identifiable as "a payment transaction from customer C001", but **not** as "the payment for INV-001 specifically". The lot → invoice association is destroyed by unpost, but the transaction's KVP-backed owner reference (`gncOwnerGetOwnerFromTxn`) and the lot's owner reference (`gncOwnerGetOwnerFromLot`) both survive. The strong fix is to list the soon-to-be-orphans *before* the unpost completes — at that point the lot still points at the invoice and the result has zero false positives.

Probe code: `tests/research/test_orphan_detection_probe.py`. Full backref dump: `exports/orphan_backref_probe.txt`. Both prototypes are exercised by the `test_find_orphan_payments_prototype` test in the same file and pass against the fixture.

### 1. Backreferences on the orphan bank tx (pre-unpost)

Probed every field listed in the prompt plus a few extras. From `exports/orphan_backref_probe.txt`:

| Candidate | Pre-unpost value | Strength as a backref |
|---|---|---|
| `xaccTransGetDescription` | `'Acme'` (customer name) | weak — identical for every payment from this customer |
| `xaccTransGetNotes` | `None` | useless — GnuCash never sets it for `ApplyPayment` txs |
| `xaccTransGetTxnType` | `'P'` | strong filter (excludes manual deposits, which are `'N'`) but doesn't identify *which* invoice |
| `gncInvoiceGetInvoiceFromTxn(tx)` | `None` (NULL) | useless — that function is for invoice-posting txs (`'I'`), not payment txs (`'P'`). Worth ruling out explicitly; the project's `gncInvoiceGetInvoiceFromTxn` already exists in the SWIG bindings and would be a tempting wrong choice |
| **`gncOwnerGetOwnerFromTxn(tx, &owner)`** | **owner.id = `'C001'`, owner.name = `'Acme'`, owner.type = 2 (Customer)** | **strong** — KVP-backed customer reference set by `gncOwnerApplyPayment`, returns the Customer/Vendor authoritatively |
| Bank split `memo` | `'Payment INV-001'` | medium — *the user wrote it*. In our fixture the memo happened to contain the invoice ID; the importer just forwards `payment.memo` from the directive to `ApplyPayment` (`services/gnucash_importer.py`). A user who set `memo: "Jan rent"` would erase this signal. Likewise, payments applied via the GnuCash UI carry whatever string the user typed in the Memo field |
| Bank split `action` | `'Payment'` | medium — defaulted by `ApplyPayment`; user can change it via the GnuCash UI but rarely does. Equivalent in selectivity to `txn_type == 'P'` |
| AR split `memo` | `'Payment INV-001'` | same source/strength as bank split memo |
| AR split `action` | `'Payment'` | same as bank split action |
| AR split `xaccSplitGetLot` | non-NULL lot ptr | strong reference for the AR side of the payment |
| **`gncInvoiceGetInvoiceFromLot(arSplit.lot)`** | **`'INV-001'`, guid `969f5164…`** | **gold standard** — authoritative invoice backref. *Pre-unpost only.* |
| `gncOwnerGetOwnerFromLot(arSplit.lot, &owner)` | None (lot is invoice-attached pre-unpost) | not useful pre-unpost; surprising result post-unpost (see below) |

### 2. Survival across unpost

The probe dumps the same fields again after `unpost-invoices INV-001`. The `* lines` in the dump are the changes:

| Field | Pre | Post | Survives? |
|---|---|---|---|
| `description` | `'Acme'` | `'Acme'` | ✓ |
| `notes` | `None` | `None` | ✓ (was never set) |
| `txn_type` | `'P'` | `'P'` | ✓ |
| `tx_guid` | `cf230c62…` | `cf230c62…` | ✓ (same tx) |
| `invoice_from_txn_id` | `None` | `None` | n/a |
| **`owner_from_txn_id`** | **`'C001'`** | **`'C001'`** | **✓ — the KVP owner backref survives** |
| `owner_from_txn_name` | `'Acme'` | `'Acme'` | ✓ |
| `owner_from_txn_type` | `2` | `2` | ✓ |
| Bank-split `memo` | `'Payment INV-001'` | `'Payment INV-001'` | ✓ |
| Bank-split `action` | `'Payment'` | `'Payment'` | ✓ |
| AR-split `memo` | `'Payment INV-001'` | `'Payment INV-001'` | ✓ |
| AR-split `lot_ptr` | `1040769184` | `1040886416` | * pointer differs |
| AR-split `lot_guid` | `b20213b8…` | `b20213b8…` | ✓ — same lot, just remapped in memory by the reopened session |
| **`invoice_from_lot_id`** | **`'INV-001'`** | **`None`** | **✗ — destroyed by unpost** |
| **`owner_from_lot_id`** | **`None`** | **`'C001'`** | * appears post-unpost: detaching the lot from the invoice promotes it to a "free-standing owner lot" that exposes the owner directly |

Two takeaways:

- The **single gold-standard backref** — the lot → invoice link — is destroyed by unpost. `gncInvoiceGetInvoiceFromLot` returns NULL afterwards.
- The **customer** backref survives via two independent paths: `gncOwnerGetOwnerFromTxn` (transaction KVP, always available for payment-class txs) and `gncOwnerGetOwnerFromLot` (lot KVP, becomes available once the lot is no longer invoice-attached). Both agree on customer `C001`.

So we can identify *which customer's payment* this orphan is, but not *which invoice* — unless we read one of the user-controlled fields (memo, description) and gamble on them containing the invoice ID.

### 3. `find_orphan_payments` prototype

Two helpers, picked by whether the unpost has already happened.

```python
# Pre-unpost: walk the invoice's posted lot. ZERO false positives —
# the lot authoritatively names every payment that paid this invoice.
def find_pre_unpost_payments(book, invoice):
    lot = invoice.GetPostedLot()
    if lot is None:
        return []
    payments = []
    for split in lot.get_split_list():
        tx = split.parent
        if xaccTransGetTxnType(tx) != 'P':   # skip the posting tx itself
            continue
        # Find the non-AR side (the bank-side) of this payment tx.
        for s in tx.GetSplitList():
            if s.GetAccount().GetType() not in (ACCT_TYPE_RECEIVABLE,
                                                ACCT_TYPE_PAYABLE):
                payments.append({
                    'tx_guid':     tx.GetGUID().to_string(),
                    'bank_acct':   s.GetAccount().get_full_name(),
                    'memo':        s.GetMemo(),
                    'description': tx.GetDescription(),
                })
                break
    return payments

# Post-unpost: best-effort recovery. False positives possible if the
# customer has multiple unposted invoices whose orphan payments are
# all on this AR account.
def find_orphan_payments_post_unpost(book, invoice_id=None, customer_id=None):
    out = []
    for tx in all_transactions(book):
        if xaccTransGetTxnType(tx) != 'P':                 # crit 1
            continue
        owner = gncOwnerGetOwnerFromTxn(tx)
        if owner is None or owner.type != Customer:        # crit 2
            continue
        if customer_id and owner.id != customer_id:
            continue
        ar_split, bank_split = classify_payment_splits(tx) # crit 3
        if not (ar_split and bank_split):
            continue
        if gncInvoiceGetInvoiceFromLot(ar_split.lot):      # crit 4
            continue   # this payment is still attached to an invoice
        memo_hit = (invoice_id is None
                    or invoice_id in (ar_split.memo or '')) # crit 5
        out.append({
            'tx_guid':              tx.GetGUID().to_string(),
            'customer_id':          owner.id,
            'memo':                 ar_split.memo,
            'memo_contains_invid':  memo_hit,
        })
    return out
```

The working implementation (with the ctypes plumbing) is at `tests/research/test_orphan_detection_probe.py:find_pre_unpost_payments` and `find_orphan_payments_post_unpost`. The accompanying `test_find_orphan_payments_prototype` confirms both paths agree on the single orphan (`tx_guid`) in the step-C/step-D fixture, and that the post-unpost path correctly identifies the customer.

Criteria ordered by strength + false-positive risk for the post-unpost path:

| # | Criterion | FP risk | Notes |
|---|---|---|---|
| 1 | `txn_type == 'P'` | none — different tx types | A manual bank deposit will be `'N'` and won't match. Set authoritatively by `ApplyPayment`; preserved across unpost |
| 2 | `gncOwnerGetOwnerFromTxn(tx).id == customer_id` | none — KVP carries customer GUID | A payment from a *different* customer won't match. Survives unpost. |
| 3 | One split on AR/AP, one elsewhere | low — pure-shape filter | Excludes oddball user-edited txs but doesn't add identification. A user could in theory hand-craft a `'P'` tx with a different shape, but `ApplyPayment` always produces this layout |
| 4 | AR-side split's lot has no invoice attached | low | After unpost, the lot detaches from the invoice. Excludes payments still attached to a *different* posted invoice |
| 5 | Invoice ID substring in AR-split `memo` | high | User-controlled string. The fixture's memo `"Payment INV-001"` contains the ID, but a real user might write `"Q1 retainer"`. If criterion 5 fails, the orphan is still a candidate but cannot be pinned to a specific invoice |
| 6 | Lot's `gncOwner.id` == customer_id (post-unpost) | redundant with #2 | Useful as a secondary check; gives the same answer as criterion 2 via a different code path |

**The genuinely ambiguous case** is "customer C001 has two unposted-but-previously-paid invoices, both paid from the same bank account, both with default memos that don't reference the invoice ID". In that situation criteria 1–4 match both orphans for both invoice IDs; criterion 5 (memo substring) is the only disambiguator and it depends entirely on the user having followed the GnuCash convention.

### 4. CLI mockup

What `unpost-invoices` would print if the orphan-listing was inlined. Pre-unpost is the path that gives the user the most actionable info (named tx, with its GUID, before the unpost commits), so the mockup uses that path.

**Happy path — one orphan found:**

```
$ gnucash-plaintext unpost-invoices mybook.gnucash INV-001
INV-001 (969f5164…): unposted

⚠  1 bank-side payment transaction is now orphaned in the book.
   GnuCash unpost does not delete payment transactions — the money
   still shows as received in your bank account.

   • 2026-01-15  Assets:Bank  CAD 100.00  "Acme"
     memo: "Payment INV-001"
     guid: cf230c62-1c58-4aed-9c7b-97081f6f7bdd

   If you intend to re-pay this invoice, either:
     a) delete the orphan first with:
          gnucash-plaintext delete-transactions mybook.gnucash \
              --by-guid cf230c621c584aed9c7b97081f6f7bdd
        then re-import the invoice with a fresh `payment:` block, or
     b) re-import the invoice with a `payment:` block that includes
          txn_guid: "cf230c621c584aed9c7b97081f6f7bdd"
        to retarget the existing bank transaction into the new lot
        (see docs/issues/Q-004 for the retarget mechanism).
```

**Multiple orphans (partial payments paid the invoice in two instalments):**

```
$ gnucash-plaintext unpost-invoices mybook.gnucash INV-001
INV-001 (969f5164…): unposted

⚠  2 bank-side payment transactions are now orphaned in the book:

   • 2026-02-10  Assets:Bank  CAD  60.00  "Acme"
     memo: "Partial 1"   guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
   • 2026-02-25  Assets:Bank  CAD  40.00  "Acme"
     memo: "Partial 2"   guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb

   Total orphaned: CAD 100.00 across Assets:Bank.

   Re-paying this invoice without acting on these first will create
   duplicate bank entries (the orphans will remain alongside the new
   payment). See above for the two cleanup options.
```

**No orphans (invoice was posted but never paid):**

```
$ gnucash-plaintext unpost-invoices mybook.gnucash INV-001
INV-001 (969f5164…): unposted
```

(No warning — the AR posting transaction was destroyed cleanly and there was nothing in the lot but the posting split itself.)

**Ambiguous — orphan tx points at a customer with multiple unposted invoices:**

This case can only fire if you ran `unpost-invoices` on customer C001's *previous* invoice first, didn't clean up its orphan, and now you're unposting a *different* invoice from the same customer. The pre-unpost path doesn't see the older orphan (it walks the current invoice's lot, which doesn't contain it). If we *also* surface "other orphan payments for this customer already in the book", the output looks like:

```
$ gnucash-plaintext unpost-invoices mybook.gnucash INV-002
INV-002 (5b1d3f9c…): unposted

⚠  1 bank-side payment transaction is now orphaned in the book:

   • 2026-03-15  Assets:Bank  CAD 200.00  "Acme"
     memo: "Mar invoice"   guid: cccccccccccccccccccccccccccccccc

ℹ  Note: Customer C001 ("Acme") also has 1 pre-existing orphan
   payment in the book that may have come from an earlier unpost:

   • 2026-01-15  Assets:Bank  CAD 100.00  "Acme"
     memo: "Payment INV-001"   guid: cf230c621c584aed9c7b97081f6f7bdd

   These are NOT being attached to any current invoice. If they
   should belong to a (possibly already-deleted) invoice, you'll
   need to clean them up manually.
```

Reasoning for the v1 surface: only print the warning when there *is* something to warn about; show full GUIDs (copy-paste-able for the `--by-guid` flag); show the bank account name (a user with several bank accounts needs to know which one); show the memo verbatim (it is the only field that might disambiguate which invoice the orphan came from). The "previously orphaned" info-note is optional — useful but adds noise; it could be gated behind a `--list-customer-orphans` flag.

### 5. Pre-unpost vs. post-unpost identification

| Aspect | Pre-unpost | Post-unpost |
|---|---|---|
| Implementation | trivial — `invoice.GetPostedLot().get_split_list()`, filter to `'P'`-type txs, dump | medium — walk all `'P'`-type txs in the book, filter on owner + AR lot has no invoice, heuristic on memo |
| Code touched | `cli/unpost_cmd.py`: insert a 5-line helper before `rec.Unpost(False)` | new helper in `use_cases/` or `services/`; needs ctypes plumbing for `gncOwnerGetOwnerFromTxn` (already in the probe) |
| Authoritative? | yes — the lot's invoice association is intact, every payment listed *certainly* paid this invoice | no — invoice association is destroyed; can only say "this is customer C001's payment tx, possibly for the invoice you just unposted" |
| False positives | none | none for customer match; significant for invoice match when customer has multiple orphans |
| False negatives | none for the invoice being unposted | none for orphans whose KVP owner backref is intact (i.e. all `ApplyPayment`-created txs) |
| User experience | inline warning at unpost time — exactly when the user is about to lose context | retrospective — user must already know they want to inspect a particular customer/invoice |

**Recommendation:** ship the pre-unpost listing as the v1 fix. It's a 5-line insert in `cli/unpost_cmd.py` (one helper call + one `click.echo` loop) and gives the user *named*, *GUID-bearing* tx info at the exact moment they need it. The post-unpost helper is a useful safety net for users who already lost the context, but the strong UX win is at the unpost moment itself.

The CLI should also probably emit the orphan list when `unpost-invoices` is invoked for *multiple* invoice IDs in one call — each invoice gets its own block of the warning. That falls out naturally from running the pre-unpost helper inside the same loop that calls `Unpost(False)`.

The post-unpost recovery helper is still worth lifting into `use_cases/` later, as a building block for a future `list-orphan-payments` or `cleanup-orphan-payments` command (the "destroy orphan payment txns" cleanup that `cli/unpost_cmd.py` already speculates about in its module docstring). It's the right tool for "I unposted an invoice last month, want to clean up what I left behind".

### Recommendation

**Ship the orphan-listing in `unpost-invoices` as the v1 fix, using the pre-unpost path.** The back-reference signal is strong enough at the moment of unpost to name the soon-to-be-orphans by GUID, bank account, date, and amount — actionable information that lets the user choose between Q-013's `delete-transactions` and Q-004's `txn_guid:` retarget without needing to dig through the GnuCash UI. The prophylactic warning (without specific tx pointers) is strictly worse and isn't needed when the strong path is this cheap to implement.

## Bills: symmetric or not?

**Headline:** Bill behaviour is **fully symmetric** to invoice behaviour. Same orphan, same lifecycle, same backref signals, same duplicate-on-re-pay trap. The two prototype helpers (`find_pre_unpost_payments` and `find_orphan_payments_post_unpost`) work **as-is** for bills with no code changes — the AR/AP type check is already `(11, 12)`, and `gncOwnerGetOwnerFromTxn` returns whichever owner the tx has (customer type 2 or vendor type 4) without the caller needing to distinguish. The only sensible API change when lifting these to production is renaming the helper's `customer_id` parameter to `owner_id` (or `payer_id`) so callers don't think it's invoice-side-only.

Snapshots: `exports/bill/bill_created.txt` … `exports/bill/bill_repaid.txt`. Diffs: `exports/bill/diff_*_to_*.patch`. Bill backref dump: `exports/bill/orphan_backref_probe.txt`. Bill cycle test: `tests/research/test_post_pay_unpost_cycle_bill.py`. Bill probe tests: `test_orphan_backreference_probe_bill` and `test_find_orphan_payments_prototype_bill` in `tests/research/test_orphan_detection_probe.py`.

### Side-by-side comparison

| Property | Invoice (customer) | Bill (vendor) |
|---|---|---|
| SWIG type | `gncInvoice` | `gncInvoice` (same — owner type disambiguates) |
| Unpost CLI | `unpost-invoices` | `unpost-bills` (Q-010 ships both) |
| Posting tx splits | DR AR / CR Income | DR Expense / CR AP |
| Payment tx splits | DR Bank / CR AR | DR AP / CR Bank (signs flipped; CLAUDE.md §7 — `ApplyPayment(amount)` for bills uses `-amount`) |
| `xaccTransGetTxnType` on payment tx | `'P'` | `'P'` (identical) |
| `gncOwnerGetOwnerFromTxn(tx)` pre/post unpost | returns Customer C001, type=2 | returns Vendor V001, **type=4** |
| AR/AP split account-type code | 11 (`A/Receivable`) | 12 (`A/Payable`) |
| AR/AP split has lot pre-unpost | yes | yes |
| `gncInvoiceGetInvoiceFromLot(arLot)` pre-unpost | `'INV-001'` | `'BILL-001'` (returns the bill via the same gncInvoice handle) |
| `gncInvoiceGetInvoiceFromLot(arLot)` post-unpost | None (destroyed) | None (destroyed) |
| `gncOwnerGetOwnerFromLot(arLot)` pre-unpost | None (lot is invoice-attached) | None (lot is bill-attached) |
| `gncOwnerGetOwnerFromLot(arLot)` post-unpost | returns C001 | returns V001 |
| Lot GUID survives unpost | yes (same GUID, new in-memory ptr) | yes (same GUID, new in-memory ptr) |
| AR/AP split memo on payment tx | user-controlled string from `payment.memo` | user-controlled string from `payment.memo` |
| Entry-GUID stability across cycle | preserved only C→D | preserved only C→D (same table as invoice case) |
| Exporter emit path for orphan | `transactions:` section only | `transactions:` section only (shared code path) |
| `_export_invoices`/`_export_bills` payment loop | walks `inv.GetPostedLot().get_split_list()`, calls `_format_payment` | walks `inv.GetPostedLot().get_split_list()`, calls `_format_payment` (same shared helper at `use_cases/export_business_objects.py:367`) |
| Re-pay-after-unpost duplicates the bank tx | yes | yes |
| Pre-unpost identification helper | works on `gncInvoice` (Q1 prototype) | **works unmodified** — Q3 `test_find_orphan_payments_prototype_bill` passes |
| Post-unpost identification helper | works | **works unmodified** |

### Diff evidence — step C → step D for the bill

The bill's `diff_paid_to_unposted.patch` is structurally identical to the invoice's: posting tx destroyed, posted/payment blocks revert to `none`, bank tx survives untouched. Key snippet from the bill diff:

```
-2026-01-01 * "BILL-001" "Bill BILL-001"
-	guid: "93ba2e49a5414a77867e1091ffa19106"
-	notes: "business_generated: true"
-	Expenses:Supplies 100.00 CAD
-	Liabilities:Accounts Payable -100.00 CAD
```

— the AP posting tx is destroyed, exactly as the AR posting tx was on the invoice side.

```
 2026-01-15 * "Supplier"
 	guid: "a7707891c2d24be1856556546c621b1b"
 	Liabilities:Accounts Payable 100.00 CAD
 		action: "Payment"
 		memo:"Payment BILL-001 (first)"
 	Assets:Bank -100.00 CAD
 		action: "Payment"
 		memo:"Payment BILL-001 (first)"
```

— the bank payment tx survives with both splits intact. Same GUID (`a7707891…`) before and after the unpost. The split sign pattern is mirrored vs invoices: bank is `-100` (money sent out) instead of `+100` (received), AP is `+100` (debt reduced) instead of AR `-100` (receivable reduced).

The re-pay diff for the bill (`exports/bill/diff_reposted_to_repaid.patch`) confirms the duplicate: re-importing with a second `payment:` block creates a brand-new bank tx (`cfb75461…`, dated 2026-02-15) alongside the surviving orphan (`a7707891…`, dated 2026-01-15). Bank balance at step F: −200 (paid the vendor twice), AP balance: −100 (vendor owes us money — wrong direction), Expenses: +100. Same shape as the invoice cycle, signs flipped.

### Backref probe — bill side

The bill probe dump (`exports/bill/orphan_backref_probe.txt`) shows every backref behaves identically to the invoice case:

```
   description                      'Supplier'  →  'Supplier'
   txn_type                         'P'  →  'P'
   tx_guid                          '91d8f7d6…'  →  '91d8f7d6…'
   owner_from_txn_id                'V001'  →  'V001'
   owner_from_txn_type              4  →  4
…
  split[0] (account='Liabilities.Accounts Payable', type=12):
   * invoice_from_lot_id            'BILL-001'  →  None
   * owner_from_lot_id              None  →  'V001'
```

Two interesting bill-specific observations:

1. `gncInvoiceGetInvoiceFromLot` on the bill's AP lot **returns the bill object** pre-unpost — i.e. it's not invoice-specific despite the function name. The function operates on any `gncInvoice`-typed handle regardless of whether the owner is Customer or Vendor. Confirmed `id='BILL-001'` from `gncInvoiceGetID(invoiceFromLot)`. This is the kind of GnuCash C API surprise that's worth flagging in the doc — *the SWIG/C symbol name is misleading; the same call handles both invoices and bills*.

2. The `gncOwnerGetOwnerFromTxn` payload's `owner.type` is **4** for vendor payments (vs **2** for customer payments). The helper doesn't currently expose `owner_type` to the caller — it only filters on `owner.id` — but the underlying field is there. If a future feature needs to format a CLI message that says "this is a *vendor* bill payment" vs "this is a *customer* invoice payment", that's the field to read.

### Identification helper symmetry

Both prototype helpers from the "Follow-up: can we track the orphan?" section work on bills without code changes:

- `find_pre_unpost_payments(book, bill_swig_obj)` — passes a SWIG `Invoice` whose owner is a Vendor; the helper walks `bill.GetPostedLot()` and filters splits by account-type `(11, 12)`. AP splits match type 12, so the lot's AP-side split is recognised correctly. The bank-side split (type 0) is correctly classified as the non-AR/AP side.
- `find_orphan_payments_post_unpost(book, invoice_id="BILL-001", customer_id="V001")` — `gncOwnerGetOwnerFromTxn` returns `owner.id='V001'` regardless of whether the owner is a Customer or a Vendor, so the same comparison works. The AR/AP filter using `(11, 12)` already covers both sides.

Both `test_find_orphan_payments_prototype_bill` and the invoice-side equivalent pass against their respective fixtures. Both helpers cross-check: the pre-unpost path and the post-unpost path return the same `tx_guid` for the orphan.

The only API ergonomic improvement worth making before lifting to production: rename `customer_id=` to `owner_id=` (or `payer_id=`) so the parameter name doesn't suggest "invoice-side only". The `invoice_id=` parameter is still well-named because both invoices and bills are `gncInvoice` records and the user types it the same way in the CLI.

### CLI mockup — `unpost-bills`

The warning text is the same shape as the `unpost-invoices` mockup with three word-level swaps: "AR" → "AP", "receivable" → "payable", and "money still shows as received" → "money still shows as having been sent". Concrete v1 happy path:

```
$ gnucash-plaintext unpost-bills mybook.gnucash BILL-001
BILL-001 (96fbf452…): unposted

⚠  1 bank-side payment transaction is now orphaned in the book.
   GnuCash unpost does not delete payment transactions — the money
   still shows as having been sent from your bank account.

   • 2026-01-15  Assets:Bank  CAD -100.00  "Supplier"
     memo: "Payment BILL-001"
     guid: a7707891-c2d2-4be1-8565-56546c621b1b

   If you intend to re-pay this bill, either:
     a) delete the orphan first with:
          gnucash-plaintext delete-transactions mybook.gnucash \
              --by-guid a7707891c2d24be1856556546c621b1b
        then re-import the bill with a fresh `payment:` block, or
     b) re-import the bill with a `payment:` block that includes
          txn_guid: "a7707891c2d24be1856556546c621b1b"
        to retarget the existing bank transaction into the new lot
        (see docs/issues/Q-004 for the retarget mechanism).
```

Bill-side wording differences worth noting:

- The bank-side amount is shown as `CAD -100.00` (negative) for bill payments vs `CAD 100.00` for invoice payments. The CLI should print the signed amount as it appears on the bank-side split — *"-100.00"* unambiguously communicates "money leaving the bank", which is what the user reading a vendor payment warning wants to confirm.
- "money still shows as having been sent" replaces "money still shows as received" — the action is reversed.
- The doc reference (`docs/issues/Q-004`) is the same — the retarget mechanism is symmetric and the existing fixture `payment_roundtrip_bill_txn_guid.txt` already demonstrates it for bills.

### Updated v1 recommendation

**Ship the pre-unpost orphan-listing in both `unpost-invoices` *and* `unpost-bills` — same helper, same warning template, two callsites.** Because the prototypes work unmodified for both, the implementation is a single `use_cases/orphan_payments.py` (or a free function in `cli/unpost_cmd.py`) invoked from both CLI commands. The output template is parameterised on three short variables — "invoice"/"bill", "AR"/"AP", "received"/"sent" — and otherwise byte-identical. No need to split the work into two tickets; whatever Q-014 scope captures `unpost-invoices` should explicitly cover `unpost-bills` in the same PR.

The two probe outputs (`exports/orphan_backref_probe.txt` and `exports/bill/orphan_backref_probe.txt`) plus the four passing probe tests give the implementation a regression net: any future drift between the invoice and bill orphan-detection behaviour will surface as a test diff.


