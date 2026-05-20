---
id: Q-010
title: Q-009 'updated' status is liberal — reports 'updated' for no-change re-imports
category: quality
severity: low
status: closed
---

## Problem

After Q-009, the importer reports `'created'`, `'updated'`, or
`'skipped'` for each business-object directive. The status is meant
to let scripts and humans tell at a glance whether something actually
changed in the book.

But `'updated'` is liberal: it means "the importer passed through
the update code path", not "the record actually differs after
import". A re-import of an unchanged file currently shows:

```
customer "C001": updated
vendor "V001": updated
invoice "INV-001": updated   (when unposted)
```

…even though nothing in the book changed. Reported by an external
reviewer:

> Q-009's updated is liberal. Scenarios 4 and 5 should have been
> skipped per the README, but the actual implementation reports
> updated. Practically irrelevant to us (we treat both the same),
> but worth flagging upstream as a doc/code mismatch on their side.

The README implies (with "Update mutable fields in place") that
`'updated'` means "fields were updated". The code reports `'updated'`
even when no field changed. CI scripts asserting "exactly N
customers were updated" would over-count.

## Proposed fix: introduce a fourth status, `'unchanged'`

Tighten the code so `'updated'` means *"at least one mutable field
differs and was changed"*. If the directive matches the existing
record byte-for-byte, return a new status `'unchanged'`.

The four-status model resolves an overload that Q-009 introduced:
under Q-009, both "existing posted invoice — can't touch it" and
"existing customer — already matches" would have collapsed into
the same `'skipped'` bucket. They're semantically different:

| Status | Meaning |
|---|---|
| `created` | Fresh record created. |
| `updated` | Existing record had at least one mutable field changed. |
| `unchanged` | Existing record matches the directive — nothing to do, no work performed. |
| `skipped` | Existing record is immutable for this directive (e.g. posted invoice can't be re-edited). The user **wanted** a change but the record's state forbids it. |

`unchanged` is the happy path for an idempotent re-run. `skipped`
is "the importer chose not to apply your change because it isn't
safe."

Per object type:

### Customer / Vendor

Compare each mutable field before assigning:

- name
- addr1, addr2, addr3, addr4, email (customer only)
- active flag
- custom KVP slots

If **any** differs, set it and mark `changed = True`. Final status:
`'updated' if changed else 'skipped'`.

### Tax table

Already skips on hit (no entry mutation supported, ever). No code
change.

### Invoice / Bill (existing unposted)

The current code unconditionally destroys all entries and rebuilds
them from the directive — even when entries match. Two things to
fix:

1. **Add a pre-check helper** `_invoice_matches_directive(invoice,
   directive)` that returns True when:
   - `date_opened`, `billing_id`, `notes`, custom KVP all match
   - existing entry count == directive entry count, and each entry
     matches positionally on date, description, action, account,
     quantity, price, taxable, tax_included, and tax_table
   - directive has no `posted:` block (otherwise posting would
     transition state — definitely a change)
   - directive has no `payment:` block
   If True → return `'skipped'` early; do not touch the book.

2. **Otherwise** do the destroy+rebuild as before, return
   `'updated'`.

Same shape for bills (`_bill_matches_directive`).

### Invoice / Bill (existing posted)

**Pre-Q-010 (Q-007 status quo)**: existing posted invoice/bill is
treated as immutable — re-import returns `'skipped'`.

**Gap closed by Q-010**: GnuCash's UI itself supports unpost → edit →
repost. The pre-Q-010 importer made every posted invoice/bill a
permanent dead-end for re-imports. Common user flow that broke:

1. User imports invoice with a posted block (creates AR posting tx).
2. User notices a typo in the entry (wrong quantity, wrong account).
3. User edits the .txt and re-imports.
4. Pre-Q-010: silent `skipped` — change not applied, no warning.

**Q-010 behaviour**: an existing posted invoice/bill is now treated
the same way GnuCash treats it — mutable via unpost-edit-repost.

| Existing | Directive | Action | Status |
|---|---|---|---|
| posted, fields match | posted: same block, same entries, same payments | no-op | `unchanged` |
| posted, fields differ | posted: { ... } different | `Unpost(False)` → rebuild entries → `PostToAccount(...)` → re-apply payments per directive | `updated` |
| posted | `posted: none` | `Unpost(False)` → rebuild entries → leave unposted | `updated` |

Implementation in `import_invoice` / `import_bill`:

```python
if existing is not None:
    if _invoice_matches_directive(existing, directive, book):
        return 'unchanged'
    if existing.GetPostedTxn() is not None:
        # Unpost destroys the posting transaction. Payment transactions
        # remain in the bank account but their AR/AP splits become
        # orphaned (lot is gone). The directive's payment: block (if any)
        # then drives re-application from scratch.
        existing.Unpost(False)
    status_on_success = 'updated'
    # Fall through to existing rebuild + repost flow.
```

**Optimisation: minimal-unpost path.** When the *only* difference
between existing and directive is `posted: { ... }` → `posted: none`
(entries match, payments match, every other field matches), the
importer takes a fast path: just `Unpost(False)`, no destroy and no
rebuild. Result: **entry GUIDs are preserved**. Useful for users who
edit the .txt to unpost (instead of edit+repost) without breaking
external references. See `_is_only_unpost_diff` in
`services/gnucash_importer.py`.

**Dedicated CLI commands**: `unpost-invoices` and `unpost-bills` are
also added in this PR (`cli/unpost_cmd.py`, `use_cases/
unpost_business_objects.py`). They don't read any .txt — they call
`Unpost(False)` directly. Use this when the .txt is stale or absent
and you only want the unpost itself, or when you want to avoid
destructive entry rebuilds even in edge cases the matcher doesn't
cover. Per-record output mirrors `delete-customers`:

```
INV-2026-001 (abc123…): unposted
INV-2026-002 (def456…): not posted (already unposted)
INV-2026-003: not found
```

**Known limitation (Q-010 v1)**: payment transactions linked to the
old lot are orphaned (not destroyed) by `Unpost` regardless of which
path triggered the unpost. If the directive's new `payment:` block
re-uses the same `txn_guid:`, retargeting still works. If the
directive has no `payment:` block, the old payment transactions
remain in bank but are no longer tied to the invoice. A future issue
can add a "destroy orphan payment txns" cleanup if that turns out to
be confusing in practice.

## What this enables

Scripts can rely on `updated` for "real change happened" and
`unchanged` for "idempotent no-op," with `skipped` reserved for
"the importer refused to mutate":

```bash
$ gnucash-plaintext import book.gnucash invoices.txt --include-business-objects | tail -10
Business Objects:
  Customers:   0 created, 0 updated, 50 unchanged, 0 skipped    ← idempotent re-run
  Invoices:    0 created, 1 updated,  0 unchanged, 49 skipped   ← 1 unposted invoice edited; 49 posted, untouched
```

vs the current behaviour where a clean re-run shows `50 updated, 0
skipped` (over-counts change) and a posted-invoice-skip looks
identical to a no-change pass-through.

## Files to change

| File | Change |
|---|---|
| `services/gnucash_importer.py` | `import_customer` / `import_vendor`: field-by-field compare before set; return `'skipped'` on no diff. New helpers `_invoice_matches_directive` and `_bill_matches_directive`. `import_invoice` / `import_bill`: short-circuit return when matcher says no change. |
| `tests/integration/test_business_object_idempotent_reimport.py` | New `TestNoChangeReimportIsSkipped` class with 6 tests: customer/vendor no-change, customer-with-name-change, customer-with-KVP-added (should still be `updated`), unposted invoice/bill no-change. |
| `tests/integration/test_business_object_import_summary.py` | Existing tests `test_reimport_shows_updated_for_customers_vendors` and `test_reimport_summary_counts` need updates — the new behaviour reports `'skipped'`, not `'updated'`, for the no-change re-import path. |
| `README.md` | "Re-import semantics" section: clarify what `'updated'` means now (real change) vs `'skipped'` (no diff or immutable target). |

## Out of scope

- Comparing transactions: separate subsystem, not part of business
  objects.
- A `--quiet` / `--verbose` flag.
- Cleaning up orphan payment transactions left behind by `Unpost`
  (see "Known limitation" above) — deferred to a follow-up issue.

## Related

- **Q-014** — orphan-payment warning at `unpost-invoices` / `unpost-bills`
  time. Closes the "known limitation" above for the dedicated CLI path.
- **Q-015** — extends the orphan warning to every importer-side
  `Unpost(False)` callsite (the destructive rebuild that Q-010
  introduced).
- **Q-016** — generalises the `txn_guid:` retarget contract from
  "supported on the unpost → re-import path" to "emitted on every
  exported `payment:` block so a fresh-book re-import reconstructs the
  same routing deterministically". The `posted: { ... } → posted: none`
  minimal-unpost optimisation introduced here continues to preserve
  entry GUIDs, and Q-016 additionally preserves bank-tx and per-split
  GUIDs across the export → re-import cycle.

---

**Created**: 2026-05-08
