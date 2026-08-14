"""Q-028: the book-level `company` directive round-trips GnuCash's Business →
Company options (Company Name/Contact/Phone/Fax/Email/URL/ID + the custom
GST/PST registration numbers), and `print-invoice` / `print-bill` render the
GST/PST in the seller block.

Before this feature the company block was read for rendering but never
exported/imported, so a roundtrip into a fresh book silently dropped every
field — Company ID included. These tests pin that the whole block survives a
double roundtrip, and that GST and each PST number reach the rendered output.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
COMPANY = str(FIXTURES / 'company_full.txt')

# Field values as written in tests/fixtures/company_full.txt.
EXPECTED = {
    'name':    'Acme Plaintext Co.',
    'contact': 'Jane Doe',
    'id':      '123456789RT0001',
    'gst':     '123456789RT0001',
    'pst':     'BC PST-1234-5678; SK 9012-3456',
    'addr1':   '100 Main St',
    'addr2':   'Suite 200',
    'addr3':   'Toronto ON M5H 1A1',
    'phone':   '+1-555-0142',
    'fax':     '+1-555-0199',
    'email':   'billing@acmeplain.test',
    'url':     'https://acmeplain.test',
}


def _new_book(runner, tmp_path, name='book.gnucash'):
    gf = tmp_path / name
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, r.output
    return gf


def _import(runner, gf, content, tmp_path, name):
    p = tmp_path / name
    p.write_text(content)
    r = runner.invoke(cli, ['import', str(gf), str(p), '--include-business-objects'])
    assert r.exit_code == 0, r.output


def _export(runner, gf, tmp_path, name='exp.txt'):
    out = tmp_path / name
    r = runner.invoke(cli, ['export', str(gf), str(out), '--include-business-objects'])
    assert r.exit_code == 0, r.output
    return out.read_text()


def _company_block(text):
    """Extract the `company` directive block (header + its indented children)
    from an export."""
    out = []
    capturing = False
    for line in text.splitlines():
        if not capturing:
            if line.strip() == 'company' and not line[:1].isspace():
                capturing = True
                out.append(line)
            continue
        if line[:1].isspace():
            out.append(line)
        else:
            break
    return '\n'.join(out)


def _company_fields(text):
    """Parse the exported company block into {key: value}."""
    fields = {}
    for line in _company_block(text).splitlines()[1:]:
        key, _, val = line.strip().partition(':')
        val = val.strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        fields[key.strip()] = val
    return fields


def test_company_directive_imports_and_exports_every_field(tmp_path):
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    _import(runner, gf, Path(COMPANY).read_text(), tmp_path, 'company.txt')
    fields = _company_fields(_export(runner, gf, tmp_path))
    for key, want in EXPECTED.items():
        assert fields.get(key) == want, (key, fields)


def test_company_block_survives_double_roundtrip(tmp_path):
    """export → import (fresh book) → export must keep the company block
    byte-for-byte identical. This is the Company-ID roundtrip coverage that
    did not exist before: every native field plus GST/PST is preserved."""
    runner = CliRunner()
    gf_a = _new_book(runner, tmp_path, 'A.gnucash')
    _import(runner, gf_a, Path(COMPANY).read_text(), tmp_path, 'company.txt')

    e1 = _export(runner, gf_a, tmp_path, 'e1.txt')
    block1 = _company_block(e1)
    assert block1, f'no company block in first export:\n{e1}'

    gf_b = tmp_path / 'B.gnucash'
    (tmp_path / 'e1_in.txt').write_text(e1)
    assert runner.invoke(cli, ['import', '--new', str(gf_b),
                               str(tmp_path / 'e1_in.txt'),
                               '--include-business-objects']).exit_code == 0
    e2 = _export(runner, gf_b, tmp_path, 'e2.txt')
    block2 = _company_block(e2)

    assert block1 == block2, (
        f'company block drifted across roundtrip:\n--- e1 ---\n{block1}\n'
        f'--- e2 ---\n{block2}'
    )
    # Explicit: Company ID and both PST numbers really are there after the
    # fresh-book roundtrip (not just equal-but-empty).
    f2 = _company_fields(e2)
    assert f2['id'] == EXPECTED['id']
    assert f2['gst'] == EXPECTED['gst']
    assert f2['pst'] == EXPECTED['pst']


def test_book_without_company_options_exports_no_company_block(tmp_path):
    """A book with no Business→Company options must export no `company`
    directive — the baseline export is unchanged for books that never set
    company info."""
    runner = CliRunner()
    gf = _new_book(runner, tmp_path)
    assert _company_block(_export(runner, gf, tmp_path)) == ''


def _book_with_company_and(runner, tmp_path, doc_fixture):
    gf = _new_book(runner, tmp_path)
    combined = (Path(COMPANY).read_text() + '\n\n'
                + (FIXTURES / doc_fixture).read_text())
    _import(runner, gf, combined, tmp_path, 'doc.txt')
    return gf


def test_print_invoice_plaintext_renders_gst_and_each_pst(tmp_path):
    runner = CliRunner()
    gf = _book_with_company_and(runner, tmp_path, 'q019_unposted_cash_with_tax.txt')
    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf), 'INV-Q19-CASH-TAX-200',
                            '--format', 'plaintext', '-o', str(out)])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert 'GST: 123456789RT0001' in text, text
    assert 'PST: BC PST-1234-5678' in text, text
    assert 'PST: SK 9012-3456' in text, text


def _assert_full_company_rendered(doc):
    """Every populated company field must appear in the rendered output.
    Requirement: if the book carries company info, the invoice/bill prints
    all of it — name, contact, Company ID, GST, every PST number, address,
    phone, fax, email, url.

    GnuCash's own page has a row for all of those but the registration
    numbers, which GnuCash has no field for: they are book options this tool
    writes, and the seller's block on the page states them by name."""
    for key, want in EXPECTED.items():
        if key in ('gst', 'pst'):
            continue  # labelled, and PST is one row per number — below
        assert want in doc, f'company field {key!r} ({want!r}) missing from render:\n{doc}'
    assert f'GST: {EXPECTED["gst"]}' in doc, f'GST missing from render:\n{doc}'
    for pst in ('BC PST-1234-5678', 'SK 9012-3456'):
        assert f'PST: {pst}' in doc, f'PST {pst!r} missing from render:\n{doc}'


def test_print_invoice_html_renders_full_company_block(tmp_path):
    runner = CliRunner()
    gf = _book_with_company_and(runner, tmp_path, 'q019_unposted_cash_with_tax.txt')
    out = tmp_path / 'inv.html'
    r = runner.invoke(cli, ['print-invoice', str(gf), 'INV-Q19-CASH-TAX-200',
                            '--format', 'html', '-o', str(out)])
    assert r.exit_code == 0, r.output
    html = out.read_text()
    assert f'company-name">{EXPECTED["name"]}<' in html, (
        f'the company must head its block:\n{html}')
    _assert_full_company_rendered(html)


def test_print_bill_html_renders_full_company_block(tmp_path):
    runner = CliRunner()
    gf = _book_with_company_and(runner, tmp_path, 'q019_unposted_cash_bill.txt')
    bill_id = _bill_id('q019_unposted_cash_bill.txt')
    out = tmp_path / 'bill.html'
    r = runner.invoke(cli, ['print-bill', str(gf), bill_id,
                            '--format', 'html', '-o', str(out)])
    assert r.exit_code == 0, r.output
    _assert_full_company_rendered(out.read_text())


def _bill_id(fixture_name):
    """Discover the bill id from a fixture's `bill "..."` header."""
    for line in (FIXTURES / fixture_name).read_text().splitlines():
        if line.startswith('bill "'):
            return line.split('"')[1]
    raise AssertionError(f'no bill header in {fixture_name}')


def test_print_bill_plaintext_renders_gst_and_each_pst(tmp_path):
    runner = CliRunner()
    gf = _book_with_company_and(runner, tmp_path, 'q019_unposted_cash_bill.txt')
    bill_id = _bill_id('q019_unposted_cash_bill.txt')
    out = tmp_path / 'bill.txt'
    r = runner.invoke(cli, ['print-bill', str(gf), bill_id,
                            '--format', 'plaintext', '-o', str(out)])
    assert r.exit_code == 0, r.output
    text = out.read_text()
    assert 'GST: 123456789RT0001' in text, text
    assert 'PST: BC PST-1234-5678' in text, text
    assert 'PST: SK 9012-3456' in text, text
