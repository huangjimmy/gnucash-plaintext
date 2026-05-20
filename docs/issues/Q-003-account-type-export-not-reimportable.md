---
id: Q-003
title: Exported file is not re-importable (mixed indentation + account type short-forms)
category: quality
severity: high
status: closed
---

## Problem

Two related issues both prevent a full export → re-import round-trip.

### Issue 1: Mixed indentation in the exported file

The transaction/account exporter uses **TABs** for indentation; the business
objects exporter uses **2 spaces**. The parser auto-detects indentation from
the first indented line it encounters (a TAB from the commodity/account
section). When it reaches the space-indented business object blocks it cannot
parse metadata fields — `currency`, `name`, etc. are silently absent from
`directive.metadata`, causing:

```
Error: customer "C1": 'currency'
```

### Issue 2: Account type short-form strings

The transaction exporter writes account types using GnuCash's internal
short-form strings (`A/Receivable`, `A/Payable`) which do not exist in the
importer's `ACCT_TYPE_MAP`. After the mixed-indentation fix, this becomes the
next crash:

```
Error: account "Assets:Accounts Receivable": 'A/Receivable'
```

Together these mean a file produced by `gnucash-plaintext export` cannot be
fed back into `gnucash-plaintext import` unmodified.

## Confirmed by test

`tests/integration/test_payment_roundtrip.py::test_account_type_roundtrip`
(added 2026-05-06).

## Fix

**Issue 1 — mixed indentation**: the business objects exporter should use
TABs to match the transaction/account exporter, OR the transaction exporter
should use spaces to match business objects. TABs are the established
convention in the existing format; switch the business objects exporter to
emit TABs.

**Issue 2 — account type short-forms**: add the short-form aliases to
`ACCT_TYPE_MAP` in `gnucash_importer.py`:

```python
"A/Payable":    ACCT_TYPE_PAYABLE,
"A/Receivable": ACCT_TYPE_RECEIVABLE,
```

## Files to change

| File | Change |
|---|---|
| `use_cases/export_business_objects.py` | Replace 2-space indentation with TAB (`\t`) throughout all exported blocks |
| `services/gnucash_importer.py` | Add `'A/Receivable'` and `'A/Payable'` aliases to `ACCT_TYPE_MAP` (already done) |
| `tests/fixtures/business_objects_only.txt` | Update reference to use TAB indentation if business objects exporter is changed |
| `tests/integration/test_payment_roundtrip.py` | `test_account_type_roundtrip` should pass after both fixes |

## Related

- **Q-016** — `test_account_type_roundtrip` was the original roundtrip smoke test added here, but it only exercised `SINGLE_PAID_INVOICE` (a plain `ApplyPayment` payment, no `txn_guid:`) and asserted on `exit_code == 0`. It did not count bank transactions across the roundtrip, so the latent gap where exported payment blocks dropped `txn_guid:` and re-imported with duplicate bank transactions on a fresh book stayed hidden until Q-016 added explicit fresh-book roundtrip tests.

---

**Created**: 2026-05-06
