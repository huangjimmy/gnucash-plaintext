"""Q-019: drafts (cash-basis OR plain accrual) render full tax info.

GnuCash only materialises tax splits at posting time; before then, the
posted-path tax extraction returns nothing. Q-019 has the renderers
compute tax from each entry's tax_table via compute_entry_informational
so unposted invoices and bills carry the same tax detail as posted
ones — marked as provisional in HTML / plaintext so the viewer knows
the figures may change at post time.
"""
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')


def _fx(name):
    return (FIXTURES / name).read_text()


def _import_into_fresh_book(runner, tmp_path, fixture_name):
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    time.sleep(1)
    fx_path = tmp_path / fixture_name
    fx_path.write_text(_fx(fixture_name))
    r = runner.invoke(cli, ['import', str(gnc), str(fx_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'{fixture_name}: {r.output}'
    time.sleep(1)
    return gnc


def _render_invoice_html(gnc, invoice_id):
    from gnucash import Query
    from gnucash.gnucash_business import Invoice as BizInvoice

    from repositories.gnucash_repository import GnuCashRepository
    from services.invoice_renderer import render_to_html

    repo = GnuCashRepository(str(gnc))
    repo.open()
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        inv = next(
            (i for r in q.run() for i in [BizInvoice(instance=r)]
             if i.GetID() == invoice_id),
            None,
        )
        q.destroy()
        assert inv is not None, f'invoice {invoice_id!r} not found'
        xslt = Path(__file__).resolve().parents[2] / 'services' / 'invoice.xslt'
        return render_to_html(inv, repo.book, str(xslt))
    finally:
        repo.close()


def _render_invoice_plaintext(gnc, invoice_id):
    from gnucash import Query
    from gnucash.gnucash_business import Invoice as BizInvoice

    from repositories.gnucash_repository import GnuCashRepository
    from services.invoice_renderer import render_to_plaintext

    repo = GnuCashRepository(str(gnc))
    repo.open()
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        inv = next(
            (i for r in q.run() for i in [BizInvoice(instance=r)]
             if i.GetID() == invoice_id),
            None,
        )
        q.destroy()
        assert inv is not None, f'invoice {invoice_id!r} not found'
        return render_to_plaintext(inv, repo.book)
    finally:
        repo.close()


# ── HTML / PDF render path ─────────────────────────────────────────

def test_cash_basis_unposted_invoice_html_renders_combined_tax(tmp_path):
    """Cash-basis unposted invoice with GST 5% + PST 7%: the HTML must
    show one <tax-line> row per tax-table account (per-account
    aggregation), the correct grand total (200 + 24 = 224), AND a
    provisional-tax notice so the viewer knows the figures will be
    recomputed at post time."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'q019_unposted_cash_with_tax.txt',
    )
    html = _render_invoice_html(gnc, 'INV-Q19-CASH-TAX-200')

    # Cash-basis → UNPAID badge (not DRAFT).
    assert '<span class="badge badge-unpaid">Unpaid</span>' in html
    assert '<span class="badge badge-draft">Draft</span>' not in html

    # Both per-tax-account rows are present.
    assert '>GST<' in html, (
        f'expected GST tax-line row; HTML:\n{html[:2500]}'
    )
    assert '>PST<' in html, (
        f'expected PST tax-line row; HTML:\n{html[:2500]}'
    )

    # Tax dollars: GST = 200 * 0.05 = 10.00; PST = 200 * 0.07 = 14.00.
    assert '$10.00' in html, 'expected GST = $10.00 row'
    assert '$14.00' in html, 'expected PST = $14.00 row'

    # Grand total includes tax (200 + 24 = 224.00).
    assert 'CAD\xa0224.00' in html or 'CAD&#160;224.00' in html or 'CAD 224.00' in html, (
        f'expected grand total CAD 224.00; got:\n{html[-2000:]}'
    )

    # Provisional-tax notice must appear.
    assert 'provisional' in html.lower(), (
        f'expected provisional-tax notice; HTML:\n{html[-2000:]}'
    )


def test_plain_accrual_draft_invoice_html_renders_single_tax(tmp_path):
    """Plain accrual draft (no cash_basis flag) with a single 10% Sales
    Tax: badge stays DRAFT, but tax detail is now rendered just like the
    cash-basis case. Single tax-table entry → single tax-line row +
    `single` tax-label CSS class."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'q019_unposted_draft_with_tax.txt',
    )
    html = _render_invoice_html(gnc, 'INV-Q19-DRAFT-TAX-300')

    # Plain draft → DRAFT badge.
    assert '<span class="badge badge-draft">Draft</span>' in html
    assert '<span class="badge badge-unpaid">Unpaid</span>' not in html

    # Single tax-table → one tax-line row, `single` label class.
    assert 'tax-single' in html, (
        f'expected single-rate tax-label class; HTML:\n{html[:2500]}'
    )

    # Tax = 300 * 0.10 = 30.00; grand total = 330.00.
    assert '$30.00' in html, 'expected tax-line row amount $30.00'
    assert 'CAD\xa0330.00' in html or 'CAD&#160;330.00' in html or 'CAD 330.00' in html, (
        f'expected grand total CAD 330.00; got:\n{html[-2000:]}'
    )

    assert 'provisional' in html.lower(), (
        f'expected provisional-tax notice on draft; HTML:\n{html[-2000:]}'
    )


# ── Plaintext render path ─────────────────────────────────────────

def test_cash_basis_unposted_invoice_plaintext_emits_breakdown(tmp_path):
    """Plaintext render must include entry_amount, entry_tax, per-tax
    breakdown blocks, invoice_subtotal, invoice_tax_total,
    invoice_total, AND a `#` comment caveat. The comment line ensures
    the recipient sees that tax values are provisional."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'q019_unposted_cash_with_tax.txt',
    )
    text = _render_invoice_plaintext(gnc, 'INV-Q19-CASH-TAX-200')

    assert '# Tax figures are provisional' in text, (
        f'expected provisional-tax `#` caveat; got:\n{text}'
    )
    # Entry-level informational fields.
    assert 'entry_amount: 200.00' in text, f'got:\n{text}'
    assert 'entry_tax: 24.00' in text, f'got:\n{text}'

    # One breakdown block per tax-table entry.
    assert 'account: "Liabilities:Tax:GST"' in text
    assert 'account: "Liabilities:Tax:PST"' in text
    # Combined amounts (per breakdown row).
    assert 'amount: 10.00' in text, f'expected GST 10.00 breakdown; got:\n{text}'
    assert 'amount: 14.00' in text, f'expected PST 14.00 breakdown; got:\n{text}'

    # Invoice-level totals.
    assert 'invoice_subtotal: 200.00' in text
    assert 'invoice_tax_total: 24.00' in text
    assert 'invoice_total: 224.00' in text


def test_plain_draft_invoice_plaintext_emits_breakdown(tmp_path):
    """Same coverage as the cash-basis case but for a plain accrual
    draft — confirms the gates aren't accidentally still cash_basis-only."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'q019_unposted_draft_with_tax.txt',
    )
    text = _render_invoice_plaintext(gnc, 'INV-Q19-DRAFT-TAX-300')

    assert '# Tax figures are provisional' in text
    assert 'entry_amount: 300.00' in text, f'got:\n{text}'
    assert 'entry_tax: 30.00' in text, f'got:\n{text}'
    assert 'account: "Liabilities:Tax:Sales Tax"' in text
    assert 'amount: 30.00' in text
    assert 'invoice_subtotal: 300.00' in text
    assert 'invoice_tax_total: 30.00' in text
    assert 'invoice_total: 330.00' in text


def test_rendered_plaintext_reimports_without_parser_error(tmp_path):
    """The `# ...` provisional caveat is a new line shape; the parser
    must skip it so rendered output re-imports cleanly. Renders a draft
    invoice to plaintext, then `import --new` into a fresh book."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'q019_unposted_cash_with_tax.txt',
    )
    text = _render_invoice_plaintext(gnc, 'INV-Q19-CASH-TAX-200')

    # The caveat must actually be there for this test to mean anything.
    assert '# Tax figures are provisional' in text

    rendered_path = tmp_path / 'rendered.txt'
    rendered_path.write_text(text)

    fresh_gnc = tmp_path / 'fresh.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(fresh_gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    time.sleep(1)
    r = runner.invoke(cli, ['import', str(fresh_gnc), str(rendered_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, (
        f'rendered draft plaintext must re-import cleanly '
        f'(the `#` caveat must be skipped by the parser); got:\n{r.output}'
    )
