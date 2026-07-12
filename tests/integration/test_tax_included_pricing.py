"""`tax_included: true` (tax-INCLUSIVE pricing) coverage — invoices & bills.

When an entry declares `tax_included: true`, the entered price already
contains the tax; the renderers and the importer back the net amount out
with `net = gross / (1 + total_rate)`. This is the one tax branch that had
no fixture/test. With a GST 5% + PST 7% table (12% total) and a gross of
1120:

    net (subtotal) = 1120 / 1.12 = 1000.00
    GST 5% of 1000 =                 50.00
    PST 7% of 1000 =                 70.00
    tax total      =                120.00
    grand total    =               1120.00   (unchanged — tax was inside)

Contrast (locks in the back-out): the SAME entered 1120 with
`tax_included: false` would be subtotal 1120, GST 56, PST 78.40, total
1254.40. So the exact 1000/50/70/1120 assertions below catch a regression
in the gross → net back-out.

The draft-render tests exercise `compute_entry_informational` /
`compute_bill_entry_informational` (the pre-posting back-out). The
posted-split tests exercise GnuCash's own posting-time back-out (the entry
flag reaching the engine), then prove `tax_included: true` survives an
export → fresh-book re-import unchanged.
"""
from pathlib import Path

import gnucash.gnucash_business as gb
from click.testing import CliRunner
from gnucash import Query

from cli.main import cli
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')


def _fx(name):
    return (FIXTURES / name).read_text()


def _import_into_fresh_book(runner, tmp_path, fixture_name):
    """Fresh book → accounts → the given tax_included fixture (business
    objects). Drives the real import pipeline; no GnuCash-type mocking."""
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    fx_path = tmp_path / fixture_name
    fx_path.write_text(_fx(fixture_name))
    r = runner.invoke(cli, ['import', str(gnc), str(fx_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'{fixture_name}: {r.output}'
    return gnc


def _find_business_object(repo, business_id):
    """Look up an invoice OR bill by id (both are gncInvoice QOF objects)."""
    q = Query()
    try:
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        return next(
            (i for raw in q.run() for i in [gb.Invoice(instance=raw)]
             if i.GetID() == business_id),
            None,
        )
    finally:
        q.destroy()


def _posting_tx_splits(gnc_path, business_id):
    """Return {account_full_name: rounded signed amount} for the posting
    transaction of the given invoice/bill id — the real materialised
    posting splits, so the tax back-out done by GnuCash at post time is
    observed, not assumed."""
    repo = GnuCashRepository(str(gnc_path))
    repo.open()
    try:
        inv = _find_business_object(repo, business_id)
        assert inv is not None, f'{business_id!r} not found in book'
        tx = inv.GetPostedTxn()
        assert tx is not None, f'{business_id!r} is not posted'
        splits = {}
        for i in range(tx.CountSplits()):
            sp = tx.GetSplit(i)
            name = get_account_full_name(sp.GetAccount())
            splits[name] = round(
                splits.get(name, 0.0) + sp.GetAmount().to_double(), 2)
        return splits
    finally:
        repo.close()


def _first_entry_tax_included(gnc_path, business_id, is_bill):
    """Read the tax_included flag straight off the first entry of the
    re-imported invoice/bill — proves the flag round-tripped into the
    engine, not just into the exported text."""
    repo = GnuCashRepository(str(gnc_path))
    repo.open()
    try:
        inv = _find_business_object(repo, business_id)
        assert inv is not None, f'{business_id!r} not found in book'
        entry = list(inv.GetEntries())[0]
        return bool(
            entry.GetBillTaxIncluded() if is_bill
            else entry.GetInvTaxIncluded())
    finally:
        repo.close()


# ── Draft render: invoice ──────────────────────────────────────────

def test_tax_included_invoice_draft_plaintext_backs_out_net_and_tax(tmp_path):
    """Unposted invoice, gross 1120, tax_included: true. `print-invoice
    --format plaintext` must back the net out to 1000: entry_amount
    1000.00, entry_tax 120.00, GST 50.00 / PST 70.00 breakdown, and
    invoice_subtotal/tax_total/total = 1000/120/1120."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(runner, tmp_path, 'tax_included_invoice.txt')
    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gnc), 'INV-TAXINCL-1120',
                            '--format', 'plaintext', '-o', str(out)])
    assert r.exit_code == 0, f'print-invoice: {r.output}'
    text = out.read_text()

    assert 'tax_included: true' in text, f'flag not rendered:\n{text}'
    assert 'entry_amount: 1000.00' in text, f'net back-out wrong:\n{text}'
    assert 'entry_tax: 120.00' in text, f'tax wrong:\n{text}'
    assert 'account: "Liabilities:Tax:GST"' in text
    assert 'account: "Liabilities:Tax:PST"' in text
    assert 'amount: 50.00' in text, f'GST 5% of 1000 = 50.00:\n{text}'
    assert 'amount: 70.00' in text, f'PST 7% of 1000 = 70.00:\n{text}'
    assert 'invoice_subtotal: 1000.00' in text
    assert 'invoice_tax_total: 120.00' in text
    assert 'invoice_total: 1120.00' in text
    # Anti-regression: a lost back-out would make subtotal the gross 1120.
    assert 'invoice_subtotal: 1120.00' not in text
    # Unposted → provisional caveat.
    assert '# Tax figures are provisional' in text


def test_tax_included_invoice_draft_html_backs_out_net_and_tax(tmp_path):
    """Same invoice rendered to HTML: GST/PST rows show $50.00/$70.00,
    Subtotal is the net CAD 1,000.00, grand total the unchanged gross
    CAD 1,120.00, plus the provisional notice."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(runner, tmp_path, 'tax_included_invoice.txt')
    out = tmp_path / 'inv.html'
    r = runner.invoke(cli, ['print-invoice', str(gnc), 'INV-TAXINCL-1120',
                            '--format', 'html', '-o', str(out)])
    assert r.exit_code == 0, f'print-invoice: {r.output}'
    html = out.read_text()

    assert '>GST<' in html and '>PST<' in html
    assert '$50.00' in html, f'GST tax line $50.00 missing:\n{html}'
    assert '$70.00' in html, f'PST tax line $70.00 missing:\n{html}'
    assert ('CAD\xa01,000.00' in html or 'CAD&#160;1,000.00' in html
            or 'CAD 1,000.00' in html), f'net subtotal missing:\n{html[-2500:]}'
    assert ('CAD\xa01,120.00' in html or 'CAD&#160;1,120.00' in html
            or 'CAD 1,120.00' in html), f'grand total missing:\n{html[-2500:]}'
    assert 'provisional' in html.lower()


# ── Draft render: bill ─────────────────────────────────────────────

def test_tax_included_bill_draft_plaintext_backs_out_net_and_tax(tmp_path):
    """Unposted bill, gross 1120, tax_included: true. `print-bill
    --format plaintext` must back the net out identically to the invoice
    side: entry_amount 1000.00, entry_tax 120.00, GST 50 / PST 70, and
    bill_subtotal/tax_total/total = 1000/120/1120."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(runner, tmp_path, 'tax_included_bill.txt')
    out = tmp_path / 'bill.txt'
    r = runner.invoke(cli, ['print-bill', str(gnc), 'BILL-TAXINCL-1120',
                            '--format', 'plaintext', '-o', str(out)])
    assert r.exit_code == 0, f'print-bill: {r.output}'
    text = out.read_text()

    assert 'tax_included: true' in text, f'flag not rendered:\n{text}'
    assert 'entry_amount: 1000.00' in text, f'net back-out wrong:\n{text}'
    assert 'entry_tax: 120.00' in text, f'tax wrong:\n{text}'
    assert 'account: "Liabilities:Tax:GST"' in text
    assert 'account: "Liabilities:Tax:PST"' in text
    assert 'amount: 50.00' in text, f'GST 5% of 1000 = 50.00:\n{text}'
    assert 'amount: 70.00' in text, f'PST 7% of 1000 = 70.00:\n{text}'
    assert 'bill_subtotal: 1000.00' in text
    assert 'bill_tax_total: 120.00' in text
    assert 'bill_total: 1120.00' in text
    assert 'bill_subtotal: 1120.00' not in text
    assert '# Tax figures are provisional' in text


def test_tax_included_bill_draft_html_backs_out_net_and_tax(tmp_path):
    """Same bill rendered to HTML: GST/PST rows $50.00/$70.00, net
    Subtotal CAD 1,000.00, grand total the unchanged gross CAD 1,120.00,
    provisional notice."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(runner, tmp_path, 'tax_included_bill.txt')
    out = tmp_path / 'bill.html'
    r = runner.invoke(cli, ['print-bill', str(gnc), 'BILL-TAXINCL-1120',
                            '--format', 'html', '-o', str(out)])
    assert r.exit_code == 0, f'print-bill: {r.output}'
    html = out.read_text()

    assert '>GST<' in html and '>PST<' in html
    assert '$50.00' in html, f'GST tax line $50.00 missing:\n{html}'
    assert '$70.00' in html, f'PST tax line $70.00 missing:\n{html}'
    assert ('CAD\xa01,000.00' in html or 'CAD&#160;1,000.00' in html
            or 'CAD 1,000.00' in html), f'net subtotal missing:\n{html[-2500:]}'
    assert ('CAD\xa01,120.00' in html or 'CAD&#160;1,120.00' in html
            or 'CAD 1,120.00' in html), f'grand total missing:\n{html[-2500:]}'
    assert 'provisional' in html.lower()


# ── Posted round-trip: invoice ─────────────────────────────────────

def test_tax_included_invoice_posted_splits_back_out_tax(tmp_path):
    """Posted invoice (4 × 280 gross = 1120, tax_included: true). GnuCash
    materialises the posting splits with the tax backed out: AR +1120,
    Income −1000, GST −50, PST −70 (balanced)."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'tax_included_invoice_posted.txt')
    splits = _posting_tx_splits(gnc, 'INV-TAXINCL-POSTED-1120')

    assert splits.get('Assets:Accounts Receivable') == 1120.00, splits
    assert splits.get('Income:Sales') == -1000.00, splits
    assert splits.get('Liabilities:Tax:GST') == -50.00, splits
    assert splits.get('Liabilities:Tax:PST') == -70.00, splits
    assert round(sum(splits.values()), 2) == 0.00, splits


def test_tax_included_invoice_survives_export_reimport(tmp_path):
    """Posted tax_included invoice → export → fresh-book re-import. The
    exporter emits `tax_included: true` and the backed-out informational
    totals; the importer's recompute/tamper-check passes; the flag and
    the 1000/50/70/1120 posting semantics are identical in the dest
    book."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'tax_included_invoice_posted.txt')

    exported = tmp_path / 'exported.txt'
    r = runner.invoke(cli, ['export', str(gnc), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'export: {r.output}'
    exported_text = exported.read_text()
    # The canonical business-object export carries the source-of-truth
    # fields (incl. `tax_included: true`) rather than the print-only
    # informational totals; preservation of the 1000/50/70/1120 semantics
    # is proven below via the re-imported posting splits.
    assert 'tax_included: true' in exported_text, exported_text
    assert 'price: 280' in exported_text and 'quantity: 4' in exported_text, (
        exported_text)

    dst = tmp_path / 'dst.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(dst), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, f're-import (recompute/tamper-check): {r.output}'

    assert _first_entry_tax_included(
        dst, 'INV-TAXINCL-POSTED-1120', is_bill=False) is True
    splits = _posting_tx_splits(dst, 'INV-TAXINCL-POSTED-1120')
    assert splits.get('Assets:Accounts Receivable') == 1120.00, splits
    assert splits.get('Income:Sales') == -1000.00, splits
    assert splits.get('Liabilities:Tax:GST') == -50.00, splits
    assert splits.get('Liabilities:Tax:PST') == -70.00, splits


# ── Posted round-trip: bill ────────────────────────────────────────

def test_tax_included_bill_posted_splits_back_out_tax(tmp_path):
    """Posted bill (4 × 280 gross = 1120, tax_included: true). GnuCash
    materialises the AP posting splits with the tax backed out and the
    OPPOSITE sign to an invoice: AP −1120, Expense +1000, GST +50,
    PST +70 (balanced)."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'tax_included_bill_posted.txt')
    splits = _posting_tx_splits(gnc, 'BILL-TAXINCL-POSTED-1120')

    assert splits.get('Liabilities:Accounts Payable') == -1120.00, splits
    assert splits.get('Expenses:Office Supplies') == 1000.00, splits
    assert splits.get('Liabilities:Tax:GST') == 50.00, splits
    assert splits.get('Liabilities:Tax:PST') == 70.00, splits
    assert round(sum(splits.values()), 2) == 0.00, splits


def test_tax_included_bill_survives_export_reimport(tmp_path):
    """Posted tax_included bill → export → fresh-book re-import. The
    exporter emits `tax_included: true` and the backed-out bill_*
    informational totals; the flag and the AP posting semantics
    (−1120 / +1000 / +50 / +70) are identical in the dest book."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'tax_included_bill_posted.txt')

    exported = tmp_path / 'exported.txt'
    r = runner.invoke(cli, ['export', str(gnc), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'export: {r.output}'
    exported_text = exported.read_text()
    # Export carries `tax_included: true` (source-of-truth); the
    # 1000/50/70/1120 AP semantics are proven below via the re-imported
    # posting splits.
    assert 'tax_included: true' in exported_text, exported_text
    assert 'price: 280' in exported_text and 'quantity: 4' in exported_text, (
        exported_text)

    dst = tmp_path / 'dst.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(dst), str(exported),
                            '--include-business-objects'])
    assert r.exit_code == 0, f're-import: {r.output}'

    assert _first_entry_tax_included(
        dst, 'BILL-TAXINCL-POSTED-1120', is_bill=True) is True
    splits = _posting_tx_splits(dst, 'BILL-TAXINCL-POSTED-1120')
    assert splits.get('Liabilities:Accounts Payable') == -1120.00, splits
    assert splits.get('Expenses:Office Supplies') == 1000.00, splits
    assert splits.get('Liabilities:Tax:GST') == 50.00, splits
    assert splits.get('Liabilities:Tax:PST') == 70.00, splits
