---
id: Q-026
title: One bank tx paying multiple invoices/bills exports the bank total as each record's payment amount
category: quality
severity: medium
status: closed
---

## Problem

When a single bank transaction pays several invoices/bills (the Q-016 shared-bank-tx shape — one bank split plus one AR/AP split per record), the exporter wrote each record's `payment: amount:` as the **whole bank-tx total** instead of that record's own allocation. A $400 wire across three invoices ($100/$120/$180) exported `amount: 400` on **every** invoice. Both exporters were affected: the round-trip business-object export (`export_business_objects.py`) and the `print-invoice` / `print-bill` render (`invoice_renderer.py`, `bill_renderer.py`) — each read the bank-side split's amount rather than the AR/AP split sitting in the record's own lot.

It is an audit-fidelity bug: re-import attaches each portion by `txn_split_guid:` (by GUID), so the wrong `amount:` round-trips invisibly and the reconstructed book is correct — which is why no test caught it. The structural roundtrip tests compare reconstructed state (lots/balances/GUIDs), and that state does not depend on the `amount:` text; single-invoice tests can't expose it because with one AR split the allocation equals the bank total.

## Fix

Emit each record's **own allocation** — the AR/AP split in its lot (`in_lot_ar_ap_split` / the lot split `s`) — not the bank-side total. While here, format the amount **exactly and currency-correctly**: a new `format_amount_for_commodity` reads the value via `num()/denom()` into a `Decimal` and quantizes to the commodity's own decimal count (`get_fraction()`), never via `to_double()`. So a 2-decimal currency exports `100.00` and a 0-decimal currency (JPY, fraction 1) exports `1000` — driven by the book's commodity definition. The sibling `prepayment:` residual is summed exactly (Fraction) and formatted the same way.

Note: GnuCash's commodity table records KRW with fraction 100 (2 decimals) despite real-world KRW being 0-decimal; the exporter faithfully follows whatever fraction the book's commodity defines.

## Files touched

| File | Change |
|---|---|
| `infrastructure/gnucash/utils.py` | `format_amount_for_commodity(number, commodity)` — exact, currency-decimal-count formatting (no `to_double`). |
| `use_cases/export_business_objects.py` | Payment `amount:` from the in-lot AR/AP split; exact `prepayment:` sum; both formatted via the new helper. |
| `services/invoice_renderer.py`, `services/bill_renderer.py` | Payment `amount:` from the lot split, currency-formatted. |
| `tests/fixtures/business_objects_only.txt` | Reference updated to the currency-decimal payment amounts (`210.00`, …). |
| `tests/integration/test_multi_invoice_payment_amount.py` | New: per-invoice and per-bill allocation on a shared bank tx; print-invoice render allocation; JPY 0-decimal amount. |

## Tests

On GnuCash 3.8 and 5.10: multi-invoice export emits `100.00/120.00/180.00` (not `400`), multi-bill emits `90.00/110.00/160.00`, the print-invoice render emits the allocation, and a JPY invoice exports `1000` (0-decimal). The `business_objects_only.txt` roundtrip and the overpayment / fresh-roundtrip suites still pass.

## Related issues

- **Q-016** — the shared-bank-tx multi-invoice mechanism (`txn_split_guid:`) whose per-record amount this corrects.

---

**Created**: 2026-06-06
