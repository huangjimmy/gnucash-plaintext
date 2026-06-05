---
id: Q-024
title: Unapply a payment from a posted invoice/bill without unposting it
category: quality
severity: medium
status: closed
---

## Problem

There was no way to take a payment *off* an invoice/bill while leaving the document posted. Removing a payment via re-import falls through to the destructive unpost-rebuild-repost path, which drops the record to Draft and detaches everything — wrong when the document is correct and only the payment is misplaced. The motivating case: an income/deposit transaction was linked to an invoice but turned out not to belong to it. You can't delete the transaction (the money really moved), and unpost-then-repost is not the right move; the right move is to revert to the state *before that payment was applied* — still **posted**, just **not paid** (or partially paid if other payments remain).

This is a distinct operation from unpost/void:

| | unapply-payment | unpost / void |
|---|---|---|
| document | untouched, stays **posted** | drops to **Draft** |
| posting tx / lot | kept (lot just reopens) | destroyed |
| the payment | detached → re-homed, kept | orphaned bank tx |

## Fix

A new `unapply-payment` CLI command, sibling to `unpost-invoices`:

```
gnucash-plaintext unapply-payment <book> <id> --to <account> [--txn <guid> | --all] [--bill] [--by-guid]
```

It detaches a payment's AR/AP split from the record's posted lot (`gnc_lot_remove_split`, probed safe on all 10 GnuCash builds) so the lot reopens — invoice returns to Outstanding, or partially-paid if other payments remain — and re-homes the freed split to `--to <account>` (`xaccSplitSetAccount`; the amount is unchanged so the transaction stays balanced). The document stays posted; the bank/income transaction is never deleted.

Key decisions:

- **`--to` is required, any account type.** The freed split's prior account (Imbalance, Income, a clearing account) was overwritten by the apply step and never recorded, and money no longer applied to an invoice is a payable you may owe back — only the user knows which account represents that in their chart (often a `LIABILITY` "Due to shareholder", possibly an asset carried negative). There is no defensible silent default, so the destination must be named; the account type is not constrained (same lesson as Q-022).
- **Identity by GUID, never amount.** Two payments can share an amount, and floats can't represent decimals exactly, so the selector (`--txn`) and every internal match key on the payment transaction's GUID. Amounts are read exactly (`gnc_numeric` → `Decimal`/`Fraction`), never via `to_double`.
- **Selection.** One payment on the record → no selector needed; several → `--txn <bank-tx-guid>` to peel one, **repeated `--txn`** to peel a subset (e.g. two of three wrong payments), or `--all` for every payment; omitting all selectors on a multi-payment record is an error, never a guess.
- **Payment enumeration is version-robust.** A payment is any transaction with a split in the lot other than the record's own posting transaction — no dependence on `xaccTransGetTxnType == 'P'`, which isn't reliably set on every version for retargeted / shared-bank-tx payments (it silently dropped the multi-invoice case on GnuCash 3.8).

## Files touched

| File | Change |
|---|---|
| `use_cases/unapply_payment.py` | `unapply_payments` / `execute_unapply`: resolve the record, enumerate lot payments by GUID, detach + re-home the selected split(s), exact `Decimal` amounts. |
| `cli/unapply_cmd.py` | `unapply-payment` command with `--to` (required), `--txn`, `--all`, `--bill`, `--by-guid`; clear per-status errors. |
| `cli/main.py` | Register `unapply-payment`. |
| `tests/integration/test_unapply_payment.py` | 11 tests (below). |

## Tests

On GnuCash 3.8 and 5.10: single-payment reopen + re-home; one-of-two payments → partial state; **two-of-three payments via repeated `--txn`** (the third stays applied); `--all` → fully Outstanding; **one of several invoices sharing one bank tx** (only that invoice reopens; the shared tx survives); **two same-amount payments selected by GUID** (the case that defeats amount-matching); bill (AP) side; the invoice stays posted and round-trips; and the guards (`--to` required, unknown invoice, unknown `--to` account, multi-payment-without-selector).

## Related issues

- **Q-014 / Q-015 / Q-016** — the apply paths (`ApplyPayment`, the `txn_guid:` / `txn_split_guid:` retarget) this reverses; the payment-enumeration helper is shared with the unpost orphan-detection.
- **Q-021 / Q-023** — owner-attached credit lots; a future enhancement could re-home an unapplied payment back onto AR as an owner-attached credit rather than to a plain account.
- **Q-022** — the "don't constrain account types" lesson applied to `--to`.

---

**Created**: 2026-06-05
