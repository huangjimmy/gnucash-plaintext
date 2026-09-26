---
id: Q-023
title: Prepayment residual credit lots must be owner-attached (else invisible to the open_prepayment summary)
category: quality
severity: medium
status: closed
---

## Problem

When an existing over-paying deposit is linked to an invoice/bill (deposit > outstanding) via the `txn_guid:` retarget-with-prepayment path, the residual pre-payment lot was created but the customer/vendor was never attached as its owner. The `open_prepayment:` per-account summary and the `export-accounts` lot-walk surface only owner-attached credit lots (they resolve the owner via `gncOwnerGetOwnerFromLot`), so the residual credit existed in the book yet was invisible there — downstream tooling reading the summary saw no open credit and showed no badge.

This is a class of defect, not a one-off: **an ownerless AR/AP credit lot is never a valid state.** A credit that belongs to no owner can't be applied to that owner's next invoice, can't be refunded, and is hidden from every owner-keyed view. The omission was latent because the ownerless lot predates the `open_prepayment:` summary (Q-021) that first read the lot's owner — nothing read it back when these paths were written. Two paths created ownerless residual lots: the retarget-split path (`_retarget_with_prepayment_split`) and the loose-sibling parking on re-import of a `prepayment:` field (Q-015).

## Fix

Enforce owner-attachment on **every** path that creates a residual credit lot, via one shared helper `_attach_record_owner_to_lot`:

- `_retarget_with_prepayment_split` (initial overpayment link) attaches the owner;
- the `prepayment:` re-import loose-sibling parking loop attaches the owner to each parked lot.

`record.GetOwner()` returns the Customer/Vendor instance (the python-gnucash decorator unwraps the `GncOwner`), so a `GncOwner` is built from it via `gncOwnerInitCustomer` / `gncOwnerInitVendor` before attaching with `gncOwnerAttachToLot` — passing the raw Customer pointer is a silent no-op.

Because an export of an owner-attached residual now carries `lot_owner:` on that split, a fresh re-import attaches it during the standalone-tx pass; the `prepayment:` validation therefore counts residual siblings that are **already parked** (in their owner lot), not only loose ones, so the round-trip neither errors nor double-creates.

**Guard so it can't silently regress:** `find-prepayments` warns about any open non-invoice AR/AP credit lot no owner can be read for (account + amount), from the `unowned` list `find_prepayments_in_book` fills. No import path leaves such a lot. GnuCash's View → Lots can make one ("New Lot" attaches no owner), so the warning says how to attach an owner to it: `lot_owner:` on its split and `import --strategy update`.

## Files touched

| File | Change |
|---|---|
| `services/gnucash_importer.py` | `_attach_record_owner_to_lot` helper; called from `_retarget_with_prepayment_split` (now takes `record`) and from the `prepayment:` loose-sibling parking loop; the prepayment validation counts already-parked residual siblings, not only loose ones. |
| `use_cases/unpost_business_objects.py` | `find_prepayments_in_book(book, unowned=[])` fills `unowned` with the open non-invoice AR/AP credit lots it passes over because no owner can be read for them. |
| `cli/find_prepayments_cmd.py` | Emits a warning listing any ownerless credit lot found in the book. |
| `tests/integration/test_retarget_prepayment_credit_visible.py` | export-accounts visibility (invoice + bill); the no-ownerless-lot invariant after a retarget overpayment; and the CLI guard firing on a crafted ownerless lot. |

## Tests

The visibility and invariant tests fail on the pre-fix code (no `open_prepayment:` block; an ownerless lot present) and pass after. The guard test crafts an ownerless lot directly and asserts both the `unowned` list and the `find-prepayments` warning surface it. Verified on GnuCash 3.8 and 5.10; the overpayment-handling, fresh-roundtrip, find-prepayments, and prepayment-settlement suites still pass.

## Related issues

- **Q-015** — introduced the retarget-with-prepayment mechanic and the `prepayment:` re-import parking whose residual lots this fixes.
- **Q-021** — added the `open_prepayment:` summary / `gncOwnerGetOwnerFromLot` lot-walk that requires the lot owner, and the standalone `lot_owner:` attach this mirrors.

---

**Created**: 2026-06-05
