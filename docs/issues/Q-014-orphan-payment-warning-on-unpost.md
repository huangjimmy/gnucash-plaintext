---
id: Q-014
title: `unpost-invoices` / `unpost-bills` don't warn about soon-to-be-orphan bank payments
category: quality
severity: medium
status: open
---

## Problem

`unpost-invoices INV-001` (and the bill-side `unpost-bills`) destroys the AR/AP posting transaction but **leaves the bank-side payment transaction in place**, orphaned from any lot. The user sees `INV-001: unposted` and nothing else — there's no indication that money still shows as received in the bank account, or that a subsequent re-pay-and-re-post cycle will silently duplicate the bank deposit.

Researched in full and documented in [`docs/research/2026-05-14-invoice-post-pay-unpost-cycle.md`](../research/2026-05-14-invoice-post-pay-unpost-cycle.md). The "Follow-up: can we track the orphan?" and "Bills: symmetric or not?" sections establish that the orphan is reliably identifiable at unpost time, and that the bill-side behaviour is fully symmetric to the invoice side.

## Why it matters

After `unpost-invoices` on a paid invoice, the book has:

- AR posting transaction: **destroyed** (✓ as intended)
- Bank-side payment tx: **survives, orphaned** — both splits intact (Bank +N, AR −N), same GUID
- Invoice plaintext: reverts to `payment: none` — the user sees no trace of the payment

If the user then re-posts and re-imports a fresh `payment:` block (the natural workflow), GnuCash creates a *second* bank transaction; the orphan from before unpost is never reattached. End state for a single $100 invoice paid once: **Bank +$200, AR −$100, Income +$100** — arithmetically balanced, semantically wrong, invisible to bank reconciliation.

The Q-004 `txn_guid:` retarget path is the only correct way to re-pay after unpost without duplication, but the user has no way to know that the orphan exists or what GUID to point at. The research test `tests/research/test_post_pay_unpost_cycle.py` walks the full six-step lifecycle and demonstrates the trap end-to-end.

## Fix

Make `unpost-invoices` and `unpost-bills` list the bank-side transactions that are about to be orphaned, with their GUIDs, dates, accounts, and amounts — at unpost time, before the user moves on. The research established that this is a ~5-line insertion using the pre-unpost path:

```python
lot = rec.GetPostedLot()  # called before rec.Unpost(False)
orphans = [
    split.GetParent() for split in lot.get_split_list()
    if xaccTransGetTxnType(split.GetParent()) == 'P'
]
```

The walk authoritatively names every payment transaction attached to the invoice's lot — **zero false positives**, since we read the still-intact lot membership before the unpost destroys it. The same code works for bills (the AR/AP filter and the owner reference work symmetrically — the only differences are sign and owner type, neither affecting the identification path).

### Output format

Per the research doc's CLI mockup. Happy path:

```
$ gnucash-plaintext unpost-invoices mybook.gnucash INV-001
INV-001 (969f5164…): unposted

⚠  1 bank-side payment transaction is now orphaned in the book.
   GnuCash unpost does not delete payment transactions — the money
   still shows as received in your bank account.

   • 2026-01-15  Assets:Bank  CAD 100.00  "Acme"
     memo: "Payment INV-001"
     guid: cf230c62-1c58-4aed-9c7b-97081f6f7bdd

   If you intend to re-pay this invoice, either:
     a) delete the orphan first with:
          gnucash-plaintext delete-transactions mybook.gnucash --by-guid \
              cf230c621c584aed9c7b97081f6f7bdd
        then re-import the invoice with a fresh `payment:` block, or
     b) re-import the invoice with a `payment:` block that includes
          txn_guid: "cf230c621c584aed9c7b97081f6f7bdd"
        to retarget the existing bank transaction into the new lot
        (see docs/issues/Q-004 for the retarget mechanism).
```

For `unpost-bills`, the wording flips to "AP transaction" / "money still shows as sent from your bank account" / etc. — same helper, output template parameterised on `"invoice"` vs `"bill"`, `"AR"` vs `"AP"`, `"received"` vs `"sent"`.

Cases to cover:

| Case | Output |
|---|---|
| One orphan | Single bullet as above |
| Multiple orphans (partial payments) | Multi-bullet block + "Total orphaned: CAD X.YZ across <bank account name(s)>" |
| Zero orphans (invoice posted but never paid) | No warning — silent success |
| Multiple invoice IDs in one call | Warning block per invoice that has orphans |

The exact spec is in the research doc, [section "4. CLI mockup"](../research/2026-05-14-invoice-post-pay-unpost-cycle.md#4-cli-mockup).

## Implementation outline

| File | Change |
|---|---|
| `use_cases/unpost_business_objects.py` | New helper `find_lot_payment_transactions(rec)` returning a list of `(tx_guid, date, account_full_name, amount, currency, memo, description, kind)` records. Lifted from `tests/research/orphan_detection_probe.py:find_pre_unpost_payments` |
| `cli/unpost_cmd.py` | Call the helper **before** `rec.Unpost(False)`, accumulate orphans per record, emit the warning block(s) after the per-record `unposted` line. Same callsite logic for both `unpost-invoices` and `unpost-bills` |
| Help text | Promote the orphan-payment caveat from a footnote to a first-class behavioural note. Cross-reference Q-004 and `delete-transactions --by-guid` |
| `tests/integration/test_unpost_invoice_bill.py` | New test cases: zero orphans (no warning), one orphan (warning printed, exact GUID + bank account + amount in output), multiple orphans (partial payments), bill-side equivalent of each, multi-invoice call surfaces orphans per record |

The research probe at `tests/research/orphan_detection_probe.py:find_pre_unpost_payments` is the working prototype. Lift directly; the four passing probe tests (`test_orphan_backreference_probe`, `test_orphan_backreference_probe_bill`, `test_find_orphan_payments_prototype`, `test_find_orphan_payments_prototype_bill`) cover both customer and vendor sides.

## Out of scope

The research surfaced three follow-up areas. Q-014 ships **only the warning**:

1. **Auto-cleanup CLI** — `unpost-invoices --cleanup-payments` flag or a dedicated `cleanup-orphan-payments <book> <invoice-id>` command. The research notes this is a useful safety net for users who already unposted and want to clean up after the fact, but it's a bigger design (separate command, separate confirmation, separate test surface). Defer to a future Q ticket.

2. **Post-unpost recovery helper** — the `find_orphan_payments_post_unpost` prototype in the probe walks the book heuristically (KVP owner ref + AR/AP-no-invoice filter). Useful as a building block for the cleanup CLI above, but not needed for the warning path. Defer.

3. **Plaintext orphan-flagging** — exporting orphan bank txs with a marker (e.g. `orphan: true` under the invoice's `payment:` block, or a `notes:` annotation) so export → import is lossless. Bigger design question for the plaintext format. Defer to a future Q ticket; the current behaviour is to emit orphans only in the free-form `transactions:` section.

Out-of-scope items are flagged in the research doc's "Implications for the codebase" section with the same numbering.

## Related issues

- **Q-004** — `txn_guid:` retarget mechanism. The warning text steers the user toward it as one of the two recommended cleanup paths.
- **Q-010** — `unpost-invoices` / `unpost-bills` CLI. The orphan caveat is currently a footnote in `cli/unpost_cmd.py`'s module docstring; Q-014 promotes it to user-visible output.
- **Q-013** — `delete-invoices` / `delete-bills`. The warning text references `delete-transactions --by-guid` (existing CLI, renamed from `delete-transaction-by-guid` in this branch for naming-consistency with the other delete-* commands) as the recommended way to clean up the orphan; Q-013's `delete-invoices` is a separate cleanup path for the unposted record itself.

---

**Created**: 2026-05-15
