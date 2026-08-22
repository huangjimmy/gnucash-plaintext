# Bad Debt and Return of Credit — Design Note

**Feature branch**: `feature/credit-refund-bad-debt`
**Created**: 2026-06-03
**Status**: Implemented and tested on GnuCash 5.10 (credit clearing — refund / vendor bad debt / customer forfeit / partial / standalone create+settle / round-trip; invoice & bill bad-debt validation; the `open_prepayment:` summary with import warn). Engine path probe-backed across GnuCash 3.8–5.16; the 45-test Q-014 orphan/payment-roundtrip suite still passes.

---

## Overview

Add plaintext support for two business-payment operations the format cannot currently express:

- **Bad debt write-off** — an uncollectible **invoice** (money owed to us) is cleared by routing its balance to a bad-debt expense instead of cash. (Only invoices: an unpaid *bill* we owe is debt forgiveness, not bad debt — out of scope. A vendor's unreturned overpayment is "vendor bad debt" but is handled as a credit clearing, below.)
- **Return of credit (refund)** — an open customer/vendor credit (pre-payment or overpayment residual) is paid back instead of being consumed against a future invoice. **Partial returns are supported** — refund part of a credit and the remainder stays open.

The central finding behind this design (verified against GnuCash 5.10 — see [Appendix: probe evidence](#appendix-probe-evidence)) is that GnuCash has **no dedicated refund or write-off function**. Both operations are the *same* payment primitive, `gncOwnerApplyPaymentSecs`, with only two knobs turned: the **transfer account** and the **sign of the amount**. That single insight keeps this feature small and makes the two operations mirror images of each other.

---

## Background: how GnuCash actually models these

`gncOwnerCreatePaymentLotSecs` (libgnucash/engine/gncOwner.c) builds every payment identically — the transfer (bank) split gets `+amount`, the posted AR/AP split gets `gnc_numeric_neg(amount)`:

```c
xaccSplitSetAmount (xfer_split, xfer_amount);          /* bank/expense split = +amount */
...
xaccSplitSetAmount (split, gnc_numeric_neg (amount));  /* AR/AP split        = -amount */
```

`gncOwnerApplyPaymentSecs` then wraps the new payment lot and hands it to `gncOwnerAutoApplyPaymentsWithLots`, a generic lot-balancer that offsets any two open opposite-sign lots for the owner. There is no `refund` argument anywhere in the owner/payment subsystem.

So the only two degrees of freedom produce all four operations:

| Operation | Target lot | Transfer account | Amount (engine) | AR/AP split | Counter split |
|---|---|---|---|---|---|
| Normal payment | invoice lot | bank | +N | −N (closes invoice) | bank +N (money in) |
| **Bad debt** | invoice lot | Expenses:Bad Debt | +N | −N (closes invoice) | expense +N (debit) |
| **Return of credit** | credit lot | bank | **−N** | **+N** (closes credit) | bank −N (money out) |
| (Forfeited credit) | credit lot | income | −N | +N (closes credit) | income −N |

Bad debt and return of credit are not two unrelated features — they share one primitive ("reduce an open AR/AP lot by N, routing the counter-amount to another account") pointed at different lots. The lot type fixes the AR/AP sign automatically; the user never deals with signs directly.

**But the counter-account is not free.** Mechanically GnuCash accepts any account; *accounting-correctly* each operation allows only specific account types, and the importer must enforce that — routing an invoice write-off to a bank, or a refund to an expense, is nonsense the format should reject. The legal matrix:

| What you're clearing | → asset (bank) | → expense | → income |
|---|---|---|---|
| Customer invoice (AR, they owe us) | payment received | **bad debt — must be expense** | ✗ (that's a credit memo — out of scope) |
| Customer credit (we owe them) | refund | ✗ (you hold their money — not your loss) | forfeit (your gain) |
| Vendor credit (they owe us) | refund received | **vendor bad debt** (your loss) | ✗ (you lost money — not a gain) |
| Vendor bill (AP, we owe them) | payment sent | ✗ | debt forgiveness — out of scope |

The shared engine call is the "general"; this per-operation account-type validation is the "not too general."

This is also the correct fix for the long-standing refund trap documented at `README.md` (the "record a free `Bank −50 / AR +50` transaction and re-import" advice). That free transaction leaves **two** dangling open lots (the original −50 credit and a new +50) that net to zero in the account balance but never actually retire the credit. Routing through `gncOwnerApplyPaymentSecs` makes GnuCash run its own lot-balancer, which genuinely closes the credit lot.

---

## Design Decisions

### 1. Invoice bad debt reuses the `payment:` block, with the account constrained — and bills are asset-only

Bad debt only exists for money owed **to us** — an uncollectible **invoice** (AR). A **bill** is money **we owe**; it has no "bad debt". An unpaid bill the vendor forgives is *debt forgiveness*, a gain booked to income (DR AP / CR income), which the matrix above marks **out of scope** — so a bill payment must never route to an expense. (Vendor *bad debt* does exist, but it is writing off a vendor's overpayment **credit**, not a bill — that is the prepayment-clearing path of decisions 2/5, never this block.)

A bad-debt write-off *is* a payment against the invoice whose counter-account is a **bad-debt expense**. The importer already resolves the payment transfer account by name (`find_account`) and calls `ApplyPayment(None, <account>, amount, …)`, so the engine mechanics work today; the changes are the field, the exporter, and — the point of this decision — **validation**.

**Decision**: introduce `account:` as the canonical transfer-account field on the `payment:` block (reading the existing `bank_account:` as an alias so already-exported books round-trip unchanged), and **constrain its account type by side**:

- **Invoice payment** → an **asset** (a real cash payment) or an **expense** (a bad-debt write-off). For a *bad debt* the account must be an expense; there is no "write off an invoice to a bank account".
- **Bill payment** → an **asset** only. Expense (no such thing as bill bad debt) and income (debt forgiveness, out of scope) are rejected.

Any other type — equity, the AR/AP account itself, income on an invoice (that would be a credit memo, out of scope) — is rejected with an accounting-level error.

```
invoice "INV-007"
    ...
    payment:
        account: "Expenses:Bad Debt"     # invoice: expense → write-off; asset → cash payment
        amount: 1000
        date: 2026-06-01
        memo: "Write-off — customer insolvent"
```

For an invoice the importer infers intent from the account *type* (asset = payment, expense = write-off) — no separate `write_off:` keyword needed — but enforces that the type is one of the two legal kinds. Partial bad debt falls out for free: write off `amount: 400` of a $1000 invoice and the lot stays open at $600. (Only invoice/customer bad debt is probe-backed — appendix C1–C2; there is no bill-bad-debt path to probe.)

Rejected alternative: a dedicated `write_off:` block. It would duplicate the entire payment-application path for no behavioural gain, since the engine treats it as an ordinary payment; the expense-account constraint already makes the intent unambiguous.

### 2. Clearing a credit reuses the `transaction:` directive and the existing `lot_owner:` split KVP

A credit isn't attached to an invoice, and clearing it *is* just a normal ledger transaction (a counter account + an AR/AP split). So instead of a new top-level block or a new split field, reuse the existing `transaction:` directive and the existing per-split `lot_owner:` KVP — the Q-014 orphan-lot KVP — extended to carry the owner guid:

```
2026-02-15 * "Refund of overpayment to Acme"
    currency.mnemonic: "CAD"
    Assets:Bank -50.00 CAD
    Assets:Accounts Receivable 50.00 CAD
        lot_owner: customer:C001:9f14a498cc894d50931f855a9a31d594
```

```
2026-02-15 * "Write off Supplier overpayment — ceased trading"
    currency.mnemonic: "CAD"
    Expenses:Bad Debt 50.00 CAD
    Liabilities:Accounts Payable -50.00 CAD
        lot_owner: vendor:V001:3f6d4a17b218c47e85d290f3e9a2b1c4
```

Why reuse `lot_owner:` rather than a new `customer:`/`vendor:` split tag:

- **One KVP, one concept.** An AR/AP split sitting in an owner's non-invoice lot already carries `lot_owner: kind:id` (Q-014, to reconstruct an orphan payment's lot). A clearing split has exactly that shape. A second field would be two mechanisms with opposite import semantics on the same split; folding them into one `lot_owner:` (with a smarter import — decision 5) avoids that. A nicer `customer:`/`vendor:` wording was weighed and judged not worth breaking the established field.
- **`kind:id[:guid]`.** The trailing guid is the **owner's** authoritative key (never a lot guid — decision 3). Always emitted on export; optional hand-written (`lot_owner: customer:C001` still imports). When present it MUST resolve to the same owner as the id, else the import **errors** — `lot_owner:` is structural, not informational, so a guid mismatch is a hard failure, never a warning.
- **The counter split states the intent**, no extra keyword: a bank account ⇒ refund, an expense ⇒ vendor bad debt, an income ⇒ customer forfeit. The legal account-type × owner matrix (decision 1) is enforced.
- **Round-trip for free.** It's a transaction, so Q-016 already round-trips it and its per-split GUIDs; export re-emits `lot_owner:` from the lot's owner backref.

Import semantics (decision 5 has the engine path):

- The split's account fixes the owner type: `customer` ⇒ an **AR** account, `vendor` ⇒ **AP**; a mismatch is an error.
- **Join or create.** If the owner has an open lot this split *reduces* (opposite sign) → **join** it (a clearing). Otherwise, if the split is itself a credit/payment origin (AR-negative / AP-positive) → **create** a new lot and attach the owner (an orphan payment reconstructed, or a fresh standalone credit — closing the "standalone credit is invisible in plaintext" gap). A clearing-shaped split (opposite sign) with no credit to reduce → **error**: no phantom lot is minted.
- **No amount/balance validation** on a join: partial (residual stays open), exact (lot closes), or over-applied are all accepted — the explicit split amounts are authoritative.

### 3. No lot id — owner tag is the only handle

We considered referencing the specific credit lot by GUID. **Rejected** — the owner tag is enough. Credits for one owner+currency are fungible: which lot a clearing lands in has no economic effect (the owner-level total is what matters), so naming a lot would only let the user pick between interchangeable lots, at the cost of an extra lot-GUID read and a handle that doesn't round-trip. With several open lots the importer attaches to the **oldest**; the user controls outcomes through the split amounts and through writing more than one transaction if they want to clear more than one lot. (We do not use `gncOwnerApplyPaymentSecs`'s auto-apply to spread a clearing across lots — that is the path that segfaults on GnuCash 4.4/4.8; see decision 5.)

### 4. Lots close, they don't disappear — and overpayments never reopen them

Probed behaviour (5.10 and 3.8, see appendix) that the rules above rely on:

- A prepayment lot driven to **zero is not removed** — it persists as a *closed* lot still holding both splits (origin + clearing), surviving save→reload. So a cleared credit stays visible to the export lot-walk, and a lot is never "absent", only **open or closed**.
- A new overpayment **always mints a fresh lot** (`gnc_lot_new`), never reopens a closed one. So an owner accumulates one closed lot per settled credit plus open lots for live credits; "find the owner's open prepayment lot" is always unambiguous.

A partial return is therefore just a smaller offsetting split than the lot balance — the lot stays open at the reduced credit, discoverable via `find-prepayments` (probe: clear 20 of a 50 credit → open at −30 on every version). Idempotent re-import of an already-applied clearing is matched by transaction GUID (Q-016) and never re-resolves a lot, so the now-closed lot doesn't cause a spurious reject.

### 5. Import path: close the credit lot with primitive engine calls, NOT `gncOwnerApplyPaymentSecs`

The obvious implementation — `gncOwnerApplyPaymentSecs(..., auto_pay=True)` with a negative amount — **segfaults on GnuCash 4.4 and 4.8** (see the cross-version probe in the appendix). The crash is inside `gncOwnerAutoApplyPaymentsWithLots`, the engine's lot-balancer, when it nets the new payment lot against the existing credit lot.

**Decision**: don't use the auto-apply at all. Close the credit lot directly with primitive engine calls — build the two-split transaction (counter account + AR/AP) and `gnc_lot_add_split` the AR/AP split straight into the existing credit lot so it closes (or reduces) by balance:

```
txn = xaccMallocTransaction(book); xaccTransBeginEdit(txn); xaccTransSetCurrency(txn, ccy)
s_counter = xaccMallocSplit(book); xaccSplitSetParent(s_counter, txn); xaccSplitSetAccount(s_counter, bank/expense/income); set value/amount
s_arap    = xaccMallocSplit(book); xaccSplitSetParent(s_arap, txn);    xaccSplitSetAccount(s_arap, AR/AP);                set value/amount
gnc_lot_add_split(credit_lot, s_arap)        # join the offsetting split to the existing credit lot
xaccTransSetDatePostedSecs(txn, date); xaccTransCommitEdit(txn)
```

When there is no open lot to reduce, the same primitives **create** a new lot (`gnc_lot_new` + `xaccAccountInsertLot` + `gnc_lot_add_split` + `gncOwnerAttachToLot`) — the existing Q-014 orphan-reconstruction path, now also used for a fresh standalone credit. This join-or-create is implemented as `_attach_lot_owner_split` in `services/gnucash_importer.py`, replacing Q-014's former always-create `lot_owner:` handler; the owner-lot walk reuses the `xaccAccountGetLotList` pattern from `use_cases/unpost_business_objects.py`.

This path is **verified on all ten supported builds** (GnuCash 3.8 through 5.16) for full refund, partial refund, vendor bad debt, forfeit, standalone-credit create-then-settle, and export → fresh re-import — no version gate needed — and the 45-test Q-014 orphan/payment-roundtrip suite still passes, so folding orphan reconstruction into the same path didn't regress it.

Customer *bad debt against an invoice* (decision 1) is different — it closes the invoice's own posted lot via the existing invoice `ApplyPayment` path (just with an expense transfer account), which does not invoke the buggy lot-netting and works on every version.

### 6. Round-trip / export

Two cases, both lighter than they first looked because the manual lot-split (decision 5) leaves a clean, persistent topology:

- **Customer bad debt** — a payment on an invoice lot whose counter-split is an expense. The existing payment exporter already walks the posted lot and emits each payment's counter-account, so it just emits `payment:` with that expense account. Local to the payment exporter.
- **Credit clearing** (refund / vendor bad debt / forfeit) — a transaction whose AR/AP split sits in a lot that **no invoice owns** (`gncInvoiceGetInvoiceFromLot` is NULL) and that carries an owner backref. Emit it as a normal `transaction:` — Q-016 already round-trips the transaction and its per-split GUIDs — and emit `lot_owner: kind:id:guid` on that AR/AP split, read from the lot's owner backref. No special transaction type, no sign analysis, no new block to detect. Because a cleared lot persists closed with its splits (decision 4), this works on cleared credits too, and because the *origin* split also carries `lot_owner:`, a standalone credit's origin round-trips as well (its `lot_owner:` re-creates the lot on import — decision 2's create branch).

For an **overpayment** origin the credit is also represented as `prepayment:` on the invoice payment (Q-015); the clearing is the additional opposite-sign split in the same lot. **This is implemented and verified** by an `import → export → import` round-trip test on a standalone credit (created via `lot_owner` then cleared): the export emits `lot_owner: …:guid`, and the fresh re-import rebuilds the same settled state.

### 7. `find-prepayments` and the workflow note

`find-prepayments` already surfaces every open credit and currently advises either consuming via `auto_apply_credit:` or the destructive "delete the source bank tx" refund. Update its guidance (and `README.md`) to point at the new non-destructive path — a normal transaction with the AR/AP split carrying `lot_owner: kind:id` — as the canonical way to dispose of a credit (refund, write off, or forfeit), keeping the delete path only as the standalone-payment shortcut.

### 8. User-facing surface: discovery and the `open_prepayment:` summary

Owners are identified consistently everywhere: by **guid (authoritative)** with the **id as a readable companion** — the same id/guid pairing used across the format.

**Discovery — two ways:**

- `find-prepayments` (read-only CLI, already exists) lists open credits per owner. Add a per-owner running total and a `--json` mode so other tools / AI can consume it. Lightest path — reads only AR/AP lots.
- **The exported file self-documents open credits.** Whenever an AR/AP lot is open with a balance, the export emits a repeating `open_prepayment:` sub-block on that account — **not optional**. Because the block lives on the account, it appears in both full `export` and the existing `export-accounts` command, so `export-accounts` is the lightweight "open credits per owner, in plaintext" path — no full ledger needed. (`export-accounts` otherwise loads no transactions; emitting `open_prepayment:` adds a *bounded* scan of the AR/AP lots only, far cheaper than a full export — note this in its `--help`.) One block per open lot (oldest first, the order a clearing consumes them):

  ```
  account "Assets:Accounts Receivable"
      ...
      open_prepayment:
          customer: "C001"
          customer_guid: "9f14a498cc894d50931f855a9a31d594"
          amount: 50.00 CAD
      open_prepayment:
          customer: "C001"
          customer_guid: "9f14a498cc894d50931f855a9a31d594"
          amount: 30.00 CAD
  ```

  (AP side uses `vendor:` / `vendor_guid:`.) This is a child block, not a metadata key, because plain `key: value` lines overwrite and an owner can hold several open lots — same mechanism as `breakdown:` under entries.

  It is **derived / informational**, so its handling differs from `entry_amount`/`entry_tax`:
    - **Export** always writes the correct, recomputed balance.
    - **Import** recomputes open prepayments from the book in a **post-import pass** (the account block is read before the transactions that create the lots, so it cannot be checked at account-creation time) and compares per owner. On a mismatch it prints a **warning to stderr** (account, owner, declared vs actual) and **import still succeeds** — the book's actual lots are authoritative, and the next export self-heals the file. This is softer than `entry_amount`/`entry_tax`, which error, because those guard posted-record integrity while this is a self-correcting summary. Implemented as `_warn_open_prepayment_mismatches` in `cli/import_cmd.py`.

**Action: the `transaction:` directive with a `lot_owner:`-tagged AR/AP split** (decision 2) is the single way to clear a credit — power, AI-assisted, and bulk editing all use the same explicit form. A `clear-prepayment` convenience CLI was considered and **rejected**: it would have to assume the destination account's currency and would hide details (the AR/AP account, the sign) that a user writing an import file generally wants to set explicitly. The directive is the clear, explicit path; the `lot_owner:` KVP carries everything needed.

---

## Linking an already-imported transaction

When the actual outflow already exists in the book (e.g. imported from a bank feed with an `Imbalance` counter-split), the user should be able to turn it into the credit clearing rather than create a duplicate bank transaction. Because the clearing is just a `transaction:`, this rides the directive's existing GUID identity (Q-016): the user writes the transaction carrying the existing bank transaction's `guid:` and re-targets its counter-split to the AR/AP account with a `lot_owner:` KVP. The importer matches the transaction by GUID, updates the split to AR/AP, and attaches it to the owner's open prepayment lot. No separate linkage field is needed — the transaction GUID is the link.

---

## Out of Scope

- **Refunding an already-paid invoice** (e.g. a customer returns goods three months after paying). This is a *separate* business transaction, not an unpost-and-refund of the original invoice; the original invoice and its payment stay untouched. Modelling product returns / credit notes against historical invoices is explicitly excluded.

---

## Appendix: probe evidence

All probes run against GnuCash 5.10 in the `gnucash-dev` container on 2026-06-03 (artifacts removed after). Credit-clearing cases drove `gncOwnerApplyPaymentSecs` via ctypes for both owner types; customer bad debt used the SWIG invoice `ApplyPayment` path.

**Full operation matrix** — every case produced textbook-correct balances and lot closure:

| Case | Setup | Result |
|---|---|---|
| C1 customer bad debt (full) | invoice 100 → expense | AR 0 (lot closed), Bad Debt +100 |
| C2 customer bad debt (partial) | 30 to bank + 70 to expense | AR 0, bank +30, Bad Debt +70 |
| C3 customer refund (full) | prepay 50 → bank | AR 0 (closed), bank net 0 |
| C4 customer refund (partial) | prepay 50 → refund 20 | 30 credit remains, bank +30 |
| C5 customer forfeit → income | prepay 50 → income | AR 0, bank +50, income −50 (gain) |
| V1 vendor prepayment | pay vendor 50 ahead | AP +50 (vendor owes us), bank −50 |
| V2 vendor refund received | prepay 50 → vendor refunds 50 | AP 0 (closed), bank net 0 |
| V3 **vendor bad debt** (full) | prepay 50 → expense | AP 0 (closed), bank −50, Bad Debt +50 |
| V4 vendor bad debt (partial) | prepay 50 → write off 30 | 20 credit remains, Bad Debt +30 |

Confirms: vendor direction works (signs as in decision 2), bad debt and forfeit work end-to-end, the counter-`account:` is free, and partials leave the correct residual credit.

**Multi-credit fungibility** (one owner holding 50 + 30; refund amount only, no lot id):

| Refund | Result | Bank |
|---|---|---|
| 50 | 50-lot closes, 30 remains | 80 → 30 |
| 60 | 50-lot consumed + 30-lot reduced → single 20 credit | 80 → 20 |
| 20 | 50-lot reduced to 30, other untouched → 60 total | 80 → 60 |

Proves owner + amount is a sufficient handle (decision 3).

**Lot GUID (investigated, then dropped)** — credit lots *are* GUID-addressable (`qof_instance_get_guid` + `guid_to_string_buff`; `gnc_lot_lookup` round-trips to the same pointer; the GUID is stable across save→reload). This confirmed a lot GUID *could* be a handle, but decision 3 shows it is unnecessary.

**Cross-version probe** — the same operations on every supported GnuCash, two implementation paths:

| GnuCash | Distro | Invoice bad debt | Credit clearing via `gncOwnerApplyPaymentSecs` (auto-apply) | Credit clearing via primitive lot-split (decision 5) |
|---|---|---|---|---|
| 3.8 | Ubuntu 20.04 | ✓ | ✓ | ✓ |
| 4.4 | Debian 11 | ✓ | **SEGFAULT** | ✓ |
| 4.8 | Ubuntu 22.04 | ✓ | **SEGFAULT** | ✓ |
| 4.13 | Debian 12 | ✓ | ✓ | ✓ |
| 5.5 | Ubuntu 24.04 | ✓ | ✓ | ✓ |
| 5.10 | Debian 13 | ✓ | ✓ | ✓ |
| 5.13 | Fedora 41 | ✓ | ✓ | ✓ |
| 5.14 | Ubuntu 26.04 | ✓ | ✓ | ✓ |
| 5.15 | Arch Linux | ✓ | ✓ | ✓ |
| 5.16 | openSUSE Tumbleweed | ✓ | ✓ | ✓ |

In version order, because that is what the column is scanned for: the boundary below is read off this table, and rows sorted by anything else put the 4.x/5.x transition in two places.

The version each row names is what that image's own package database reports. Three of them were a release or more out when this table was written — Ubuntu 24.04 was listed as 4.9 and carries 5.5 — which matters here more than anywhere else in the repo, for the same reason.

The auto-apply path (`gncOwnerApplyPaymentSecs` with `auto_pay`) **segfaults on GnuCash 4.4 and 4.8** — reproducibly, through pure SWIG using the book's own engine instance (so it is not a ctypes/instance-mismatch artifact). The crash is *inside* `gncOwnerAutoApplyPaymentsWithLots` when it nets the new payment lot against the existing credit lot: creating the prepayment lot (`+N`) returns fine, the offsetting `−N` payment crashes. The pattern is ok on 3.8, broken on 4.4 and 4.8, ok from 4.13 on — an early-4.x engine regression, and the supported builds place its repair somewhere in 4.9–4.13 rather than at 4.9, which is what this table said while Ubuntu 24.04 was labelled with a version it does not carry.

**The primitive lot-split path (decision 5) avoids the bug entirely and passes on all ten builds** — so this is resolved, not an open question: there is no version gate. Intermediate snapshots (identical on 3.8 / 4.4 / 4.8 / 5.10) show the mechanic step by step:

```
A customer full refund:   credit created  AR=-50 bank=+50  lot bal=-50 splits=1 open
                          after refund     AR= 0  bank=  0  lot bal=  0 splits=2 closed
B customer partial 20/50: after refund     AR=-30 bank=+30  lot bal=-30 splits=2 open
C vendor bad debt:        credit created  AP=+50 bank=-50  lot bal=+50 splits=1 open
                          after write-off  AP=  0 bank=-50  baddebt=+50  lot bal=0 splits=2 closed
```

(In every case the offsetting split joins the existing lot — splits 1 → 2 — and the balance moves to 0 for a full clear or to the residual for a partial.) Invoice/bill *payments* — including an invoice bad-debt write-off — are unaffected on all versions regardless, because they close the invoice's own lot and never net two lots.

**Round-trip verified**: a standalone credit created via `lot_owner`, cleared, exported, and re-imported into a fresh book reaches the same settled state, and the exporter emits `lot_owner: …:guid`. The `open_prepayment:` summary survives the same cycle (parsed and ignored on import; warns on a tampered value).
