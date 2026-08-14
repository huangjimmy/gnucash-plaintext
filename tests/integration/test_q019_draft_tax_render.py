"""Q-019: drafts (cash-basis OR plain accrual) carry full tax info.

GnuCash only materialises tax splits at posting time. Its own page prices an
unposted document from the entries' tax tables and states the tax as one
total, so the HTML needs nothing from this project; the plaintext render does
its own arithmetic through `compute_entry_informational` and marks the figures
provisional, because a plaintext document is re-imported and its numbers are
checked against a recomputation.
"""
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import wrap_invoice_or_bill
from tests.integration.rendered_page import is_in_progress

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')


def _fx(name):
    return (FIXTURES / name).read_text()


def _import_into_fresh_book(runner, tmp_path, fixture_name):
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    fx_path = tmp_path / fixture_name
    fx_path.write_text(_fx(fixture_name))
    r = runner.invoke(cli, ['import', str(gnc), str(fx_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'{fixture_name}: {r.output}'
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
            (i for r in q.run() for i in [wrap_invoice_or_bill(r)]
             if i.GetID() == invoice_id),
            None,
        )
        q.destroy()
        assert inv is not None, f'invoice {invoice_id!r} not found'
        return render_to_html(inv, repo.session)
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
            (i for r in q.run() for i in [wrap_invoice_or_bill(r)]
             if i.GetID() == invoice_id),
            None,
        )
        q.destroy()
        assert inv is not None, f'invoice {invoice_id!r} not found'
        return render_to_plaintext(inv, repo.book)
    finally:
        repo.close()


# ── HTML / PDF render path ─────────────────────────────────────────

def test_cash_basis_unposted_invoice_html_prices_its_tax(tmp_path):
    """Cash-basis unposted invoice with GST 5% + PST 7%: GnuCash prices it
    from the entries' tax table — 200.00 net, 10.00 GST, 14.00 PST, 224.00
    owed — and marks it in progress, which is what says the figures are not
    posted yet.

    One row per tax account, each named: a filer reclaims the GST and not the
    PST, and a document stating only their sum does not tell them which is
    which. GnuCash's report writes them that way when asked
    (`Display/Use Detailed Tax Summary`), and it is asked.
    """
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'q019_unposted_cash_with_tax.txt',
    )
    html = _render_invoice_html(gnc, 'INV-Q19-CASH-TAX-200')

    assert is_in_progress(html), html
    assert '>C$200.00<' in html, f'net; HTML:\n{html[-2500:]}'
    assert '>GST</td>' in html, f'GST named; HTML:\n{html[-2500:]}'
    assert '>C$10.00<' in html, f'5% of 200.00; HTML:\n{html[-2500:]}'
    assert '>PST</td>' in html, f'PST named; HTML:\n{html[-2500:]}'
    assert '>C$14.00<' in html, f'7% of 200.00; HTML:\n{html[-2500:]}'
    assert '>C$224.00<' in html, f'owed; HTML:\n{html[-2500:]}'


def test_plain_accrual_draft_invoice_html_prices_its_tax(tmp_path):
    """The same for a plain accrual draft carrying no `cash_basis:` key, on a
    single 10% table: 300.00 net, 30.00 tax, 330.00 owed."""
    runner = CliRunner()
    gnc = _import_into_fresh_book(
        runner, tmp_path, 'q019_unposted_draft_with_tax.txt',
    )
    html = _render_invoice_html(gnc, 'INV-Q19-DRAFT-TAX-300')

    assert is_in_progress(html), html
    assert '>C$300.00<' in html, f'net; HTML:\n{html[-2500:]}'
    assert '>C$30.00<' in html, f'10% of 300.00; HTML:\n{html[-2500:]}'
    assert '>C$330.00<' in html, f'owed; HTML:\n{html[-2500:]}'


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
    r = runner.invoke(cli, ['import', str(fresh_gnc), str(rendered_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, (
        f'rendered draft plaintext must re-import cleanly '
        f'(the `#` caveat must be skipped by the parser); got:\n{r.output}'
    )
