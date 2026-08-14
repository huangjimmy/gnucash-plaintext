"""Combined-output HTML structure tests for print-invoice / print-bill.

When several documents are rendered into one HTML or PDF file, each is a whole
page of GnuCash's own — its own `<!DOCTYPE>`, `<html>`, `<head>` and `<body>` —
and concatenating them gives a file with three of each, which is malformed as
HTML and as XML both. `services/document_pages.combine_pages` takes them apart
and rebuilds one shell: one `<head>`, kept once so the pages stay styled, and
each document's body inside a `<div>` that breaks the page after it.

Two regressions caught by these tests, from when the stripping was done tag by
tag in each print command:

  1. `inner.replace('<html>', '')` never matched a real opening tag, which
     carries attributes — every fragment kept its wrapper and the combined
     file had one `<html` per document plus the outer one.
  2. The per-document `<!DOCTYPE>` declarations were not removed either, so
     they ended up scattered through the body.

Tests assert structural counts rather than XML well-formedness: the pages are
HTML, not XHTML, and `<meta charset>` and friends close HTML-style.
"""
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
    fx1 = tmp_path / 'inv1.txt'
    fx1.write_text(_fx('q019_unposted_cash_with_tax.txt'))
    r = runner.invoke(cli, ['import', str(gnc), str(fx1),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'inv1: {r.output}'
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
    return gnc, 'INV-Q19-CASH-TAX-200', 'INV-Q19-CASH-TAX-201'


def _book_with_two_bills(runner, tmp_path):
    """Bill-side analogue of _book_with_two_invoices."""
    gnc = tmp_path / 'book.gnucash'
    r = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert r.exit_code == 0, f'accounts: {r.output}'
    fx1 = tmp_path / 'bill1.txt'
    fx1.write_text(_fx('q019_unposted_cash_bill.txt'))
    r = runner.invoke(cli, ['import', str(gnc), str(fx1),
                            '--include-business-objects'])
    assert r.exit_code == 0, f'bill1: {r.output}'
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
    return gnc, 'BILL-Q19-CASH-TAX-400', 'BILL-Q19-CASH-TAX-401'


def _assert_one_outer_shell(html):
    """Combined HTML must have exactly one of each opening tag — one
    `<!DOCTYPE>`, one `<html…>`, one `</html>`, one `<body…>`, one
    `</body>`. Counts both `<html>` and `<html dir='auto'>` form via the
    `<html` token, since the original bug was that
    `inner.replace('<html>', '')` missed the attributed form.

    One and not zero: the shell is GnuCash's own, carried from the first
    fragment. A page with no DOCTYPE is a quirks-mode page, and this
    assertion read `== 0` while the fragments were HTML 4.01 stripped tag by
    tag — which pinned the loss as correct."""
    n_doctype = html.count('<!DOCTYPE')
    n_html_open = html.count('<html')
    n_html_close = html.count('</html>')
    n_body_open = html.count('<body')
    n_body_close = html.count('</body>')

    assert n_doctype == 1, (
        f'combined HTML must carry exactly one DOCTYPE — the report\'s own, '
        f'from the first fragment; got {n_doctype}. Zero puts the page in '
        f'quirks mode, more than one is what the per-fragment declarations '
        f'did before they were taken apart. Output:\n{html[:3000]}'
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


def test_one_document_is_the_same_page_whichever_way_it_is_written(tmp_path):
    """`-o invoice.html` and `-o dir/` must produce the same document.

    The combining path is taken for *one* document as well as for several —
    `-o file.html` and `-o file.pdf` go through it whatever the count — while
    `-o dir/` writes what GnuCash drew, untouched. So the two are the same
    page rebuilt and the same page verbatim, and anything the rebuild drops
    shows up here as a difference: the DOCTYPE, `dir='auto'`, the body's
    colours. It dropped all three, and one invoice came out in standards mode
    one way and quirks mode the other.

    Compared on the shell rather than byte for byte, because the combined form
    legitimately adds the `<div>` wrapper that breaks pages.
    """
    runner = CliRunner()
    gnc, id1, _ = _book_with_two_invoices(runner, tmp_path)

    one_file = tmp_path / 'one.html'
    assert runner.invoke(cli, [
        'print-invoice', str(gnc), id1, '--format', 'html', '-o',
        str(one_file)]).exit_code == 0
    outdir = tmp_path / 'perdoc'
    assert runner.invoke(cli, [
        'print-invoice', str(gnc), id1, '--format', 'html', '-o',
        f'{outdir}/']).exit_code == 0

    combined = one_file.read_text()
    verbatim = (outdir / f'{id1}.html').read_text()

    for tag in ('<!DOCTYPE', '<html', '<body'):
        opening = verbatim[verbatim.index(tag):
                           verbatim.index('>', verbatim.index(tag)) + 1]
        assert opening in combined, (opening, combined[:600])


def test_print_invoice_combined_html_has_one_outer_shell(tmp_path):
    """Combined two-invoice HTML carries exactly one outer wrapper: one
    DOCTYPE, one <html>, one </html>, one <body>, one </body>. Catches both
    the `<html lang="en">`-not-stripped and the `<!DOCTYPE>`-duplicated bugs
    in one shot."""
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


def test_the_combined_page_keeps_the_reports_styling(tmp_path):
    """One shell, and the `<head>` that shell needs.

    GnuCash writes the report's whole stylesheet into each page's `<head>`, so
    dropping the head — which stripping tag by tag does, and which every
    assertion above is silent about — gives a combined file that is
    structurally perfect and prints in a browser's defaults, where the same
    documents printed one at a time come out styled. So the rules that lay the
    page out are looked for, not merely the shell around them.
    """
    runner = CliRunner()
    gnc, id1, id2 = _book_with_two_invoices(runner, tmp_path)
    out = tmp_path / 'combined.html'
    r = runner.invoke(cli, [
        'print-invoice', str(gnc), id1, id2,
        '--format', 'html', '-o', str(out),
    ])
    assert r.exit_code == 0, f'print-invoice: {r.output}'
    html = out.read_text()

    assert html.count('<head>') == 1, html[:2000]
    assert html.count('<style') == 1, html[:2000]
    # And the tags' own attributes, which are the rest of what GnuCash
    # decided about this page: the direction it reads in, and the colours
    # its stylesheet set — `html-document.scm` writes that body tag with the
    # comment "this lovely little number just makes sure that <body>
    # attributes like bgcolor get included".
    assert "<html dir='auto'>" in html, html[:2000]
    assert '<body bgcolor=' in html, html[:2000]
    # Two rules the report's own CSS carries, and the entries table is the
    # part of the page that reads as a table only because of them.
    for rule in ('.entries-table', 'td.total-number-cell'):
        assert rule in html, (rule, html[:3000])
    # In the head, not loose in the body where a stripped page would leave it.
    head = html[html.index('<head>'):html.index('</head>')]
    assert '.entries-table' in head, head
