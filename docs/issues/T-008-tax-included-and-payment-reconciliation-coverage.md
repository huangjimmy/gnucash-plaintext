---
id: T-008
title: tax_included pricing branch untested; discovered bill tax flags not persisted; payment/credit reconciliation gaps
category: tests
severity: high
status: open
---

## Problem

The `tax_included: true` (tax-inclusive pricing) branch — where the entered
price already contains the tax and the code backs the net out via
`net = gross / (1 + total_rate)` — existed in both
`services/invoice_renderer.py` (`compute_entry_informational`) and
`services/bill_renderer.py` (`compute_bill_entry_informational`) but had **no
fixture or test**. Adding coverage for both invoices and bills uncovered a
production bug and several adjacent reconciliation gaps.

### Production bug found (and fixed)

Vendor-bill entries were attached to the bill with SWIG `Invoice.AddEntry`
(`gncInvoiceAddEntry`), the **customer-invoice** owner API, which sets the
entry's *invoice* pointer. GnuCash's entry XML writer guards the bill-side tax
flags behind `if (gncEntryGetBill(entry))`, so those entries serialised on the
invoice side (`entry:invoice`, `i-taxincluded`) and **never persisted
`entry:b-taxable` / `entry:b-taxincluded`**. Consequently `tax_included: true`
(and `taxable: false`) on a bill silently reverted on save/reload, over-taxing
the bill. Proven by an XML probe: an entry added via `gncBillAddEntry` writes
`<entry:bill>` with `b-taxincluded=1`, whereas `Invoice.AddEntry` omits it.
This also explains — and supersedes — the earlier CLAUDE.md finding #8 belief
that GnuCash "cannot persist `bill_taxable = false`".

Root cause and fix: the importer built and looked up vendor bills with the
**`Invoice`** class, so `bill.AddEntry` / `bill.RemoveEntry` resolved to the
customer-invoice functions. The Python bindings do provide a `Bill(Invoice)`
class whose `AddEntry` / `RemoveEntry` dispatch to `gncBill*`. All production
paths now construct and wrap vendor bills as `Bill` (via `wrap_invoice_or_bill`),
so the correct functions are used with no ctypes workarounds. Removing the
ctypes helpers and using `Bill.RemoveEntry` also avoids the GnuCash-3.8 rebuild
segfault the ctypes helper was originally added for — verified on Ubuntu 20.04,
22.04 and Debian 13.

### Reconciliation coverage gaps (untested before this work)

- overpayment / partial payment on a **taxed** invoice/bill (payment applied
  against the tax-inclusive total);
- settling one document with a **mix** of a fresh `ApplyPayment` and a linked
  existing bank tx (`txn_guid:`), then `unapply-payment` (single / `--all`) and
  re-link — on the bill side (`--all` and multi-partial bill unapply were
  uncovered);
- a vendor/customer **credit consumed across two documents** (second goes
  partial when the credit runs out) and credit + cash settling two documents;
- credit **owner attribution** across several vendors/customers;
- refund tests asserted only that the credit lot closed, not that the cash
  actually moved or that no expense/income was touched.

## Affected files

- `services/gnucash_importer.py` — vendor bills constructed/looked up as the
  SWIG `Bill` class + `SetBillTaxIncluded`; `infrastructure/gnucash/utils.py`
  `wrap_invoice_or_bill` classifies every `gncInvoice` query result
- `use_cases/delete_business_objects.py`, `use_cases/export_business_objects.py`,
  `cli/bill_print_cmd.py`, `cli/invoice_print_cmd.py` — bills wrapped as `Bill`
- `services/invoice_renderer.py`, `services/bill_renderer.py` (branch under test)
- `tests/integration/test_tax_included_pricing.py`,
  `test_overpayment_partial_payment_with_and_without_tax.py`,
  `test_taxed_bill_mixed_payment_unapply_and_relink.py`,
  `test_credit_attribution_multiple_owners.py`,
  `test_credit_consumption_across_bills.py`,
  `test_credit_consumption_across_invoices.py`,
  `test_prepayment_settlement.py` (strengthened refunds)
- `tests/fixtures/*` (tax_included_*, overpay_partial_*, hero_*, credit_*)
- `tests/research/bill_payment_reconciliation_probe.py`
- `docs/bill-payment-reconciliation.md` (new), `docs/invoice-payment-reconciliation.md`
- `tests/fixtures/business_objects_only.txt` (reference now reflects persisted
  `taxable: false`), `CLAUDE.md` finding #8 corrected

## Resolution

Addressed in branch `test/tax-included-pricing`: the `gncBillAddEntry` fix, the
tax_included coverage for invoices and bills, and the payment / credit
reconciliation tests and docs above. Close on merge to `main`.
