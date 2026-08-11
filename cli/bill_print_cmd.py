#!/usr/bin/env python
"""
CLI command for printing GnuCash vendor bills.

Q-019: parallel to cli/invoice_print_cmd.py. A bill is an inbound
document (vendor → us), so the rendered output puts the vendor on the
"Bill From" side and our company on the "Bill To" side (driven from
the GnuCash book's Business → Company options).

Output formats: pdf, html, plaintext. The plaintext format reuses the
canonical bill block syntax (already understood by `import`) with
Q-017 bill_* informational totals.
"""

import fnmatch
import re
import sys
from datetime import datetime
from pathlib import Path

import click
from gnucash import Query

from infrastructure.gnucash.utils import wrap_invoice_or_bill
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.bill_renderer import (
    render_to_html,
    render_to_plaintext,
)
from services.invoice_renderer import read_book_company_info
from use_cases.export_transactions import UnwritableFigureError

_XSLT_PATH = Path(__file__).parent.parent / "services" / "bill.xslt"


def _all_bills(book):
    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    results = []
    for r in q.run():
        bill = wrap_invoice_or_bill(r)
        # Vendor bills only (skip customer invoices). Asked of every document
        # in the book, customer invoices included: `GetVendor()` answers None
        # for one rather than raising, on all ten supported builds — measured,
        # and the reason the `except Exception` that used to wrap this is gone.
        # It could not be reached to be right or wrong, and a bare `except`
        # over a call whose failure would mean the book cannot be read is one
        # that would have quietly dropped documents instead.
        vendor = bill.GetOwner().GetVendor()
        if vendor is not None:
            results.append(bill)
    q.destroy()
    return results


def _filter_bills(bills, selectors, from_date, to_date, vendor):
    """Apply selectors (AND-composed). `selectors` accepts exact bill
    IDs or glob patterns when they contain `*?[` characters."""
    out = bills

    if selectors:
        def _matches(bill):
            bid = bill.GetID()
            for sel in selectors:
                if any(c in sel for c in '*?['):
                    if fnmatch.fnmatch(bid, sel):
                        return True
                elif bid == sel:
                    return True
            return False
        out = [b for b in out if _matches(b)]

    if from_date:
        from_dt = datetime.strptime(from_date, '%Y-%m-%d').date()
        out = [b for b in out if b.GetDateOpened().date() >= from_dt]
    if to_date:
        to_dt = datetime.strptime(to_date, '%Y-%m-%d').date()
        out = [b for b in out if b.GetDateOpened().date() <= to_dt]

    if vendor:
        out = [b for b in out
               if b.GetOwner().GetVendor() is not None
               and b.GetOwner().GetVendor().GetID() == vendor]

    out.sort(key=lambda b: (b.GetDateOpened(), b.GetID()))
    return out


def _write_combined(bills, book, fmt, xslt_path, company_info, output):
    if output == '-':
        if fmt != 'plaintext':
            raise click.UsageError(
                '--output - (stdout) is only supported for --format plaintext '
                '(pdf is binary; html is interactive)'
            )
        parts = [
            render_to_plaintext(b, book, company_info=company_info)
            for b in bills
        ]
        sys.stdout.write('\n'.join(parts))
        return

    output_path = Path(output)
    if fmt == 'plaintext':
        parts = [
            render_to_plaintext(b, book, company_info=company_info)
            for b in bills
        ]
        output_path.write_text('\n'.join(parts))
        return

    if fmt == 'html':
        fragments = [
            render_to_html(b, book, xslt_path, company_info=company_info)
            for b in bills
        ]
        shell_parts = []
        for frag in fragments:
            inner = frag
            for tag in ('</body>', '</html>'):
                inner = inner.replace(tag, '')
            # The XSLT emits `<!DOCTYPE html PUBLIC …>` + `<html lang="en">`
            # per-fragment; literal `<html>` and absent DOCTYPE stripping
            # leaves nested DOCTYPEs and nested `<html>` in the combined
            # output (invalid both as HTML and XML). Strip all three so
            # the combined doc has exactly one outer shell.
            inner = re.sub(r'<!DOCTYPE[^>]*>', '', inner)
            inner = re.sub(r'<html\b[^>]*>', '', inner)
            inner = re.sub(r'<body\b[^>]*>', '', inner)
            shell_parts.append(
                f'<section style="page-break-after: always;">{inner}</section>'
            )
        combined = '<html><body>' + ''.join(shell_parts) + '</body></html>'
        output_path.write_text(combined)
        return

    # pdf, unconditionally: `--format` is a `click.Choice` of exactly three,
    # and the other two have returned above. Asking again would add a fourth
    # case nothing can take — and a fourth format added to the Choice would
    # silently fall through it, which is the failure a trailing `raise` was
    # meant to catch and could never reach.
    import weasyprint
    fragments = [
        render_to_html(b, book, xslt_path, company_info=company_info)
        for b in bills
    ]
    shell_parts = []
    for frag in fragments:
        inner = frag
        for tag in ('</body>', '</html>'):
            inner = inner.replace(tag, '')
        # The XSLT emits `<!DOCTYPE html PUBLIC …>` + `<html lang="en">`
        # per-fragment; literal `<html>` and absent DOCTYPE stripping
        # leaves nested DOCTYPEs and nested `<html>` in the combined
        # output (invalid both as HTML and XML). Strip all three so
        # the combined doc has exactly one outer shell.
        inner = re.sub(r'<!DOCTYPE[^>]*>', '', inner)
        inner = re.sub(r'<html\b[^>]*>', '', inner)
        inner = re.sub(r'<body\b[^>]*>', '', inner)
        shell_parts.append(
            f'<section style="page-break-after: always;">{inner}</section>'
        )
    combined_html = (
        '<html><body>' + ''.join(shell_parts) + '</body></html>'
    )
    weasyprint.HTML(string=combined_html).write_pdf(str(output_path))


def _write_per_bill(bills, book, fmt, xslt_path, company_info, outdir):
    """Write one file per bill into the directory `outdir`.

    Every bill is rendered before any file is written, and the directory is
    made only once there is something to put in it — see `_write_per_invoice`
    for what writing inside the loop cost when a payment figure was refused
    partway through.
    """
    ext = {'plaintext': 'txt', 'html': 'html', 'pdf': 'pdf'}[fmt]
    rendered = [
        (f'{b.GetID()}.{ext}',
         render_to_plaintext(b, book, company_info=company_info)
         if fmt == 'plaintext'
         else render_to_html(b, book, xslt_path, company_info=company_info))
        for b in bills
    ]
    # Laid out before any of them is written, PDFs included — see
    # `_write_per_invoice` for what writing them as they finished cost.
    if fmt == 'pdf':
        import weasyprint
        rendered = [(name, weasyprint.HTML(string=html).write_pdf())
                    for name, html in rendered]

    outdir = Path(outdir.rstrip('/'))
    outdir.mkdir(parents=True, exist_ok=True)
    for name, body in rendered:
        target = outdir / name
        if fmt == 'pdf':                # the third of three, see above
            target.write_bytes(body)
        else:
            target.write_text(body)


@click.command()
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.argument('bill_selectors', nargs=-1)
@click.option("--bill-id", default=None,
              help="Single bill ID (back-compat alias for a positional ID).")
@click.option("--from", "from_date", default=None,
              help="Include bills opened on or after this date (YYYY-MM-DD).")
@click.option("--to", "to_date", default=None,
              help="Include bills opened on or before this date (YYYY-MM-DD).")
@click.option("--vendor", default=None, help="Filter by vendor ID.")
@click.option("--format", "fmt", default='pdf',
              type=click.Choice(['pdf', 'html', 'plaintext']),
              help="Output format. plaintext uses the canonical bill block "
                   "syntax with Q-017 informational totals.")
@click.option("-o", "--output", required=True,
              help="Output file path, directory (trailing /), or '-' for "
                   "stdout (plaintext only).")
@click.option("--template", "template_path", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help=("Path to a custom XSLT template. Defaults to the "
                    "embedded services/bill.xslt."))
def print_bill(gnucash_file, bill_selectors, bill_id,
               from_date, to_date, vendor, fmt, output, template_path):
    """Prints one or more GnuCash vendor bills.

    Examples:

        # single bill → PDF
        print-bill book.gnucash --bill-id BILL-001 -o out.pdf

        # multiple bills, combined PDF
        print-bill book.gnucash BILL-001 BILL-002 -o combined.pdf

        # Q1 bills, one PDF per file
        print-bill book.gnucash --from 2026-01-01 --to 2026-03-31 \\
            --format pdf -o q1/

        # plaintext stream of one vendor's bills, stdout
        print-bill book.gnucash --vendor V-001 --format plaintext -o -
    """
    company_info = read_book_company_info(gnucash_file)

    selectors = list(bill_selectors)
    if bill_id:
        selectors.append(bill_id)

    if not selectors and not from_date and not to_date and not vendor:
        raise click.UsageError(
            'specify at least one bill: positional ID (e.g. BILL-001), '
            'glob (e.g. \'BILL-2026-*\'), --from/--to date range, '
            '--vendor, or --bill-id'
        )

    repo = GnuCashRepository(gnucash_file)
    repo.open(SessionMode.READ_ONLY)
    book = repo.book

    try:
        all_bills = _all_bills(book)
        selected = _filter_bills(all_bills, selectors, from_date, to_date,
                                 vendor)
        if not selected:
            criteria = []
            if selectors:
                criteria.append(f'selectors={selectors!r}')
            if from_date:
                criteria.append(f'from={from_date!r}')
            if to_date:
                criteria.append(f'to={to_date!r}')
            if vendor:
                criteria.append(f'vendor={vendor!r}')
            raise click.UsageError(
                'no bills matched the selection ('
                + (', '.join(criteria) if criteria else 'no selectors given')
                + ')'
            )

        xslt = template_path if template_path else str(_XSLT_PATH)
        if output.endswith('/'):
            _write_per_bill(selected, book, fmt, xslt, company_info, output)
            click.echo(f'✓ Wrote {len(selected)} bill(s) to {output}')
        else:
            _write_combined(selected, book, fmt, xslt, company_info, output)
            if output != '-':
                click.echo(f'✓ Wrote {len(selected)} bill(s) to {output}')

    except UnwritableFigureError as exc:
        # As the invoice printer does: a refusal the reader cannot read tells
        # them nothing about which figure to correct.
        raise click.ClickException(str(exc)) from exc
    finally:
        repo.close()
