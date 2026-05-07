# Post-mortem: bill PostToAccount segfault on GnuCash 3.8

**Date:** 2026-05-08
**Branch / PR:** Q-009 / unposted→posted re-import (Q-007 follow-up)
**Severity:** medium — would have shipped a latent dangling-pointer bug
masked by a workaround.
**Caught by:** multi-distribution CI (ubuntu20 / GnuCash 3.8). All
newer-GnuCash distros passed.

## What happened

While implementing the unposted→posted re-import behaviour, the
importer for vendor bills started calling `entry.Destroy()` on each
existing entry of an unposted bill before re-adding entries from the
plaintext directive. On debian13/ubuntu24/etc. this worked; on
ubuntu20 (GnuCash 3.8) the next call to `gncInvoicePostToAccount`
segfaulted inside the C library.

The first attempted fix was to **disable the feature on the failing
platform** — i.e. don't touch entries at all on existing unposted
bills, only run the posted/payment blocks. This made the test pass
on ubuntu20 but left the underlying bug in the code.

The reviewer pushed back ("should find out how to make it pass! not
ignoring!"), so the destroy-step was investigated again. The actual
cause turned out to be:

- `gncEntryDestroy(entry)` sets the `do_free` flag on the entry's
  QofInstance and removes it from the QofCollection.
- It does **not** detach the entry from the parent invoice/bill's
  internal entry list.
- `gncInvoicePostToAccount` later iterates that entry list and
  dereferences each pointer.
- On GnuCash 3.8 the dangling pointer crashes; on newer GnuCash the
  crash either doesn't happen (different memory layout) or is
  silently masked by null checks added since.

The correct fix is to detach the entry from its parent before
destroying:

- Customer invoices: `Invoice.RemoveEntry(entry)` (SWIG, wraps
  `gncInvoiceRemoveEntry`).
- Vendor bills: SWIG `Invoice.RemoveEntry` is **customer-only**, so
  bills need `gncBillRemoveEntry(bill, entry)` directly via ctypes.

After the fix, the destroy-and-rebuild path passes on every supported
distro.

## Timeline

| Step | Action |
|---|---|
| 1 | Tests for unposted→posted transition added; pass on debian13 (864 passed). |
| 2 | Pre-commit ran multi-distro suite. Ubuntu20 segfault in `gncInvoicePostToAccount` for `test_bill_unposted_can_be_posted_via_reimport`. |
| 3 | First attempted fix: stop touching entries on existing unposted invoices/bills. Tests pass on ubuntu20 but the actual bug is unresolved. |
| 4 | Reviewer pushed back — root-cause not workaround. |
| 5 | Investigation: `gncEntryDestroy` doesn't detach the entry from the invoice's list. Add `RemoveEntry` (or `gncBillRemoveEntry` via ctypes for bills) before `Destroy()`. |
| 6 | Fix verified on every distribution. |

## Why the wrong instinct kicked in

Honest read: the workaround instinct came from several biases working
together.

1. **Reframing the bug as "platform quirk".** The crash *only*
   reproduced on ubuntu20. The default story became "GnuCash 3.8 is
   weird" rather than "the destroy-step is wrong". Once a bug is
   labeled "platform quirk", investigation stops.
2. **Sunk cost on the existing diff.** The destroy-step had been
   written; backing it out felt like progress; investigating felt
   like more work.
3. **Tests pass elsewhere = good enough.** When debian13 passes, the
   "it works" signal feels stronger than the single failing platform.
   The latent dangling pointer was actually present on every
   platform; only one platform crashed visibly.
4. **Asymmetric cost framing.** Disabling the feature on one platform
   *feels* like a smaller compromise than tracking down a C-level
   memory bug. In reality the workaround would have shipped a real
   bug into newer GnuCash too — newer versions might dereference the
   dangling pointer at any point in the future.

## Lessons

### For the codebase

- **`gncEntryDestroy` does NOT remove from the parent's entry list.**
  Always call `RemoveEntry` first. Documented in
  `docs/DEBUGGING_GNUCASH_BINDINGS.md` (added as part of this fix).

- **SWIG `Invoice.RemoveEntry` is customer-only.** For vendor bills,
  call `gncBillRemoveEntry` via ctypes. The SWIG `Invoice` class
  presents a unified API but its `RemoveEntry` method silently maps
  to the customer-side C function. Same wrong-API pattern as
  `book.InvoiceLookupByID` not finding bills (Q-007 finding).

- **Multi-distribution CI is load-bearing.** Without ubuntu20 in the
  matrix this would have shipped. Don't reduce coverage to make CI
  green.

### For future work (process)

- When a test passes on platform A but fails on platform B, the
  default frame is "the failing platform caught a real bug", not
  "this platform is quirky". Investigate the root cause first.

- Resist the temptation to disable a feature on the failing platform
  to make the suite green. That's a workaround that hides a real
  problem.

- Read the C-level traceback and attribute the bug to the user's own
  code first. Only label it "platform incompatibility" with a
  stronger argument than the stack trace itself.

## How this finding accelerates future debugging

The same wrong-API trap has now bitten us at least twice with the
GnuCash bindings. Cataloguing the pattern explicitly:

### Recognise the "SWIG presents one API, C has two" smell

Several GnuCash entities have a unified Python class but distinct C
functions per owner type:

- `Invoice` → `gncInvoiceLookupByID` (customer) vs.
  `gncBillRemoveEntry` (vendor) — both bug-shaped; SWIG only wraps
  the customer side.
- `Invoice.RemoveEntry` → `gncInvoiceRemoveEntry` (customer-only).
  Vendor bills must use `gncBillRemoveEntry` via ctypes.

Whenever a SWIG class wraps something that has a customer/vendor
asymmetry in the C layer, treat the bill side as a separate code
path and verify with ctypes.

### Standard playbook for a single-platform crash

1. **Read the C-level traceback first.** The fault is in
   `gncInvoicePostToAccount`; the call chain leads from
   `import_bill`. Investigation should start at the C function, not
   at "is this a platform issue."
2. **Search this doc** (`docs/DEBUGGING_GNUCASH_BINDINGS.md`) for
   the function name and surrounding API. Several past landmines are
   already catalogued.
3. **Check whether `Destroy()` actually unhooks from the parent.** A
   QofInstance-level destroy is not the same as removing from a
   parent's list. Always look for a matching `Remove*` C function.
4. **Reproduce on the same docker image with a minimal script.** A
   one-off `./scripts/run.sh ubuntu20 python3 -c '...'` is faster
   than re-running the full pytest suite.
5. **Confirm the fix on the failing distro AND the distros that
   "passed."** A test that was passing only because the dangling
   pointer happened to land in cleared memory is still wrong.

### Diagnostic shortcuts

| Symptom | First place to look |
|---|---|
| Segfault in `gncInvoicePostToAccount` | Was `RemoveEntry` skipped before `Destroy` on a prior entry-mutation? |
| `book.InvoiceLookupByID(bill_id)` returns None | The lookup is customer-only; switch to a Query filtered by owner-type 4. |
| `Account(instance=raw_ptr)` segfaults | Wrong: walk the parent→children tree from `book.get_root_account()` instead. |
| `string_to_guid("hello")` returns 0 (not raise) | Check the int return value; raise `ValueError` yourself. |

## Why this matters for the product

A workaround that disables a feature on one platform looks small in
isolation, but the cumulative cost is high:

1. **The bug is real on every platform.** Newer GnuCash isn't
   immune; it just doesn't crash visibly *yet*. Memory layout and
   future GnuCash patches can promote a silent corruption into a
   segfault at any point. Shipping the workaround would have left
   that timer running on every supported distro.

2. **The product depends on dropping in to a wide GnuCash matrix.**
   Users on debian13 won't tolerate a feature that "works there" if
   the same input segfaults on a teammate's ubuntu20 box. The
   project's value proposition includes "your existing GnuCash
   install, whichever distro it lives on" — that promise is only
   credible if the multi-distro CI is allowed to gate merges.

3. **Trust compounds.** Every time the importer silently does the
   wrong thing — Q-006 customer dedup, Q-007 invoice/bill
   detection, Q-008 tax-table identity, this entry-list dangler —
   we lose user trust that re-import is safe. "Safe" here means *I
   can re-import this file and the result is what I expect, on any
   supported install*. Workarounds that say "well, on platform X we
   skip this part" make the trust assertion conditional and harder
   to reason about.

4. **The fix surface is small once found.** Adding `RemoveEntry` (or
   `gncBillRemoveEntry` via ctypes) before `Destroy` is a one-line
   change. The investment is in the diagnosis, not the patch — and
   the diagnosis pays back every time we touch business-object
   mutation code.

5. **Multi-distro CI is the safety net.** Without ubuntu20 in the
   matrix, this PR would have shipped a latent dangling-pointer
   bug. The cost of running 9 distros in parallel is far less than
   the cost of one user reporting a segfault that took six months
   to reproduce locally.

## Code citations

- `services/gnucash_importer.py` — `_bill_remove_all_entries` helper
  and the matching `Invoice.RemoveEntry` + `Destroy` sequence in
  `import_invoice` / `import_bill`.
- `docs/DEBUGGING_GNUCASH_BINDINGS.md` — finding documenting the
  RemoveEntry-before-Destroy pattern (added as part of this PR).
- `tests/integration/test_business_object_idempotent_reimport.py` —
  `TestUnpostedToPostedTransition` class. The failing test was
  `test_bill_unposted_can_be_posted_via_reimport`.
