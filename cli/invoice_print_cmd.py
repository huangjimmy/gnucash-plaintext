#!/usr/bin/env python
"""
CLI command for printing GnuCash invoices.

Q-017: supports `--format {pdf,html,plaintext}` and multi-invoice
selection (positional IDs / globs, `--from`/`--to` date range,
`--customer`). The plaintext format emits the canonical plaintext
syntax populated with informational totals (entry_amount, entry_tax,
breakdown:, invoice_subtotal, invoice_tax_total, invoice_total) — the
importer recomputes these on re-import and errors on mismatch.
"""

import fnmatch
import sys
from datetime import datetime
from pathlib import Path

import click
import gnucash.gnucash_business as gb
from gnucash import Query

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.invoice_renderer import (
    read_book_company_info,
    render_to_html,
    render_to_plaintext,
)

_XSLT_PATH = Path(__file__).parent.parent / "services" / "invoice.xslt"


def _all_invoices(book):
    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    results = []
    for r in q.run():
        inv = gb.Invoice(instance=r)
        # Customer invoices only (skip vendor bills)
        try:
            cust = inv.GetOwner().GetCustomer()
        except Exception:
            cust = None
        if cust is not None:
            results.append(inv)
    q.destroy()
    return results


def _filter_invoices(invoices, selectors, from_date, to_date, customer):
    """Apply all selectors (AND-composed). `selectors` is the list of
    positional arguments, each treated as either an exact invoice ID or
    a glob pattern when it contains *? characters."""
    out = invoices

    if selectors:
        def _matches(inv):
            inv_id = inv.GetID()
            for sel in selectors:
                if any(c in sel for c in '*?['):
                    if fnmatch.fnmatch(inv_id, sel):
                        return True
                elif inv_id == sel:
                    return True
            return False
        out = [inv for inv in out if _matches(inv)]

    if from_date:
        from_dt = datetime.strptime(from_date, '%Y-%m-%d').date()
        out = [inv for inv in out if inv.GetDateOpened().date() >= from_dt]
    if to_date:
        to_dt = datetime.strptime(to_date, '%Y-%m-%d').date()
        out = [inv for inv in out if inv.GetDateOpened().date() <= to_dt]

    if customer:
        out = [inv for inv in out
               if inv.GetOwner().GetCustomer() is not None
               and inv.GetOwner().GetCustomer().GetID() == customer]

    out.sort(key=lambda inv: (inv.GetDateOpened(), inv.GetID()))
    return out


def _render_one(invoice, book, fmt, xslt_path, company_info):
    """Return the rendered output bytes (pdf) or string (html/plaintext)
    for a single invoice."""
    if fmt == 'plaintext':
        return render_to_plaintext(invoice, book, company_info=company_info)
    if fmt == 'html':
        return render_to_html(invoice, book, xslt_path,
                              company_info=company_info)
    if fmt == 'pdf':
        # PDF combining is done at the dispatcher level via the HTML
        # fragments; this helper only produces per-invoice HTML.
        return render_to_html(invoice, book, xslt_path,
                              company_info=company_info)
    raise click.UsageError(f'Unknown format: {fmt!r}')


def _write_combined(invoices, book, fmt, xslt_path, company_info, output):
    """Write all rendered invoices into a single file (or stdout)."""
    if output == '-':
        if fmt != 'plaintext':
            raise click.UsageError(
                '--output - (stdout) is only supported for --format plaintext '
                '(pdf is binary; html is interactive)'
            )
        parts = [
            render_to_plaintext(inv, book, company_info=company_info)
            for inv in invoices
        ]
        sys.stdout.write('\n'.join(parts))
        return

    output_path = Path(output)
    if fmt == 'plaintext':
        parts = [
            render_to_plaintext(inv, book, company_info=company_info)
            for inv in invoices
        ]
        output_path.write_text('\n'.join(parts))
        return

    if fmt == 'html':
        fragments = [
            render_to_html(inv, book, xslt_path, company_info=company_info)
            for inv in invoices
        ]
        # Wrap each in <section> with a page-break so users who print the
        # combined HTML get the same separation a multi-page PDF would
        # show. Strip the surrounding <html><body> from each fragment so
        # the combined doc has just one outer shell.
        shell_parts = []
        for frag in fragments:
            inner = frag
            for tag in ('</body>', '</html>'):
                inner = inner.replace(tag, '')
            inner = inner.replace('<html>', '').replace('<body>', '')
            shell_parts.append(
                f'<section style="page-break-after: always;">{inner}</section>'
            )
        combined = '<html><body>' + ''.join(shell_parts) + '</body></html>'
        output_path.write_text(combined)
        return

    if fmt == 'pdf':
        import weasyprint
        fragments = [
            render_to_html(inv, book, xslt_path, company_info=company_info)
            for inv in invoices
        ]
        # Concatenate HTML fragments with explicit page break so each
        # invoice starts on a fresh page in the combined PDF.
        shell_parts = []
        for frag in fragments:
            inner = frag
            for tag in ('</body>', '</html>'):
                inner = inner.replace(tag, '')
            inner = inner.replace('<html>', '').replace('<body>', '')
            shell_parts.append(
                f'<section style="page-break-after: always;">{inner}</section>'
            )
        combined_html = (
            '<html><body>' + ''.join(shell_parts) + '</body></html>'
        )
        weasyprint.HTML(string=combined_html).write_pdf(str(output_path))
        return

    raise click.UsageError(f'Unknown format: {fmt!r}')


def _write_per_invoice(invoices, book, fmt, xslt_path, company_info, outdir):
    """Write one file per invoice into the directory `outdir`."""
    outdir = Path(outdir.rstrip('/'))
    outdir.mkdir(parents=True, exist_ok=True)
    ext = {'plaintext': 'txt', 'html': 'html', 'pdf': 'pdf'}[fmt]
    for inv in invoices:
        target = outdir / f'{inv.GetID()}.{ext}'
        if fmt == 'plaintext':
            target.write_text(
                render_to_plaintext(inv, book, company_info=company_info)
            )
        elif fmt == 'html':
            target.write_text(
                render_to_html(inv, book, xslt_path,
                               company_info=company_info)
            )
        elif fmt == 'pdf':
            import weasyprint
            html = render_to_html(inv, book, xslt_path,
                                  company_info=company_info)
            weasyprint.HTML(string=html).write_pdf(str(target))


@click.command()
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('invoice_selectors', nargs=-1)
@click.option("--invoice-id", default=None,
              help="Single invoice ID (back-compat alias for a positional ID).")
@click.option("--from", "from_date", default=None,
              help="Include invoices opened on or after this date (YYYY-MM-DD).")
@click.option("--to", "to_date", default=None,
              help="Include invoices opened on or before this date (YYYY-MM-DD).")
@click.option("--customer", default=None,
              help="Filter by customer ID.")
@click.option("--format", "fmt", default='pdf',
              type=click.Choice(['pdf', 'html', 'plaintext']),
              help="Output format. plaintext uses the canonical plaintext "
                   "syntax populated with informational totals (Q-017).")
@click.option("-o", "--output", required=True,
              help="Output file path, directory (trailing /), or '-' for "
                   "stdout (plaintext only).")
@click.option("--template", "template_path", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help=("Path to a custom XSLT template (Q-011). The XML schema "
                    "the template receives is documented at the top of "
                    "services/invoice.xslt. Defaults to the embedded "
                    "template."))
def print_invoice(gnucash_file, invoice_selectors, invoice_id,
                  from_date, to_date, customer, fmt, output, template_path):
    """Prints one or more GnuCash invoices.

    Examples:

        # single invoice → PDF (back-compat)
        print-invoice book.gnucash --invoice-id INV-001 -o out.pdf

        # multiple invoices, combined PDF
        print-invoice book.gnucash INV-001 INV-002 INV-003 -o combined.pdf

        # Q1 invoices, one PDF per file
        print-invoice book.gnucash --from 2026-01-01 --to 2026-03-31 \\
            --format pdf -o q1/

        # plaintext stream of a customer's invoices, stdout
        print-invoice book.gnucash --customer C-001 --format plaintext -o -
    """
    company_info = read_book_company_info(gnucash_file)

    selectors = list(invoice_selectors)
    if invoice_id:
        selectors.append(invoice_id)

    # Require explicit selection. Rendering "all invoices in the book"
    # by accident would be expensive and rarely intended — users who
    # really want everything can pass a wildcard (`'*'`) or a wide
    # `--from`/`--to` range.
    if not selectors and not from_date and not to_date and not customer:
        raise click.UsageError(
            'specify at least one invoice: positional ID (e.g. INV-001), '
            'glob (e.g. \'INV-2026-*\'), --from/--to date range, '
            '--customer, or --invoice-id'
        )

    repo = GnuCashRepository(gnucash_file)
    repo.open(SessionMode.READ_ONLY)
    book = repo.book

    try:
        all_inv = _all_invoices(book)
        selected = _filter_invoices(all_inv, selectors, from_date, to_date,
                                    customer)
        if not selected:
            criteria = []
            if selectors:
                criteria.append(f'selectors={selectors!r}')
            if from_date:
                criteria.append(f'from={from_date!r}')
            if to_date:
                criteria.append(f'to={to_date!r}')
            if customer:
                criteria.append(f'customer={customer!r}')
            raise click.UsageError(
                'no invoices matched the selection ('
                + ', '.join(criteria) if criteria else 'no selectors given'
                + ')'
            )

        xslt = template_path if template_path else str(_XSLT_PATH)
        if output.endswith('/'):
            _write_per_invoice(selected, book, fmt, xslt, company_info,
                               output)
            click.echo(
                f'✓ Wrote {len(selected)} invoice(s) to {output}'
            )
        else:
            _write_combined(selected, book, fmt, xslt, company_info, output)
            if output != '-':
                click.echo(
                    f'✓ Wrote {len(selected)} invoice(s) to {output}'
                )

    finally:
        repo.close()
