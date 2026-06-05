---
id: Q-022
title: Invoice/bill payment validation rejects owner's-equity deposit accounts
category: quality
severity: medium
status: closed
---

## Problem

Q-021 added validation that an invoice payment's transfer account must be an asset (cash) or an expense (bad-debt write-off), and a bill payment's must be an asset. That matrix only imagined "cash vs bad debt" and never considered **balance-sheet clearing / deposit accounts**, so it rejects a legitimate, common bookkeeping pattern: a **Canadian sole proprietor** has no separate business bank account — the T2125 business return reports only income and expense — so customer receipts (and vendor bills paid from personal funds) flow through **owner's equity** (`Equity:Owner equity:Owner's equity`), an `ACCT_TYPE_EQUITY` account. The importer raised "an invoice payment must use an asset account (cash payment) or an expense account (bad-debt write-off)" and refused the import.

(The corporate "shareholder loan" variant is *not* affected: a corp models "due from director" as an **asset**, which the asset case already accepts. Only the sole-prop owner's-equity account was blocked.)

## Why it matters

It blocked a real user from importing their books. The deposit-account model is correct double-entry accounting — `ApplyPayment` to an equity transfer account closes the AR/AP lot and records the receipt against owner's equity exactly as a bank account would — so there was no accounting reason to reject it; the validation was simply too narrow.

## Fix

Allow an `ACCT_TYPE_EQUITY` (10) account as a payment's transfer account on **both** sides (invoice and bill), alongside the existing asset case. The two documented Q-021 guards are kept:

- an **expense** remains **invoice-only** (a bill paid to an expense is debt forgiveness — a gain booked to income — out of scope), and
- **income** is still rejected on an invoice payment (it would double-count the revenue already recognised at posting), as are the AR/AP account itself and structural types (root, trading).

So the accepted transfer accounts are now: invoice → asset | owner's equity | expense; bill → asset | owner's equity.

## Files touched

| File | Change |
|---|---|
| `services/gnucash_importer.py` | `_validate_payment_account_type` accepts `_EQUITY_ACCT_TYPE` (10) on both sides; docstring and the two rejection messages updated to name the owner's-equity deposit account and explain the sole-proprietor rationale. |
| `tests/integration/test_payment_to_equity_clearing_account.py` | Regression: an invoice payment and a bill payment, each into `Equity:Owner equity:Owner's equity`, close the AR/AP lot and move the balance into owner's equity. |
| `tests/fixtures/q022_clearing_accounts.txt`, `q022_invoice_paid_to_equity.txt`, `q022_bill_paid_to_equity.txt` | Account tree with the sole-prop owner's-equity hierarchy, plus the invoice and bill that pay into it. |
| `README.md` | New "Sole-proprietor deposit account: paying into owner's equity" subsection; the bad-debt section now lists owner's equity as a valid transfer account for both sides. |

## Tests

Both new tests pass on GnuCash 3.8 and 5.10. The Q-021 bad-debt guardrails (`test_invoice_bad_debt.py` — invoice→income rejected, bill→expense rejected, invoice→expense write-off works) and the 13-test `test_prepayment_settlement.py` suite still pass, confirming the relaxation didn't weaken the kept guards or regress the clearing path.

## Related issues

- **Q-021** — added the payment account-type validation this issue relaxes. The over-restriction was a gap in Q-021's matrix, not a behaviour Q-021 intended; the bad-debt and income/bill-expense guards Q-021 documented are preserved.

---

**Created**: 2026-06-05
