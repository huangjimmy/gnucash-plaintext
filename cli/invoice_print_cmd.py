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
from gnucash import Query

from cli._warnings import said_once
from infrastructure.gnucash.utils import wrap_invoice_or_bill
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.document_pages import combine_pages, load_weasyprint
from services.invoice_renderer import (
    read_book_company_info,
    render_to_html,
    render_to_plaintext,
)
from use_cases.export_transactions import UnwritableFigureError


def _all_invoices(book):
    q = Query()
    q.search_for('gncInvoice')
    q.set_book(book)
    results = []
    for r in q.run():
        inv = wrap_invoice_or_bill(r)
        # Customer invoices only (skip vendor bills). Asked of every document
        # in the book, vendor bills included: `GetCustomer()` answers None for
        # one rather than raising, on all ten supported builds — measured, and
        # the reason the `except Exception` that used to wrap this is gone. It
        # could not be reached to be right or wrong, and a bare `except` over
        # a call whose failure would mean the book cannot be read is one that
        # would have quietly dropped documents instead.
        cust = inv.GetOwner().GetCustomer()
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


def _write_combined(invoices, book, fmt, company_info, output, session=None,
                    report=None, report_file=None):
    """Write all rendered invoices into a single file (or stdout).

    `session` is the open session for `book`: GnuCash's own report resolves a
    document from its guid against the *current* book, so the renderer has to
    be told which session that is. `report` and `report_file` choose which
    GnuCash report draws the page.
    """
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
        # Through the byte stream, encoded here: `sys.stdout` takes its
        # encoding from the locale like every other text handle, so
        # `-o -` and `-o file.txt` would write the same document differently —
        # and `-o -` is the form the README pipes back into `import`.
        sys.stdout.buffer.write('\n'.join(parts).encode('utf-8'))
        return

    output_path = Path(output)
    if fmt == 'plaintext':
        parts = [
            render_to_plaintext(inv, book, company_info=company_info)
            for inv in invoices
        ]
        # UTF-8 stated, not taken from the locale: a customer's name is not
        # ASCII in general, and `write_text` without it either raises after
        # having already truncated the destination to nothing, or writes
        # Latin-1 bytes into a file whose own `<meta charset>` says UTF-8.
        output_path.write_text('\n'.join(parts), encoding='utf-8')
        return

    warn = said_once()          # one sink for the run, not one per document
    combined = combine_pages(
        render_to_html(inv, session, report=report, report_file=report_file,
                       warn=warn)
        for inv in invoices
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


def _write_per_invoice(invoices, book, fmt, company_info, outdir, session=None,
                       report=None, report_file=None):
    """Write one file per invoice into the directory `outdir`.

    Every invoice is rendered before any file is written, and the directory is
    made only once there is something to put in it. A printed `payment:` block
    states its amount at the unit its account is kept to and refuses a figure
    the currency cannot hold, so rendering can stop partway through a run —
    and writing inside the loop left the documents before the offender on disk
    and the ones after it missing, with nothing on the directory saying which.
    `export` renders in full for the same reason; the combined form below
    already did.
    """
    ext = {'plaintext': 'txt', 'html': 'html', 'pdf': 'pdf'}[fmt]
    warn = said_once()          # one sink for the run, not one per document
    rendered = [
        (f'{inv.GetID()}.{ext}',
         render_to_plaintext(inv, book, company_info=company_info)
         if fmt == 'plaintext'
         else render_to_html(inv, session, report=report,
                             report_file=report_file, warn=warn))
        for inv in invoices
    ]
    # A PDF is laid out before any of them is written too, not only the HTML
    # it is laid out from. Written as each one finished, a document weasyprint
    # cannot lay out — a font it cannot find, an image it cannot read — left
    # the directory partial in exactly the way rendering first was meant to
    # stop, from the other half of the same loop.
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
def print_invoice(gnucash_file, invoice_selectors, invoice_id,
                  from_date, to_date, customer, fmt, output, report,
                  report_file):
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
    # Refused rather than ignored. `--format plaintext` is this project's own
    # render of the canonical syntax and no GnuCash report is involved in it,
    # so a run naming a report would quietly produce a document the reader did
    # not ask for — and `-o -` is plaintext by definition, which is where it
    # would be least visible.
    if fmt == 'plaintext' and (report or report_file):
        raise click.UsageError(
            '--report and --report-file choose which GnuCash report draws the '
            'page, and --format plaintext draws no page: it writes the '
            'canonical plaintext syntax. Use --format pdf or --format html.')

    # And a `.scm` nothing then names is the same silence: loading a file
    # registers a report, it does not choose one, so this would have printed
    # the stock page, exited 0 and said `✓ Wrote 1 invoice(s)` — with the
    # reader's own report loaded and unused, and nothing saying so. The two
    # flags are one instruction in two halves.
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
                + (', '.join(criteria) if criteria else 'no selectors given')
                + ')'
            )

        if output.endswith('/'):
            _write_per_invoice(selected, book, fmt, company_info, output,
                               session=repo.session, report=report,
                               report_file=report_file)
            click.echo(
                f'✓ Wrote {len(selected)} invoice(s) to {output}'
            )
        else:
            _write_combined(selected, book, fmt, company_info, output,
                            session=repo.session, report=report,
                            report_file=report_file)
            if output != '-':
                click.echo(
                    f'✓ Wrote {len(selected)} invoice(s) to {output}'
                )

    except UnwritableFigureError as exc:
        # As a sentence, not a traceback. A printed document carries the guids
        # that make it re-importable, so its payment amount is judged the way
        # the export's is — and a refusal the reader cannot read is a refusal
        # that tells them nothing about which figure to correct.
        raise click.ClickException(str(exc)) from exc
    finally:
        repo.close()
