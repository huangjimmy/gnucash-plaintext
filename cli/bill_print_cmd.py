#!/usr/bin/env python
"""
CLI command for printing GnuCash vendor bills.

Q-019: parallel to cli/invoice_print_cmd.py. A bill is a vendor's invoice —
one `gncInvoice` type and one GnuCash report — so the page is
drawn exactly as an invoice's is, with the vendor as the document's owner.

Output formats: pdf, html, plaintext. The plaintext format reuses the
canonical bill block syntax (already understood by `import`) with
Q-017 bill_* informational totals.
"""

import fnmatch
import sys
from datetime import datetime
from pathlib import Path

import click
from gnucash import Query

from cli._document_files import file_names
from cli._warnings import said_once
from infrastructure.gnucash.utils import wrap_invoice_or_bill
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.bill_renderer import (
    render_to_html,
    render_to_plaintext,
)
from services.document_pages import combine_pages, load_weasyprint
from services.gnucash_importer import _swig_invoice_guid_str
from services.invoice_renderer import read_book_company_info
from use_cases.export_transactions import UnwritableFigureError


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


def _write_combined(bills, book, fmt, company_info, output, session=None,
                    report=None, report_file=None):
    """Write all rendered bills into a single file (or stdout).

    `session` is the open session for `book` — see
    `invoice_print_cmd._write_combined`.
    """
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
        # Encoded here rather than by the locale — see
        # `invoice_print_cmd._write_combined`.
        sys.stdout.buffer.write('\n'.join(parts).encode('utf-8'))
        return

    output_path = Path(output)
    if fmt == 'plaintext':
        parts = [
            render_to_plaintext(b, book, company_info=company_info)
            for b in bills
        ]
        # UTF-8 stated — see `invoice_print_cmd._write_combined` for what the
        # locale's answer costs on a document whose owner is not named in
        # ASCII.
        output_path.write_text('\n'.join(parts), encoding='utf-8')
        return

    warn = said_once()          # one sink for the run — see there
    combined = combine_pages(
        render_to_html(b, session, report=report, report_file=report_file,
                       warn=warn)
        for b in bills
    )
    if fmt == 'html':
        output_path.write_text(combined, encoding='utf-8')
        return

    # pdf, unconditionally: `--format` is a `click.Choice` of exactly three,
    # and the other two have returned above. Asking again would add a fourth
    # case nothing can take — and a fourth format added to the Choice would
    # silently fall through it, which is the failure a trailing `raise` was
    # meant to catch and could never reach.
    weasyprint = load_weasyprint()

    weasyprint.HTML(string=combined).write_pdf(str(output_path))


def _write_per_bill(bills, book, fmt, company_info, outdir, session=None,
                    report=None, report_file=None):
    """Write one file per bill into the directory `outdir`.

    Every bill is rendered before any file is written, and the directory is
    made only once there is something to put in it — see `_write_per_invoice`
    for what writing inside the loop cost when a payment figure was refused
    partway through.
    """
    ext = {'plaintext': 'txt', 'html': 'html', 'pdf': 'pdf'}[fmt]
    warn = said_once()          # one sink for the run — see there
    # Named before rendering — see `invoice_print_cmd._write_per_invoice`.
    rendered = [
        (name,
         render_to_plaintext(b, book, company_info=company_info)
         if fmt == 'plaintext'
         else render_to_html(b, session, report=report,
                             report_file=report_file, warn=warn))
        for name, b in file_names(bills, ext, _swig_invoice_guid_str)
    ]
    # Laid out before any of them is written, PDFs included — see
    # `_write_per_invoice` for what writing them as they finished cost.
    if fmt == 'pdf':
        weasyprint = load_weasyprint()
        rendered = [(name, weasyprint.HTML(string=html).write_pdf())
                    for name, html in rendered]

    outdir = Path(outdir.rstrip('/'))
    outdir.mkdir(parents=True, exist_ok=True)
    for name, body in rendered:
        target = outdir / name
        if fmt == 'pdf':                # the third of three, see above
            target.write_bytes(body)
        else:
            target.write_text(body, encoding='utf-8')   # see _write_combined


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
@click.option("--report", default=None,
              help="Which GnuCash report draws the page — its English name "
                   "(e.g. 'Fancy Invoice') or its template guid. Names are "
                   "matched as the report registers them, which is English "
                   "on every build; a localized GnuCash shows you the "
                   "translated name, so use the guid there. Defaults to "
                   "'Printable Invoice', the one GnuCash's own File → Print "
                   "Invoice uses.")
@click.option("--report-file", "report_file", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="A Scheme (.scm) file to load before the report is looked "
                   "up, so a report of your own — `gnc:define-report` — can "
                   "be named with --report. This is GnuCash's own extension "
                   "point: your report is written the way its own are.")
def print_bill(gnucash_file, bill_selectors, bill_id,
               from_date, to_date, vendor, fmt, output, report, report_file):
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
    # Refused rather than ignored — see `invoice_print_cmd.print_invoice`.
    if fmt == 'plaintext' and (report or report_file):
        raise click.UsageError(
            '--report and --report-file choose which GnuCash report draws the '
            'page, and --format plaintext draws no page: it writes the '
            'canonical plaintext syntax. Use --format pdf or --format html.')

    # Likewise a `.scm` nothing names — see there.
    if report_file and not report:
        raise click.UsageError(
            '--report-file loads a report so --report can name it, and on its '
            'own it would load yours and still draw GnuCash\'s. Add --report '
            '"<the name your .scm passes to gnc:define-report>" (or its '
            'guid).')

    # Only the plaintext render writes a seller header from it, and reading it
    # decompresses and parses the whole book file — a cost the default format
    # has no use for, because GnuCash's report reads the book's options itself.
    company_info = (read_book_company_info(gnucash_file)
                    if fmt == 'plaintext' else None)

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

        if output.endswith('/'):
            _write_per_bill(selected, book, fmt, company_info, output,
                            session=repo.session, report=report,
                            report_file=report_file)
            click.echo(f'✓ Wrote {len(selected)} bill(s) to {output}')
        else:
            _write_combined(selected, book, fmt, company_info, output,
                            session=repo.session, report=report,
                            report_file=report_file)
            if output != '-':
                click.echo(f'✓ Wrote {len(selected)} bill(s) to {output}')

    except UnwritableFigureError as exc:
        # As the invoice printer does: a refusal the reader cannot read tells
        # them nothing about which figure to correct.
        raise click.ClickException(str(exc)) from exc
    finally:
        repo.close()
