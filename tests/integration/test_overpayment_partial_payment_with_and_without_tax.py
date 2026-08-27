"""Overpayment and partial payment, WITH and WITHOUT tax, on bills and invoices.

The payment machinery works against the *payable total*, which for a record
with tax is net + tax. This module pins that for all four combinations
(overpay / partial × with tax / with no tax) on both sides, using a fresh
`ApplyPayment` (a `payment:` block with no `txn_guid:`):

  with tax:    net 100 + GST 5% + PST 7% = 112 total
  with no tax: 100 total

  overpay: pay 150 → record lot closes at 0; the residual opens a credit
           lot (150 − total): 38 with tax, 50 with none.
  partial: pay 60  → record lot stays open at the shortfall (total − 60):
           52 with tax, 40 with none (AP negative for bills, AR positive
           for invoices).

The link-existing-tx path and unapply/re-link are covered in
test_a_bill_with_tax_paid_partly_fresh_and_partly_linked.py.
"""
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import wrap_invoice_or_bill

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')


def _book(runner, tmp_path, fixture_name):
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    fx = tmp_path / fixture_name
    fx.write_text((FIXTURES / fixture_name).read_text())
    r = runner.invoke(cli, ['import', str(gf), str(fx),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'{fixture_name}: {r.output}'
    return gf


def _find(repo, obj_id):
    import gnucash.gnucash_business as gb
    from gnucash import Query
    q = Query()
    try:
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        return next((i for raw in q.run() for i in [wrap_invoice_or_bill(raw)]
                     if i.GetID() == obj_id), None)
    finally:
        q.destroy()


def _posted_lot_balance(gf, obj_id):
    """The record's own posted-lot balance: 0 when settled, and the signed
    shortfall while still owed (AP negative for bills, AR positive for
    invoices)."""
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        obj = _find(repo, obj_id)
        assert obj is not None, f'{obj_id!r} not found'
        lot = obj.GetPostedLot()
        assert lot is not None, f'{obj_id!r} not posted'
        return round(lot.get_balance().to_double(), 2)
    finally:
        repo.close()


def _owner_credit_total(gf, *, vendor_id=None, customer_id=None):
    """Sum of open pre-payment credit lots for the owner (0 if none)."""
    from repositories.gnucash_repository import GnuCashRepository
    from use_cases.unpost_business_objects import find_prepayments_in_book
    repo = GnuCashRepository(str(gf))
    repo.open()
    try:
        credits_ = find_prepayments_in_book(
            repo.book, customer_id=customer_id, vendor_id=vendor_id)
        return round(sum(float(c.amount) for c in credits_), 2)
    finally:
        repo.close()


def _export(runner, gf, tmp_path):
    out = tmp_path / 'export.txt'
    r = runner.invoke(cli, ['export', str(gf), str(out),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    return out.read_text()


# ── Bills — overpayment ────────────────────────────────────────────

def test_bill_with_tax_overpayment_credit_is_residual_over_tax_inclusive_total(tmp_path):
    """A bill with tax, total 112, paid 150: lot closes, vendor credit = 38."""
    runner = CliRunner()
    gf = _book(runner, tmp_path, 'overpay_partial_bills_with_tax.txt')
    assert _posted_lot_balance(gf, 'BILL-TAX-OVER-112') == 0.00
    assert _owner_credit_total(gf, vendor_id='V-TAX-BILL') == 38.00
    exported = _export(runner, gf, tmp_path)
    assert 'prepayment: 38.00' in exported, exported


def test_bill_with_no_tax_overpayment_credit_is_residual_over_total(tmp_path):
    """A bill with no tax, total 100, paid 150: lot closes, vendor credit = 50."""
    runner = CliRunner()
    gf = _book(runner, tmp_path, 'overpay_partial_bills_with_no_tax.txt')
    assert _posted_lot_balance(gf, 'BILL-NOTAX-OVER-100') == 0.00
    assert _owner_credit_total(gf, vendor_id='V-NOTAX-BILL') == 50.00
    exported = _export(runner, gf, tmp_path)
    assert 'prepayment: 50.00' in exported, exported


# ── Bills — partial payment ────────────────────────────────────────

def test_bill_with_tax_partial_outstanding_against_tax_inclusive_total(tmp_path):
    """A bill with tax, total 112, paid 60: AP lot open at -52; no credit."""
    runner = CliRunner()
    gf = _book(runner, tmp_path, 'overpay_partial_bills_with_tax.txt')
    assert _posted_lot_balance(gf, 'BILL-TAX-PART-112') == -52.00
    assert _owner_credit_total(gf, vendor_id='V-TAX-BILL') == 38.00  # only the OVER bill's credit


def test_bill_with_no_tax_partial_outstanding_against_total(tmp_path):
    """A bill with no tax, total 100, paid 60: AP lot open at -40."""
    runner = CliRunner()
    gf = _book(runner, tmp_path, 'overpay_partial_bills_with_no_tax.txt')
    assert _posted_lot_balance(gf, 'BILL-NOTAX-PART-100') == -40.00


# ── Invoices — overpayment ─────────────────────────────────────────

def test_invoice_with_tax_overpayment_credit_is_residual_over_tax_inclusive_total(tmp_path):
    """An invoice with tax, total 112, paid 150: lot closes, customer credit = 38."""
    runner = CliRunner()
    gf = _book(runner, tmp_path, 'overpay_partial_invoices_with_tax.txt')
    assert _posted_lot_balance(gf, 'INV-TAX-OVER-112') == 0.00
    assert _owner_credit_total(gf, customer_id='C-TAX-INV') == 38.00
    exported = _export(runner, gf, tmp_path)
    assert 'prepayment: 38.00' in exported, exported


def test_invoice_with_no_tax_overpayment_credit_is_residual_over_total(tmp_path):
    """An invoice with no tax, total 100, paid 150: lot closes, customer credit = 50."""
    runner = CliRunner()
    gf = _book(runner, tmp_path, 'overpay_partial_invoices_with_no_tax.txt')
    assert _posted_lot_balance(gf, 'INV-NOTAX-OVER-100') == 0.00
    assert _owner_credit_total(gf, customer_id='C-NOTAX-INV') == 50.00


# ── Invoices — partial payment ─────────────────────────────────────

def test_invoice_with_tax_partial_outstanding_against_tax_inclusive_total(tmp_path):
    """An invoice with tax, total 112, paid 60: AR lot open at +52 (still owed)."""
    runner = CliRunner()
    gf = _book(runner, tmp_path, 'overpay_partial_invoices_with_tax.txt')
    assert _posted_lot_balance(gf, 'INV-TAX-PART-112') == 52.00


def test_invoice_with_no_tax_partial_outstanding_against_total(tmp_path):
    """An invoice with no tax, total 100, paid 60: AR lot open at +40."""
    runner = CliRunner()
    gf = _book(runner, tmp_path, 'overpay_partial_invoices_with_no_tax.txt')
    assert _posted_lot_balance(gf, 'INV-NOTAX-PART-100') == 40.00
