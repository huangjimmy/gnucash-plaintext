"""A book that holds BOTH a customer invoice AND a vendor bill at once.

GnuCash stores both under one QOF type (`gncInvoice`); every query in this
codebase does `search_for('gncInvoice')` and then classifies each result by
owner type (`wrap_invoice_or_bill`, or an inline `GetOwner().GetCustomer()` /
`GetOwner().GetVendor()` filter). That classification step is exactly where
the Bill-vs-Invoice class bug lived (see CLAUDE.md #8 / T-008): a vendor bill
handled with the wrong SWIG class silently corrupted its tax flags. These
tests exercise every mixed-owner query site with BOTH kinds of record
present in the SAME book, to catch a regression where one type leaks into
the other's result set or gets mutated with the wrong class.

Covered: export (partition + no cross-contamination), print-invoice /
print-bill (each excludes the other kind entirely, including by explicit
selector), delete-invoices / delete-bills (deleting one leaves the other
completely untouched), and re-import / update (both records updated in the
same pass, tax flags surviving on both sides — the sharpest test of the
AddEntry/RemoveEntry class-selection bug in a mixed result set).
"""
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
POSTED_FIXTURE = 'mixed_book_invoice_and_bill_posted_taxed.txt'
UNPOSTED_FIXTURE = 'mixed_book_invoice_and_bill_unposted.txt'


def _fx(name):
    return (FIXTURES / name).read_text()


def _book(runner, tmp_path, fixture_name):
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    fx = tmp_path / fixture_name
    fx.write_text(_fx(fixture_name))
    r = runner.invoke(cli, ['import', str(gnc), str(fx),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'{fixture_name}: {r.output}'
    return gnc


def _entry_tax_included(gnc, business_id, is_bill):
    """Read tax_included straight off the first entry, proving the correct
    SWIG class (Bill vs Invoice) was used for the mutation, not just that
    the flag string round-tripped through plaintext."""
    import gnucash.gnucash_business as gb
    from gnucash import Query

    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gnc))
    repo.open()
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        rec = next((gb.Invoice(instance=r) for r in q.run()
                    if gb.Invoice(instance=r).GetID() == business_id), None)
        q.destroy()
        assert rec is not None, f'{business_id!r} not found'
        entry = list(rec.GetEntries())[0]
        return bool(entry.GetBillTaxIncluded() if is_bill
                    else entry.GetInvTaxIncluded())
    finally:
        repo.close()


# ── Export: partition, no cross-contamination ──────────────────────

def test_export_partitions_invoice_and_bill_with_no_cross_contamination(tmp_path):
    """Exporting a book with one invoice and one bill puts each ID in its
    own block, with the invoice's fields never appearing in the bill block
    (and vice versa)."""
    runner = CliRunner()
    gnc = _book(runner, tmp_path, POSTED_FIXTURE)
    out = tmp_path / 'export.txt'
    r = runner.invoke(cli, ['export', str(gnc), str(out),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    text = out.read_text()

    assert 'invoice "INV-MIX-1"' in text
    assert 'bill "BILL-MIX-1"' in text

    inv_start = text.index('invoice "INV-MIX-1"')
    bill_start = text.index('bill "BILL-MIX-1"')
    inv_block = text[inv_start:bill_start] if inv_start < bill_start else \
        text[inv_start:inv_start + text[inv_start:].index('\n\n')]
    bill_block = text[bill_start:bill_start + text[bill_start:].index('\n\n')] \
        if bill_start > inv_start else text[bill_start:inv_start]

    assert 'ar_account' in inv_block and 'ap_account' not in inv_block, (
        f'invoice block must not carry AP fields:\n{inv_block}')
    assert 'ap_account' in bill_block and 'ar_account' not in bill_block, (
        f'bill block must not carry AR fields:\n{bill_block}')
    assert 'BILL-MIX-1' not in inv_block, 'bill id leaked into invoice block'
    assert 'INV-MIX-1' not in bill_block, 'invoice id leaked into bill block'


# ── print-invoice / print-bill: strict exclusion ───────────────────

def test_print_invoice_excludes_the_bill_in_the_same_book(tmp_path):
    """`print-invoice` on a mixed book renders only the invoice; the bill's
    id/description never appears, and selecting the bill's id by
    --invoice-id finds nothing (a bill is not a selectable invoice)."""
    runner = CliRunner()
    gnc = _book(runner, tmp_path, POSTED_FIXTURE)

    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gnc),
                            '--invoice-id', 'INV-MIX-1',
                            '--format', 'plaintext', '-o', str(out)])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert 'INV-MIX-1' in text
    assert 'BILL-MIX-1' not in text
    assert 'Mixed-book bill' not in text

    r = runner.invoke(cli, ['print-invoice', str(gnc),
                            '--invoice-id', 'BILL-MIX-1',
                            '--format', 'plaintext',
                            '-o', str(tmp_path / 'nope.txt')])
    assert r.exit_code != 0, (
        'a bill id must not be selectable via print-invoice --invoice-id')


def test_print_bill_excludes_the_invoice_in_the_same_book(tmp_path):
    """Mirror: `print-bill` on a mixed book renders only the bill; the
    invoice never appears, and selecting the invoice's id by --bill-id
    finds nothing."""
    runner = CliRunner()
    gnc = _book(runner, tmp_path, POSTED_FIXTURE)

    out = tmp_path / 'bill.txt'
    r = runner.invoke(cli, ['print-bill', str(gnc),
                            '--bill-id', 'BILL-MIX-1',
                            '--format', 'plaintext', '-o', str(out)])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert 'BILL-MIX-1' in text
    assert 'INV-MIX-1' not in text
    assert 'Mixed-book invoice' not in text

    r = runner.invoke(cli, ['print-bill', str(gnc),
                            '--bill-id', 'INV-MIX-1',
                            '--format', 'plaintext',
                            '-o', str(tmp_path / 'nope.txt')])
    assert r.exit_code != 0, (
        'an invoice id must not be selectable via print-bill --bill-id')


def test_print_invoice_glob_selection_in_mixed_book_never_matches_the_bill(tmp_path):
    """A glob broad enough to match both ids by naive substring (`*MIX*`)
    must still select only the invoice under print-invoice — proving the
    owner-type filter, not just the id string, decides membership."""
    runner = CliRunner()
    gnc = _book(runner, tmp_path, POSTED_FIXTURE)
    out = tmp_path / 'globbed.txt'
    r = runner.invoke(cli, ['print-invoice', str(gnc), '*MIX*',
                            '--format', 'plaintext', '-o', str(out)])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert 'invoice "INV-MIX-1"' in text
    assert 'BILL-MIX-1' not in text


# ── delete-invoices / delete-bills: strict isolation ───────────────

def test_delete_invoice_in_mixed_book_leaves_bill_completely_untouched(tmp_path):
    """Deleting INV-MIX-2 removes only the invoice; BILL-MIX-2 (unposted,
    same book) still imports/exports afterward exactly as before."""
    runner = CliRunner()
    gnc = _book(runner, tmp_path, UNPOSTED_FIXTURE)

    r = runner.invoke(cli, ['delete-invoices', str(gnc), 'INV-MIX-2'])
    assert r.exit_code == 0, r.output

    out = tmp_path / 'after.txt'
    r = runner.invoke(cli, ['export', str(gnc), str(out),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert 'invoice "INV-MIX-2"' not in text, 'invoice must be gone'
    assert 'bill "BILL-MIX-2"' in text, 'bill must survive the invoice delete'
    assert 'posted: none' in text.split('bill "BILL-MIX-2"', 1)[1], (
        'the surviving bill must still be unposted/unaffected')


def test_delete_bill_in_mixed_book_leaves_invoice_completely_untouched(tmp_path):
    """Mirror: deleting BILL-MIX-2 removes only the bill; INV-MIX-2 survives
    unaffected. This is the isolation check closest to the AddEntry /
    RemoveEntry class bug — a wrong-class RemoveEntry on the bill would
    risk corrupting shared state."""
    runner = CliRunner()
    gnc = _book(runner, tmp_path, UNPOSTED_FIXTURE)

    r = runner.invoke(cli, ['delete-bills', str(gnc), 'BILL-MIX-2'])
    assert r.exit_code == 0, r.output

    out = tmp_path / 'after.txt'
    r = runner.invoke(cli, ['export', str(gnc), str(out),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert 'bill "BILL-MIX-2"' not in text, 'bill must be gone'
    assert 'invoice "INV-MIX-2"' in text, 'invoice must survive the bill delete'
    assert 'posted: none' in text.split('invoice "INV-MIX-2"', 1)[1], (
        'the surviving invoice must still be unposted/unaffected')


# ── Re-import (update path): both records touched in one pass ─────

def test_reimport_update_path_preserves_tax_flags_on_both_sides_at_once(tmp_path):
    """Re-importing the same mixed posted fixture triggers the UPDATE path
    (existing invoice found, existing bill found) for both records in one
    import call. Both entries' tax_included must still read back correctly
    afterward — the sharpest proof that AddEntry/RemoveEntry dispatch is
    correct per-record even when the query result set contains both kinds
    together."""
    runner = CliRunner()
    gnc = _book(runner, tmp_path, POSTED_FIXTURE)

    assert _entry_tax_included(gnc, 'INV-MIX-1', is_bill=False) is False
    assert _entry_tax_included(gnc, 'BILL-MIX-1', is_bill=True) is False

    # Re-import the identical fixture: both records already exist and are
    # posted, so the importer takes the unpost/rebuild/repost path for each
    # — exercising RemoveEntry + AddEntry on both an Invoice and a Bill in
    # the same pass, against a book where both kinds are present together.
    fx = tmp_path / 'reimport.txt'
    fx.write_text(_fx(POSTED_FIXTURE))
    r = runner.invoke(cli, ['import', str(gnc), str(fx),
                            '--include-business-objects'])
    assert r.exit_code == 0, f're-import: {r.output}'

    assert _entry_tax_included(gnc, 'INV-MIX-1', is_bill=False) is False
    assert _entry_tax_included(gnc, 'BILL-MIX-1', is_bill=True) is False

    # And the entries are still tax-correct end to end (net 1000 + 120 tax).
    out = tmp_path / 'after.txt'
    r = runner.invoke(cli, ['export', str(gnc), str(out),
                            '--include-business-objects'])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert text.count('invoice "INV-MIX-1"') == 1, 'no duplicate invoice'
    assert text.count('bill "BILL-MIX-1"') == 1, 'no duplicate bill'
