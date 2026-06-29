---
id: Q-033
title: Natural Receivable/Payable account-type strings are rejected, silently dropping accounts
category: bug
severity: high
status: closed
---

## Problem

A book that used the natural account-type spellings `type: "Receivable"` / `type: "Payable"` imported with those accounts **missing a type**, so they vanished from the balance sheet and it read **NOT BALANCED**. The symptom looked like the earlier Bank-type drop fixed in Q-032 (#82), but it was a different layer: the balance-sheet classification already covers RECEIVABLE/PAYABLE — the **importer** never gave the accounts those types.

Repro (`tests/fixtures/receivable_payable_natural_form_book.txt`): Cash 600 + Trade receivable 400 = 1000 assets, Trade payable 250, Equity 750. Before the fix, `import` reported a vague `'Receivable'` error, `balance-sheet` showed only Cash and Equity, and `Assets = Liabilities + Equity` failed (600 ≠ 750).

## Cause

`services/gnucash_importer.py`'s `ACCT_TYPE_MAP` only knew `"Accounts Receivable"` / `"A/Receivable"` and `"Accounts Payable"` / `"A/Payable"`. The bare `"Receivable"` / `"Payable"` raised a `KeyError` on `ACCT_TYPE_MAP[...]`, and `create_account` had already attached the account to the tree before that line — so the account survived with type `INVALID` (-1) and its splits were dropped. The balance sheet then correctly ignored the typeless account.

The docs compounded it:
- The README listed `Other Assets` (not a type — should be `Asset`) and `Expenses` (should be `Expense`).
- `docs/gnucash-beancount-format.md` and `docs/issues/F-010-…` showed native-plaintext examples using the uppercase XML-enum forms `type: "BANK"` / `type: "EXPENSE"`, which the importer doesn't accept either.

So a user following the docs hit the same silent failure.

## Fix

- `ACCT_TYPE_MAP` now also accepts the natural `Receivable` / `Payable`, and the README spellings `Other Assets` (→ Asset) / `Expenses` (→ Expense).
- `create_account` resolves the type **before** attaching the account, so an unrecognised type raises a clear, actionable error that names the bad type and lists the supported ones — instead of a cryptic `KeyError` that half-creates an INVALID account. The error stays non-fatal and is surfaced in the import summary (matching the existing `test_import_new_reports_account_creation_error` design), but it can no longer pass silently with an account left untyped.
- Docs corrected: README's account-type list is precise and lists the accepted spellings; the uppercase native `type:` examples in `docs/gnucash-beancount-format.md` and `docs/issues/F-010-…` are now the canonical title-case forms.

This is distinct from **Q-003**, which added the exporter's short forms (`A/Receivable` / `A/Payable`) so an exported file re-imports; here the strings are the ones a human writes by hand.

## Tests

- `tests/unit/services/test_account_type_map.py` — the natural `Receivable`/`Payable` and the README spellings map to the right GnuCash types.
- `tests/integration/test_balance_sheet_account_types.py::test_natural_form_receivable_payable_land_on_balance_sheet` — the repro imports as RECEIVABLE/PAYABLE (matched **by account type**, not name), lands in the right sections, and balances (Assets 1000 = Liabilities 250 + Equity 750).
- `tests/integration/test_cli_import.py::test_import_new_reports_account_creation_error` — an unknown type warns clearly: the summary names the bad type and lists the supported ones.

Passing on GnuCash 3.8 and 5.10.

## Related

- **Q-032** — the balance-sheet account-type classification (the symptom surfaced there, but the cause is the importer).
- **Q-003** — exporter short-form account types not re-importable (closed; different layer).

---

**Created**: 2026-06-28
