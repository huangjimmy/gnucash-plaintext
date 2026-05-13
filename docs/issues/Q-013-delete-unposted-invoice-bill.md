---
id: Q-013
title: No way to delete an unposted invoice or bill from the CLI
category: feature
severity: medium
status: open
---

## Problem

Users can create unposted invoices/bills (via re-import with
`posted: none`) but have no way to remove them again short of editing
the .gnucash XML by hand or opening GnuCash's UI. Real-world drivers:

- A user imports a batch invoice .txt, notices a row was a typo
  (wrong customer, wrong amount), wants to drop the invoice and
  re-import a corrected version.
- A user previews an unposted invoice as a PDF (Q-012), decides it's
  not needed, and wants to delete it cleanly without having to first
  give it a posted block.

For posted invoices, `unpost-invoices` (Q-010) is half the workflow.
Q-013 is the other half: after unposting, drop the record entirely.

## Scope

Add two CLI commands that mirror `unpost-invoices` / `unpost-bills`
exactly:

```
gnucash-plaintext delete-invoices <book> <id>... [--by-guid]
gnucash-plaintext delete-bills    <book> <id>... [--by-guid]
```

Behaviour:

| Record state         | Result        | Message                                                   |
|----------------------|---------------|-----------------------------------------------------------|
| Unposted, found      | `DELETED`     | `<id> (<guid>): deleted`                                  |
| Posted, found        | `FAILED_POSTED` | `<id> (<guid>): failed — posted; run unpost-<kind> first` |
| Not found            | `NOT_FOUND`   | `<id>: not found`                                         |
| Ambiguous id (legacy)| `AMBIGUOUS_ID`| `<id>: failed — multiple records share this id; rerun with --by-guid` |

Exit code 1 if any record didn't reach DELETED; successful deletes
still saved.

## Refusing posted records — why not auto-unpost?

A `delete-invoices` that silently unposted-then-deleted would:

1. Destroy the posting transaction and orphan any payment splits
   (matching `unpost-invoices` behaviour) **as a side effect of a
   delete command**. The user gave one instruction; we'd be doing
   two destructive operations.
2. Make it impossible to ever delete a "did I really mean this?"
   record without first running `unpost-invoices` and being able to
   review what got orphaned.

Requiring the explicit two-step `unpost-invoices` → `delete-invoices`
chain keeps each destructive operation under its own command and
matches the project's general "make destructive things visible" stance.

## Implementation strategy

Mirror `unpost-business-objects.py` structure (already in the
codebase since Q-010):

- New `DeleteInvoicesUseCase` + `DeleteBillsUseCase` in
  `use_cases/delete_business_objects.py`.
- New status enum `DeleteInvoiceStatus` (separate from existing
  `DeleteStatus` for customers to keep their result shapes distinct).
- Lookup via `services.gnucash_importer._find_invoices_by_id` /
  `_find_invoice_by_guid` (same helpers `unpost_business_objects`
  uses) — DRY and consistent with the unpost path.
- Action: `inv.Destroy()` (SWIG `Invoice.Destroy()`).

### Open question to verify in tests (CLAUDE.md finding #8)

`gncEntryDestroy` does NOT detach from the parent invoice/bill's
internal entry list (Q-007 / Q-009 hard-won finding). The importer
works around this by calling `invoice.RemoveEntry(entry)` or
`_bill_remove_all_entries(book, bill)` before destroying entries.

It's unclear whether `gncInvoiceDestroy` cascades through the entry
list correctly or has the same dangling-pointer hazard. Two
possibilities to discover via tests:

1. **Best case:** `Invoice.Destroy()` cleans up entries internally;
   we just call it and move on.
2. **Worst case:** we have to call `RemoveEntry` (invoice side) or
   `_bill_remove_all_entries` (bill side) before `Destroy()`, same
   asymmetric SWIG↔ctypes split as the importer.

Tests must cover the "destroy invoice with entries" path on every
supported distro — the importer's bug only surfaced visibly on
ubuntu20 (GnuCash 3.8) per the 2026-05-08 post-mortem, so multi-
distro CI is load-bearing here.

## Files to add / change

| File | Change |
|---|---|
| `use_cases/delete_business_objects.py` | Add `DeleteInvoiceStatus`, `DeleteInvoiceResult`, `DeleteInvoicesUseCase`, `DeleteBillsUseCase` |
| `cli/delete_cmd.py` | Add `delete-invoices` + `delete-bills` click commands; share a `_run_delete_invoice` helper with the same save-on-partial-success pattern as `_run_delete` |
| `cli/main.py` | Register the two new commands |
| `tests/integration/test_delete_invoice_bill.py` (new) | Unposted invoice deleted; unposted bill deleted; posted refused with FAILED_POSTED; not-found path; ambiguous-id path; --by-guid path; save persists deletion across reload; entries-with-tax-table deleted cleanly |
| `tests/fixtures/q013_*.txt` (new) | Reusable fixtures |
| `README.md` | Document the new commands; cross-reference unpost commands |
| `docs/issues/README.md` | Index row |

## Out of scope

- Auto-unpost-then-delete shortcut (see "Refusing posted records").
- Deleting customers/vendors (already `delete-customers` /
  `archive-customers`).
- A separate `delete-paid-invoices`-style command that handles AR/AP
  cleanup — that's a different problem (no clear user request, and
  the accounting consequences are non-obvious).

---

**Created**: 2026-05-12
