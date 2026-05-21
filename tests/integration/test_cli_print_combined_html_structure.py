"""Combined-output HTML structure tests for print-invoice / print-bill.

When users render multiple invoices or bills into a single HTML / PDF
file (combined mode), each per-document fragment must have its outer
`<!DOCTYPE>`, `<html>…</html>`, and `<body>…</body>` shells stripped
before being wrapped in the combined doc's single outer shell.
Otherwise the combined output has nested DOCTYPEs and nested `<html>`
elements — malformed under HTML 4.01 (and any HTML 5 reading).

Two regressions caught by these tests:
  1. The strip code was `inner.replace('<html>', '')`, which never
     matched the XSLT's actual `<html lang="en">` opening tag — every
     fragment kept its full wrapper, combined output had N+1 `<html`
     opening tags (one outer + one per fragment).
  2. The strip code didn't remove the per-fragment
     `<!DOCTYPE html PUBLIC …>` declarations either, so the combined
     body contained scattered inline DOCTYPEs (also illegal).

Fixed in cli/{invoice,bill}_print_cmd.py: regex strips opening
`<html…>` / `<body…>` with any attributes, plus `<!DOCTYPE …>`.

Test contract: the XSLT uses `<xsl:output method="html"
doctype-public="…HTML 4.01…">`, so combined output is HTML 4.01 (not
XHTML — `<meta charset>` and friends self-close HTML-style without
the slash). Tests assert structural counts rather than XML
well-formedness so they reflect the actual format contract.
"""
import time
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')


def _fx(name):
    return (FIXTURES / name).read_text()


def _book_with_two_invoices(runner, tmp_path):
    """Import two cash-basis invoices with different IDs so we can
    feed both into a combined print-invoice run. Returns the .gnucash
    path and the two invoice IDs."""
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    time.sleep(1)
    fx1 = tmp_path / 'inv1.txt'
    fx1.write_text(_fx('q019_unposted_cash_with_tax.txt'))
    r = runner.invoke(cli, ['import', str(gnc), str(fx1),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'inv1: {r.output}'
    time.sleep(1)
    # Second invoice — rewrite IDs and customer so the importer treats
    # it as a new record rather than an update to the first.
    fx2_text = _fx('q019_unposted_cash_with_tax.txt').replace(
        'INV-Q19-CASH-TAX-200', 'INV-Q19-CASH-TAX-201',
    ).replace(
        '"C-Q19-1"', '"C-Q19-1B"',
    ).replace(
        'Beta Industries', 'Beta Two',
    )
    fx2 = tmp_path / 'inv2.txt'
    fx2.write_text(fx2_text)
    r = runner.invoke(cli, ['import', str(gnc), str(fx2),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'inv2: {r.output}'
    time.sleep(1)
    return gnc, 'INV-Q19-CASH-TAX-200', 'INV-Q19-CASH-TAX-201'


def _book_with_two_bills(runner, tmp_path):
    """Bill-side analogue of _book_with_two_invoices."""
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    time.sleep(1)
    fx1 = tmp_path / 'bill1.txt'
    fx1.write_text(_fx('q019_unposted_cash_bill.txt'))
    r = runner.invoke(cli, ['import', str(gnc), str(fx1),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'bill1: {r.output}'
    time.sleep(1)
    fx2_text = _fx('q019_unposted_cash_bill.txt').replace(
        'BILL-Q19-CASH-TAX-400', 'BILL-Q19-CASH-TAX-401',
    ).replace(
        '"V-Q19-1"', '"V-Q19-1B"',
    ).replace(
        'Office Depot Wholesale', 'Office Depot Two',
    )
    fx2 = tmp_path / 'bill2.txt'
    fx2.write_text(fx2_text)
    r = runner.invoke(cli, ['import', str(gnc), str(fx2),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'bill2: {r.output}'
    time.sleep(1)
    return gnc, 'BILL-Q19-CASH-TAX-400', 'BILL-Q19-CASH-TAX-401'


def _assert_one_outer_shell(html):
    """Combined HTML must have exactly one outer `<!DOCTYPE>` (zero,
    in our case — the outer wrapper doesn't emit one), one `<html…>`,
    one `</html>`, one `<body…>`, and one `</body>`. Counts both
    `<html>` and `<html lang="en">` form via the `<html` token, since
    the original bug was that `inner.replace('<html>', '')` missed
    the attributed form."""
    n_doctype = html.count('<!DOCTYPE')
    n_html_open = html.count('<html')
    n_html_close = html.count('</html>')
    n_body_open = html.count('<body')
    n_body_close = html.count('</body>')

    assert n_doctype == 0, (
        f'combined HTML must have zero inline DOCTYPEs (outer wrapper '
        f'omits the declaration); got {n_doctype}. Pre-fix the '
        f'per-fragment `<!DOCTYPE html PUBLIC …>` survived the strip. '
        f'Output:\n{html[:3000]}'
    )
    assert n_html_open == 1, (
        f'combined HTML must have exactly one <html opening tag; '
        f'got {n_html_open}. Pre-fix the per-fragment <html lang="en"> '
        f'survived the strip. Output:\n{html[:3000]}'
    )
    assert n_html_close == 1, (
        f'combined HTML must have exactly one </html> closing tag; '
        f'got {n_html_close}.'
    )
    assert n_body_open == 1, (
        f'combined HTML must have exactly one <body opening tag; '
        f'got {n_body_open}.'
    )
    assert n_body_close == 1, (
        f'combined HTML must have exactly one </body> closing tag; '
        f'got {n_body_close}.'
    )


def test_print_invoice_combined_html_has_one_outer_shell(tmp_path):
    """Combined two-invoice HTML carries exactly one outer wrapper:
    no inline DOCTYPEs, one <html>, one </html>, one <body>, one
    </body>. Catches both the `<html lang="en">`-not-stripped and the
    `<!DOCTYPE>`-not-stripped bugs in one shot."""
    runner = CliRunner()
    gnc, id1, id2 = _book_with_two_invoices(runner, tmp_path)
    out = tmp_path / 'combined.html'
    r = runner.invoke(cli, [
        'print-invoice', str(gnc), id1, id2,
        '--format', 'html', '-o', str(out),
    ])
    assert r.exit_code == 0, f'print-invoice: {r.output}'
    _assert_one_outer_shell(out.read_text())


def test_print_bill_combined_html_has_one_outer_shell(tmp_path):
    """Bill-side mirror of the above. Bills inherit the same combine
    logic, so any regression in either CLI fails both tests."""
    runner = CliRunner()
    gnc, id1, id2 = _book_with_two_bills(runner, tmp_path)
    out = tmp_path / 'combined.html'
    r = runner.invoke(cli, [
        'print-bill', str(gnc), id1, id2,
        '--format', 'html', '-o', str(out),
    ])
    assert r.exit_code == 0, f'print-bill: {r.output}'
    _assert_one_outer_shell(out.read_text())
