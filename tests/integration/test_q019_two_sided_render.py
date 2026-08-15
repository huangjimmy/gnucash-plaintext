"""Q-019: invoice / bill rendering shows BOTH sides.

Both documents are drawn by GnuCash's own Printable Invoice report, which puts
the document's owner on one side and the seller — us, from the book's Business
→ Company options — on the other. A bill is a vendor's invoice, so the owner
there is the vendor; one report draws both and neither side is invented here.

Drives the full CLI pipeline — populates real Business → Company book options
via the GnuCash KvpFrame API, then runs `print-invoice` / `print-bill`, which
calls `read_book_company_info` itself. No `company_info=` injection (that would
skip the wiring between the reader and the renderer, where bugs hide).
"""
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.integration.rendered_page import is_in_progress, readable

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')

# Our company info — written into the GnuCash book's Business→Company
# options frame for every test in this module.
COMPANY = {
    'Company Name':          'Acme Plaintext Co.',
    'Company ID':            '123456789RT0001',
    'Company Phone Number':  '+1-555-0142',
    'Company Email Address': 'billing@acmeplain.test',
    'Company Website URL':   'https://acmeplain.test',
    'Company Address':       '100 Main St\nSuite 200\nToronto ON M5H 1A1',
}


def _fx(name):
    return (FIXTURES / name).read_text()


def _populate_company_options(gnc_path):
    """Set Acme's Business → Company options on the book via the proper
    GnuCash API (`set_book_string_option`, which wraps
    `qof_instance_set_kvp` with a 3-element nested path). This goes
    through GnuCash's dirty-tracking + session-save machinery, the
    same path File→Properties→Business uses in the GUI, so the test
    setup is faithful to how production users populate these slots.

    The renderer's `read_book_company_info` then reads the resulting
    XML directly — no production code is bypassed."""
    from infrastructure.gnucash.kvp import set_book_string_option
    from repositories.gnucash_repository import GnuCashRepository
    repo = GnuCashRepository(str(gnc_path))
    repo.open()
    try:
        for slot_key, slot_val in COMPANY.items():
            assert set_book_string_option(
                repo.book, 'Business', slot_key, slot_val,
            ), f'set_book_string_option failed for Business/{slot_key}'
        repo.save()
    finally:
        repo.close()

    # Self-check: read back via the production reader. If the renderer
    # can't see the options we just wrote, the test setup is broken
    # before any production rendering code runs — fail loudly here so
    # the failure isn't blamed on the renderer downstream.
    from services.invoice_renderer import read_book_company_info
    info = read_book_company_info(str(gnc_path))
    assert info.get('name') == COMPANY['Company Name'], (
        f'read_book_company_info did not see the populated options; '
        f'got: {info!r}'
    )


def _book_with_company(runner, tmp_path, fixture_name):
    """Common setup: fresh book → accounts → fixture → company options.
    Options are injected last so no subsequent GnuCash session-save
    re-serializes the book (which would canonicalise XML namespace
    prefixes and might reorder slots). `print-invoice` / `print-bill`
    only open the book READ_ONLY, so the XML-injected slots survive."""
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    fx_path = tmp_path / fixture_name
    fx_path.write_text(_fx(fixture_name))
    r = runner.invoke(cli, ['import', str(gnc), str(fx_path),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'{fixture_name}: {r.output}'
    _populate_company_options(gnc)
    return gnc


# ── Invoice two-sided rendering ────────────────────────────────────

def test_invoice_html_renders_both_customer_and_company(tmp_path):
    """`print-invoice --format html` shows the customer on one side and us on
    the other, with every populated book option on the page."""
    runner = CliRunner()
    gnc = _book_with_company(
        runner, tmp_path, 'q019_unposted_cash_with_tax.txt',
    )
    out_html = tmp_path / 'invoice.html'
    r = runner.invoke(cli, [
        'print-invoice', str(gnc), 'INV-Q19-CASH-TAX-200',
        '--format', 'html', '-o', str(out_html),
    ])
    assert r.exit_code == 0, f'print-invoice: {r.output}'

    html = readable(out_html.read_text())

    # Customer side: the document's owner, in the report's client block.
    assert 'client-name">Beta Industries<' in html, (
        f'customer name must head the client block; HTML:\n{html}'
    )

    # Seller side: the company block, from the book's options.
    assert f'company-name">{COMPANY["Company Name"]}<' in html, (
        f'company name must head the company block; HTML:\n{html}'
    )
    assert COMPANY['Company ID'] in html, (
        f'Company ID (tax registration) value must appear; HTML:\n{html}'
    )
    # Address line 1 of the multi-line company address.
    assert '100 Main St' in html, (
        f'company address must appear; HTML:\n{html}'
    )
    assert COMPANY['Company Phone Number'] in html
    assert COMPANY['Company Email Address'] in html
    assert COMPANY['Company Website URL'] in html


def test_invoice_plaintext_emits_seller_header(tmp_path):
    """`print-invoice --format plaintext` emits a `# Issued by: <name> |
    Company ID: <id> | <addr> | <phone> | <email> | <url>` comment
    header so the recipient knows who issued the invoice. The header
    is a parser-skipped comment, so it doesn't leak into the
    recipient's book on re-import."""
    runner = CliRunner()
    gnc = _book_with_company(
        runner, tmp_path, 'q019_unposted_cash_with_tax.txt',
    )
    out_txt = tmp_path / 'invoice.txt'
    r = runner.invoke(cli, [
        'print-invoice', str(gnc), 'INV-Q19-CASH-TAX-200',
        '--format', 'plaintext', '-o', str(out_txt),
    ])
    assert r.exit_code == 0, f'print-invoice: {r.output}'

    text = out_txt.read_text()
    assert text.startswith('# Issued by: '), (
        f'plaintext must start with seller `#` header; got:\n{text[:500]}'
    )
    assert COMPANY['Company Name'] in text
    assert COMPANY['Company ID'] in text
    assert COMPANY['Company Phone Number'] in text
    assert COMPANY['Company Email Address'] in text
    assert COMPANY['Company Website URL'] in text


# ── Bill two-sided rendering ───────────────────────────────────────

_BILL_FIXTURE = 'q019_unposted_cash_bill.txt'


def test_bill_html_renders_both_vendor_and_company(tmp_path):
    """`print-bill --format html` shows the vendor in the client block — a
    bill is the vendor's invoice, and GnuCash draws it from the same report —
    with us in the company block.

    The figures are checked too (4×50 = 200, GST 5% + PST 7% = 24.00), so this
    covers Q-019's draft tax on bills: the document is unposted, and GnuCash
    prices an unposted one from its entries and says it is in progress.
    """
    runner = CliRunner()
    gnc = _book_with_company(runner, tmp_path, _BILL_FIXTURE)

    out_html = tmp_path / 'bill.html'
    r = runner.invoke(cli, [
        'print-bill', str(gnc), 'BILL-Q19-CASH-TAX-400',
        '--format', 'html', '-o', str(out_html),
    ])
    assert r.exit_code == 0, f'print-bill: {r.output}'

    html = readable(out_html.read_text())

    # Vendor side: the document's owner, in the report's client block.
    assert 'client-name">Office Depot Wholesale<' in html, (
        f'vendor name must head the client block; HTML:\n{html}'
    )

    # Seller side (us).
    assert f'company-name">{COMPANY["Company Name"]}<' in html
    assert COMPANY['Company ID'] in html
    assert '100 Main St' in html

    # What GnuCash prices the entries at, with each tax named.
    assert '>C$200.00<' in html, f'4 × C$50.00; HTML:\n{html}'
    assert '>GST</td>' in html and '>C$10.00<' in html, (
        f'5% of C$200.00, under its own name; HTML:\n{html}')
    assert '>PST</td>' in html and '>C$14.00<' in html, (
        f'7% of C$200.00, under its own name; HTML:\n{html}')
    assert '>C$224.00<' in html, f'grand total; HTML:\n{html[-2000:]}'
    assert is_in_progress(html), (
        f'an unposted document is drawn as in progress; HTML:\n{html}')


def test_bill_plaintext_emits_seller_and_vendor_headers(tmp_path):
    """`print-bill --format plaintext` emits two leading `#` lines: the
    seller header naming us (the recipient) and a `# Bill from vendor:`
    line naming the supplier. Both are comments → don't survive
    re-import."""
    runner = CliRunner()
    gnc = _book_with_company(runner, tmp_path, _BILL_FIXTURE)

    out_txt = tmp_path / 'bill.txt'
    r = runner.invoke(cli, [
        'print-bill', str(gnc), 'BILL-Q19-CASH-TAX-400',
        '--format', 'plaintext', '-o', str(out_txt),
    ])
    assert r.exit_code == 0, f'print-bill: {r.output}'

    text = out_txt.read_text()
    assert text.startswith('# Bill received by: '), (
        f'plaintext must start with `# Bill received by:` header; '
        f'got:\n{text[:500]}'
    )
    assert COMPANY['Company Name'] in text
    assert COMPANY['Company ID'] in text
    assert '# Bill from vendor: Office Depot Wholesale' in text
    assert '# Tax figures are provisional' in text, (
        f'unposted bill must carry provisional-tax caveat; got:\n{text}'
    )
    # Q-017 bill_* informational totals appear.
    assert 'bill_subtotal: 200.00' in text
    assert 'bill_tax_total: 24.00' in text
    assert 'bill_total: 224.00' in text


# ── Seller-header round-trip ──────────────────────────────────────

def test_rendered_plaintext_with_seller_header_reimports_cleanly(tmp_path):
    """A rendered invoice that carries `# Issued by: ...` (because the
    source book had Business→Company options populated) must re-import
    cleanly into a fresh book — the parser's `#`-comment skip is what
    keeps the seller info from leaking into the recipient's KVP slots.
    The Q-019 draft-tax round-trip test only exercises the
    `# Tax figures are provisional` caveat; this test adds explicit
    coverage with the seller header actually present."""
    runner = CliRunner()
    gnc = _book_with_company(
        runner, tmp_path, 'q019_unposted_cash_with_tax.txt',
    )
    out_txt = tmp_path / 'rendered.txt'
    r = runner.invoke(cli, [
        'print-invoice', str(gnc), 'INV-Q19-CASH-TAX-200',
        '--format', 'plaintext', '-o', str(out_txt),
    ])
    assert r.exit_code == 0, f'print-invoice: {r.output}'
    rendered = out_txt.read_text()
    # Precondition: the rendered text must actually carry the seller
    # header — otherwise this test isn't exercising what it claims.
    assert rendered.startswith('# Issued by: Acme Plaintext Co.'), (
        f'rendered text missing seller header — test premise broken; '
        f'got:\n{rendered[:300]}'
    )

    fresh_gnc = tmp_path / 'fresh.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(fresh_gnc), ACCOUNTS])
    assert r.exit_code == 0, f'fresh accounts: {r.output}'
    r = runner.invoke(cli, ['import', str(fresh_gnc), str(out_txt),
                            '--include-business-objects'])
    assert r.exit_code == 0, (
        f'rendered plaintext (with seller `#` header) must re-import '
        f'cleanly; the parser must skip the `#` lines so they don\'t '
        f'land as KVPs in the recipient\'s book. Got:\n{r.output}'
    )
