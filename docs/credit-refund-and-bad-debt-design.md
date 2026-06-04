# Bad Debt and Return of Credit — Design Document

**Feature branch**: `feature/credit-refund-bad-debt`
**Created**: 2026-06-03
**Status**: Design settled (directive, CLI/API, and cross-version engine path all probe-backed); implementation pending

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

### 2. Clearing a credit reuses the `transaction:` directive — tag the AR/AP split with its owner

A credit isn't attached to a document, and clearing it *is* just a normal ledger transaction (a counter account + an AR/AP split). So instead of a new top-level block, reuse the existing `transaction:` directive and add one thing: on the AR/AP split, name the owner whose prepayment it settles.

```
2026-02-15 * "Refund of overpayment to Acme"
    currency.mnemonic: "CAD"
    Assets:Bank -50.00 CAD
    Assets:Accounts Receivable 50.00 CAD
        customer: "C001"
        customer_guid: "9f14a498cc894d50931f855a9a31d594"
```

```
2026-02-15 * "Write off Supplier overpayment — ceased trading"
    currency.mnemonic: "CAD"
    Expenses:Bad Debt 50.00 CAD
    Liabilities:Accounts Payable -50.00 CAD
        vendor: "V001"
        vendor_guid: "3f6d4a17b218c47e85d290f3e9a2b1c4"
```

Why this shape:

- **Self-descriptive in context.** An AR split *is* the customer's receivable; an AP split *is* the vendor's payable. So `customer:` / `vendor:` on that split reads as "this AR/AP belongs to <owner>", and the counter split's account states the intent with no extra keyword: a bank account ⇒ refund, an expense ⇒ vendor bad debt, an income ⇒ customer forfeit. (The legal account-type × owner matrix from decision 1 still applies and is enforced.)
- **Round-trip for free.** It's a transaction, so Q-016 already round-trips the transaction and its per-split GUIDs. Export just adds the owner tag, read from the lot's owner backref.
- **Owner referenced by the documented id/guid convention.** `customer:` / `vendor:` carries the human id; `customer_guid:` / `vendor_guid:` carries the authoritative owner key (README §Identity, same as on invoices/bills). Either alone is fine hand-written; when both are present they must resolve to the same owner; export emits both. The guid is the **owner's**, never a lot guid (no lot reference — decision 3). Both ids are plain quoted strings, so any character a GnuCash id allows is fine; nothing new is forbidden.

Import semantics:

- A split carrying `customer:` / `customer_guid:` must be on an **AR** account; `vendor:` / `vendor_guid:` on an **AP** account. Owner type is derived from the account; a mismatch is an error (and is the owner-type check).
- The split is attached to the owner's **open prepayment lot** (oldest, if several) via the primitive lot-split close (decision 5).
- **Reject only when the owner has no open prepayment lot.** A closed/already-settled lot, or an owner who never had a credit, both mean there is nothing live to apply against — and a new credit is created by a fresh overpayment, never by reopening a closed lot (decision 4). We never create a lot here.
- **No amount/balance validation.** The explicit split amounts are authoritative: partial (residual stays open), exact (lot closes), or even over-applied (the lot flips past zero — an untidy but user-intended balance) are all accepted, matching GnuCash's own permissiveness. The only thing rejected is referencing a credit that isn't there.

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

This path is **verified on all ten supported builds** (GnuCash 3.8 through 5.14) for full refund, partial refund, and vendor bad debt — no version gate needed. It also gives precise control (we choose exactly which lot the offsetting split joins) and avoids the `Vendor.ApplyPayment` SWIG-alias gap entirely. The locating of the owner's open credit lot reuses the same `xaccAccountGetLotList` walk the project already uses in `use_cases/unpost_business_objects.py`.

Customer *bad debt against an invoice* (decision 1) is different — it closes the invoice's own document lot via the existing invoice `ApplyPayment` path (just with an expense transfer account), which does not invoke the buggy lot-netting and works on every version.

### 6. Round-trip / export

Two cases, both lighter than they first looked because the manual lot-split (decision 5) leaves a clean, persistent topology:

- **Customer bad debt** — a payment on an invoice lot whose counter-split is an expense. The existing payment exporter already walks the posted lot and emits each payment's counter-account, so it just emits `payment:` with that expense account. Local to the payment exporter.
- **Credit clearing** (refund / vendor bad debt / forfeit) — a transaction whose AR/AP split sits in a lot that **no invoice owns** (`gncInvoiceGetInvoiceFromLot` is NULL) and that carries an owner backref. Emit it as a normal `transaction:` — Q-016 already round-trips the transaction and its per-split GUIDs — and add `customer:`/`vendor:` (+ the owner guid) to that AR/AP split, read from the lot's owner backref. No special transaction type, no sign analysis, no new block to detect. And because a cleared lot persists closed with its splits (decision 4), the detection works on cleared credits too.

The one wrinkle is the credit's **origin** split that shares the lot. For an **overpayment** origin it is already emitted as `prepayment:` on the invoice payment (Q-015), so export must emit the *clearing* split without re-emitting the origin. A **standalone-prepayment** origin (a credit received with no invoice) is not represented in plaintext today at all — that is a pre-existing gap, not one this feature introduces; the credits this feature targets come from overpayments, so standalone-origin representation is out of scope here.

**Still to probe** (needs the importer/exporter to exist): an `import → export → import` cycle to pin the exact lot/split topology the exporter walks. Lower risk than under the old auto-apply design, but build it first during implementation.

### 7. `find-prepayments` and the workflow note

`find-prepayments` already surfaces every open credit and currently advises either consuming via `auto_apply_credit:` or the destructive "delete the source bank tx" refund. Update its guidance (and `README.md`) to point at the new non-destructive path — a normal transaction with the AR/AP split tagged `customer:`/`vendor:` — as the canonical way to dispose of a credit (refund, write off, or forfeit), keeping the delete path only as the standalone-payment shortcut.

### 8. User-facing surface: discovery, the `open_prepayment:` summary, and a `clear-prepayment` CLI

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
    - **Import** recomputes open prepayments from the book in a **post-import pass** (the account block is read before the transactions that create the lots, so it cannot be checked at account-creation time). The `customer_guid:`/`vendor_guid:` is the key it resolves on. On a mismatch it prints a **warning to stderr** (owner, declared vs actual) and **import still succeeds** — the book's actual lots are authoritative, and the next export self-heals the file. This is softer than `entry_amount`/`entry_tax`, which error, because those guard posted-record integrity while this is a self-correcting summary.

**Action — two ways, both running the proven primitive lot-attach (decision 5):**

- The `transaction:` directive with the tagged AR/AP split (power / AI-assisted / bulk editing).
- A `clear-prepayment` convenience CLI for users who would rather not hand-write the transaction:

  ```
  gnucash-plaintext clear-prepayment book.gnucash \
      --customer C001 --amount 50 --to "Assets:Bank" --date 2026-02-15 --memo "Refund"
  gnucash-plaintext clear-prepayment book.gnucash \
      --vendor V001 --amount 50 --to "Expenses:Bad Debt" --date 2026-02-15
  ```

  It resolves the owner's oldest open prepayment lot and builds the clearing transaction. `--to` is the counter account (asset ⇒ refund, expense ⇒ vendor bad debt, income ⇒ customer forfeit, validated by owner per decision 1). Rejects when the owner has no open prepayment.

---

## Linking an already-imported transaction

When the actual outflow already exists in the book (e.g. imported from a bank feed with an `Imbalance` counter-split), the user should be able to turn it into the credit clearing rather than create a duplicate bank transaction. Because the clearing is just a `transaction:`, this rides the directive's existing GUID identity (Q-016): the user writes the transaction carrying the existing bank transaction's `guid:` and re-targets its counter-split to the AR/AP account with the `customer:`/`vendor:` tag. The importer matches the transaction by GUID, updates the split to AR/AP, and attaches it to the owner's open prepayment lot. No separate linkage field is needed — the transaction GUID is the link.

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
| 4.9 | Ubuntu 24.04 | ✓ | ✓ | ✓ |
| 4.13 | Debian 12 | ✓ | ✓ | ✓ |
| 5.10 | Debian 13 | ✓ | ✓ | ✓ |
| 5.13 | Fedora 41 / openSUSE | ✓ | ✓ | ✓ |
| 5.14 | Ubuntu 26.04 / Arch | ✓ | ✓ | ✓ |

The auto-apply path (`gncOwnerApplyPaymentSecs` with `auto_pay`) **segfaults on GnuCash 4.4 and 4.8** — reproducibly, through pure SWIG using the book's own engine instance (so it is not a ctypes/instance-mismatch artifact). The crash is *inside* `gncOwnerAutoApplyPaymentsWithLots` when it nets the new payment lot against the existing credit lot: creating the prepayment lot (`+N`) returns fine, the offsetting `−N` payment crashes. The non-monotonic pattern (ok 3.8 / broken 4.4–4.8 / ok 4.9+) points to an early-4.x engine regression fixed by 4.9.

**The primitive lot-split path (decision 5) avoids the bug entirely and passes on all ten builds** — so this is resolved, not an open question: there is no version gate. Intermediate snapshots (identical on 3.8 / 4.4 / 4.8 / 5.10) show the mechanic step by step:

```
A customer full refund:   credit created  AR=-50 bank=+50  lot bal=-50 splits=1 open
                          after refund     AR= 0  bank=  0  lot bal=  0 splits=2 closed
B customer partial 20/50: after refund     AR=-30 bank=+30  lot bal=-30 splits=2 open
C vendor bad debt:        credit created  AP=+50 bank=-50  lot bal=+50 splits=1 open
                          after write-off  AP=  0 bank=-50  baddebt=+50  lot bal=0 splits=2 closed
```

(In every case the offsetting split joins the existing lot — splits 1 → 2 — and the balance moves to 0 for a full clear or to the residual for a partial.) Invoice/bill *payments* — including an invoice bad-debt write-off — are unaffected on all versions regardless, because they close the document's own lot and never net two lots.

**Still not probed**: export / round-trip detection of a credit-clearing transaction (decision 6) — requires the importer/exporter to exist.
