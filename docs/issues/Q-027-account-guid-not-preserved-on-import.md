---
id: Q-027
title: Account GUIDs are not preserved on import, so they drift every roundtrip
category: quality
severity: medium
status: closed
---

## Problem

The exporter emits `guid:` on every `open` account directive (for external cross-reference, like every other object), and `'guid'` is a known account metadata key — but `create_account` never applied it. GnuCash minted a fresh GUID for each account on import, so account GUIDs **drifted on every export → import roundtrip**. The transaction, split, posting-tx, and customer/vendor/invoice/bill GUIDs were all already preserved; accounts were the lone exception, leaving external references to accounts by GUID broken across a roundtrip.

Found via a double-roundtrip probe (export → import → export): every GUID matched except the account GUIDs, which were re-minted.

## Fix

`create_account` now applies the declared `guid:` to the freshly created account via the existing `_set_object_guid` helper (ctypes `qof_instance_set_guid`, with the same book-wide uniqueness guard used for customers/vendors). Only newly created accounts are affected — re-import of an existing account returns early as before. Hand-written files may still omit `guid:` (GnuCash assigns one on first import); on re-export that GUID is then preserved.

## Files touched

| File | Change |
|---|---|
| `services/gnucash_importer.py` | `create_account` sets the account GUID from the declared `guid:` via `_set_object_guid`. |
| `tests/integration/test_multi_invoice_payment_amount.py` | `test_double_roundtrip_preserves_every_guid`: export → fresh import → export must keep **every** guid-bearing line identical (account, tx, split, posting, owner). |

## Tests

The double-roundtrip test fails on the pre-fix code (account `guid:` lines differ between the two exports) and passes after. Verified on GnuCash 3.8 and 5.10; the business-objects roundtrip and the rest of the suite still pass.

## Related issues

- **Q-006** — full GUID emission + the `_set_object_guid` mechanism for forcing a created object's GUID; this extends it to accounts.
- **Q-016** — transaction/split GUID preservation; accounts were the remaining gap.

---

**Created**: 2026-06-06
