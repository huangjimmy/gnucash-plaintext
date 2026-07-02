"""Q-017 — `print-invoice` learns `--format plaintext` (with informational
fields covering line-item tax breakdown, subtotal, tax total, total) and
multi-invoice selection (positional IDs, --from/--to, --customer, glob).

The plaintext format is the same canonical format used for export/import.
Informational fields are emitted by the renderer and validated on
re-import: the importer recomputes from the source-of-truth fields
(quantity, price, tax_table, tax_included) and errors loudly on mismatch.
"""
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q017_accounts.txt')


def _fx(name):
    return (FIXTURES / name).read_text()


def _build_book(runner, tmp_path, *fixture_files):
    """Import accounts + fixtures into a fresh book."""
    gf = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf), ACCOUNTS])
    assert r.exit_code == 0, f'accounts import: {r.output}'
    for fx in fixture_files:
        r = runner.invoke(cli, ['import', str(gf), fx,
                                '--include-business-objects'])
        assert r.exit_code == 0, f'{fx} import: {r.output}'
    return gf


# ── Informational-field emission ────────────────────────────────────────────

def test_print_invoice_plaintext_format_emits_informational_fields(tmp_path):
    """Single HST 13% line on $100. Plaintext render emits entry_amount,
    entry_tax, invoice_subtotal, invoice_tax_total, invoice_total."""
    runner = CliRunner()
    gf = _build_book(runner, tmp_path,
                     str(FIXTURES / 'q017_simple_hst_invoice.txt'))
    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf),
                            '--invoice-id', 'INV-Q17-HST-100',
                            '--format', 'plaintext',
                            '-o', str(out)])
    assert r.exit_code == 0, f'render: {r.output}'
    text = out.read_text()
    assert 'entry_amount: 100.00' in text, f'missing entry_amount:\n{text}'
    assert 'entry_tax: 13.00' in text, f'missing entry_tax:\n{text}'
    assert 'invoice_subtotal: 100.00' in text, f'missing subtotal:\n{text}'
    assert 'invoice_tax_total: 13.00' in text, f'missing tax_total:\n{text}'
    assert 'invoice_total: 113.00' in text, f'missing total:\n{text}'


def test_print_invoice_plaintext_emits_tax_breakdown_combined_table(tmp_path):
    """Combined HST = 5% GST + 8% PST on $200. Breakdown lists each
    tax-table entry's account/rate/amount with the right dollars."""
    runner = CliRunner()
    gf = _build_book(runner, tmp_path,
                     str(FIXTURES / 'q017_combined_hst_invoice.txt'))
    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf),
                            '--invoice-id', 'INV-Q17-COMBINED-200',
                            '--format', 'plaintext',
                            '-o', str(out)])
    assert r.exit_code == 0, f'render: {r.output}'
    text = out.read_text()
    # Per-entry totals
    assert 'entry_amount: 200.00' in text
    assert 'entry_tax: 26.00' in text, f'5% + 8% on $200 = $26:\n{text}'
    # Breakdown blocks (one `breakdown:` per tax-table entry)
    assert text.count('breakdown:') >= 2, (
        f'expected one breakdown: block per GST/PST entry:\n{text}'
    )
    assert 'account: "Liabilities:Tax:GST"' in text
    assert 'account: "Liabilities:Tax:PST"' in text
    assert 'rate: 5.0' in text and 'amount: 10.00' in text  # 5% on $200
    assert 'rate: 8.0' in text and 'amount: 16.00' in text  # 8% on $200
    # Invoice totals
    assert 'invoice_subtotal: 200.00' in text
    assert 'invoice_tax_total: 26.00' in text
    assert 'invoice_total: 226.00' in text


def test_render_plaintext_roundtrips_via_import(tmp_path):
    """`print-invoice --format plaintext` output must re-import into a
    fresh book cleanly. Informational fields validate against the
    recomputed values."""
    runner = CliRunner()
    gf_src = _build_book(runner, tmp_path,
                         str(FIXTURES / 'q017_simple_hst_invoice.txt'))
    rendered = tmp_path / 'rendered.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf_src),
                            '--invoice-id', 'INV-Q17-HST-100',
                            '--format', 'plaintext',
                            '-o', str(rendered)])
    assert r.exit_code == 0
    # The rendered file is invoice-only; for re-import we need accounts +
    # taxtable + customer too. Concatenate the source fixtures.
    full = tmp_path / 'full.txt'
    full.write_text(
        _fx('q017_accounts.txt')
        + '\n'
        + rendered.read_text()
    )
    gf_dst = tmp_path / 'fresh.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_dst), str(full),
                            '--include-business-objects'])
    assert r.exit_code == 0, f're-import: {r.output}'


def test_tampered_invoice_total_errors_loudly(tmp_path):
    """A hand-edited `invoice_total:` that disagrees with recomputed value
    must produce a clear error naming the field and both numbers."""
    runner = CliRunner()
    gf_src = _build_book(runner, tmp_path,
                         str(FIXTURES / 'q017_simple_hst_invoice.txt'))
    rendered = tmp_path / 'rendered.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf_src),
                            '--invoice-id', 'INV-Q17-HST-100',
                            '--format', 'plaintext',
                            '-o', str(rendered)])
    assert r.exit_code == 0
    tampered = rendered.read_text().replace(
        'invoice_total: 113.00', 'invoice_total: 999.00'
    )
    full = tmp_path / 'full.txt'
    full.write_text(_fx('q017_accounts.txt') + '\n' + tampered)
    gf_dst = tmp_path / 'fresh.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_dst), str(full),
                            '--include-business-objects'])
    assert r.exit_code != 0
    assert 'invoice_total' in r.output
    assert '999' in r.output and '113' in r.output, (
        f'error must name both the declared and recomputed values:\n{r.output}'
    )


def test_tampered_entry_tax_breakdown_errors_loudly(tmp_path):
    """A tampered breakdown amount (PST: 16.00 → 99.00) must also fail."""
    runner = CliRunner()
    gf_src = _build_book(runner, tmp_path,
                         str(FIXTURES / 'q017_combined_hst_invoice.txt'))
    rendered = tmp_path / 'rendered.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf_src),
                            '--invoice-id', 'INV-Q17-COMBINED-200',
                            '--format', 'plaintext',
                            '-o', str(rendered)])
    assert r.exit_code == 0
    tampered = rendered.read_text().replace('amount: 16.00', 'amount: 99.00', 1)
    full = tmp_path / 'full.txt'
    full.write_text(_fx('q017_accounts.txt') + '\n' + tampered)
    gf_dst = tmp_path / 'fresh.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gf_dst), str(full),
                            '--include-business-objects'])
    assert r.exit_code != 0
    assert 'breakdown' in r.output.lower(), (
        f'error must mention the breakdown field:\n{r.output}'
    )


def test_draft_invoice_plaintext_emits_provisional_totals(tmp_path):
    """Q-019: drafts now render the full informational stack — subtotal,
    tax_total, total, per-entry entry_tax — computed from each entry's
    tax_table (independent of posting state). A `# Tax figures are
    provisional` comment header tells the recipient the numbers will
    be recomputed at post time. For the fixture's single non-taxable
    line item, tax_total = 0.00 and total == subtotal."""
    runner = CliRunner()
    gf = _build_book(runner, tmp_path,
                     str(FIXTURES / 'q017_draft_invoice.txt'))
    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf),
                            '--invoice-id', 'INV-Q17-DRAFT-50',
                            '--format', 'plaintext',
                            '-o', str(out)])
    assert r.exit_code == 0, f'render: {r.output}'
    text = out.read_text()
    assert '# Tax figures are provisional' in text, (
        f'draft must carry provisional-tax caveat; got:\n{text}'
    )
    assert 'invoice_subtotal: 50.00' in text
    assert 'invoice_tax_total: 0.00' in text, (
        f'draft must emit tax_total even when zero (post-Q-019):\n{text}'
    )
    assert 'invoice_total: 50.00' in text, (
        f'draft must emit grand total (post-Q-019):\n{text}'
    )
    assert 'entry_tax: 0.00' in text, (
        f'draft must emit per-entry entry_tax (post-Q-019):\n{text}'
    )


# ── Multi-invoice selection ────────────────────────────────────────────────

def test_multi_invoice_by_positional_ids(tmp_path):
    """Multiple positional IDs select exactly those invoices. Rendered
    plaintext output contains each invoice's block."""
    runner = CliRunner()
    gf = _build_book(runner, tmp_path,
                     str(FIXTURES / 'q017_multi_invoices.txt'))
    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf),
                            'INV-Q17-A-100', 'INV-Q17-C-300',
                            '--format', 'plaintext',
                            '-o', str(out)])
    assert r.exit_code == 0, f'render: {r.output}'
    text = out.read_text()
    assert 'INV-Q17-A-100' in text
    assert 'INV-Q17-C-300' in text
    assert 'INV-Q17-B-200' not in text
    assert 'INV-Q17-D-400' not in text


def test_multi_invoice_by_date_range(tmp_path):
    """--from/--to filters by date_opened. Q1 (Jan/Feb/Mar) selects 3 of
    4 invoices."""
    runner = CliRunner()
    gf = _build_book(runner, tmp_path,
                     str(FIXTURES / 'q017_multi_invoices.txt'))
    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf),
                            '--from', '2026-01-01',
                            '--to', '2026-03-31',
                            '--format', 'plaintext',
                            '-o', str(out)])
    assert r.exit_code == 0, f'render: {r.output}'
    text = out.read_text()
    assert 'INV-Q17-A-100' in text
    assert 'INV-Q17-B-200' in text
    assert 'INV-Q17-C-300' in text
    assert 'INV-Q17-D-400' not in text


def test_multi_invoice_by_customer(tmp_path):
    """--customer filters to invoices for one customer."""
    runner = CliRunner()
    gf = _build_book(runner, tmp_path,
                     str(FIXTURES / 'q017_multi_invoices.txt'))
    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf),
                            '--customer', 'CUST-Y',
                            '--format', 'plaintext',
                            '-o', str(out)])
    assert r.exit_code == 0, f'render: {r.output}'
    text = out.read_text()
    assert 'INV-Q17-A-100' not in text
    assert 'INV-Q17-B-200' not in text
    assert 'INV-Q17-C-300' in text
    assert 'INV-Q17-D-400' in text


def test_multi_invoice_glob(tmp_path):
    """Positional glob 'INV-Q17-?-???' matches all four; the more
    restrictive 'INV-Q17-A-*' matches only INV-Q17-A-100."""
    runner = CliRunner()
    gf = _build_book(runner, tmp_path,
                     str(FIXTURES / 'q017_multi_invoices.txt'))
    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf),
                            'INV-Q17-A-*',
                            '--format', 'plaintext',
                            '-o', str(out)])
    assert r.exit_code == 0, f'render: {r.output}'
    text = out.read_text()
    assert 'INV-Q17-A-100' in text
    assert 'INV-Q17-B-200' not in text


def test_multi_invoice_output_dir_one_file_per_invoice(tmp_path):
    """--output dir/ writes one file per selected invoice."""
    runner = CliRunner()
    gf = _build_book(runner, tmp_path,
                     str(FIXTURES / 'q017_multi_invoices.txt'))
    outdir = tmp_path / 'out'
    outdir.mkdir()
    r = runner.invoke(cli, ['print-invoice', str(gf),
                            'INV-Q17-A-100', 'INV-Q17-B-200',
                            '--format', 'plaintext',
                            '-o', str(outdir) + '/'])
    assert r.exit_code == 0, f'render: {r.output}'
    files = sorted(p.name for p in outdir.iterdir())
    assert 'INV-Q17-A-100.txt' in files
    assert 'INV-Q17-B-200.txt' in files
    assert len(files) == 2, f'expected 2 files, got {files}'


def test_plaintext_to_stdout(tmp_path):
    """--output - writes plaintext to stdout (for piping)."""
    runner = CliRunner()
    gf = _build_book(runner, tmp_path,
                     str(FIXTURES / 'q017_simple_hst_invoice.txt'))
    r = runner.invoke(cli, ['print-invoice', str(gf),
                            '--invoice-id', 'INV-Q17-HST-100',
                            '--format', 'plaintext',
                            '-o', '-'])
    assert r.exit_code == 0, f'render: {r.output}'
    assert 'invoice "INV-Q17-HST-100"' in r.output
    assert 'invoice_total: 113.00' in r.output


def test_no_selection_matches_errors(tmp_path):
    """A glob/filter that selects zero invoices must fail loudly, not
    write an empty output."""
    runner = CliRunner()
    gf = _build_book(runner, tmp_path,
                     str(FIXTURES / 'q017_multi_invoices.txt'))
    out = tmp_path / 'inv.txt'
    r = runner.invoke(cli, ['print-invoice', str(gf),
                            'NONEXISTENT-*',
                            '--format', 'plaintext',
                            '-o', str(out)])
    assert r.exit_code != 0
    assert 'no invoices' in r.output.lower() or 'no match' in r.output.lower(), (
        f'must explain the empty selection:\n{r.output}'
    )
