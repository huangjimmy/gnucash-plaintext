#!/usr/bin/env python
"""
CLI command for printing GnuCash invoices to PDF.
"""

from pathlib import Path

import click
import gnucash.gnucash_business as gb
from gnucash import Query

from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.invoice_renderer import read_book_company_info, render_to_pdf

_XSLT_PATH = Path(__file__).parent.parent / "services" / "invoice.xslt"


@click.command()
@click.argument('gnucash_file', type=click.Path(exists=True))
@click.option("--invoice-id", required=True, help="ID of the invoice to print.")
@click.option("-o", "--output", required=True, type=click.Path(), help="Output PDF file path.")
def print_invoice(gnucash_file, invoice_id, output):
    """Prints a GnuCash invoice to a PDF file."""
    click.echo(f"Printing invoice {invoice_id} from {gnucash_file} to {output}...")

    repo = GnuCashRepository(gnucash_file)
    repo.open(SessionMode.READ_ONLY)
    book = repo.book

    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(book)
        invoice = next(
            (inv for r in q.run() for inv in [gb.Invoice(instance=r)] if inv.GetID() == invoice_id),
            None
        )
        q.destroy()

        if not invoice:
            raise click.UsageError(f"Invoice with ID '{invoice_id}' not found.")

        company_info = read_book_company_info(gnucash_file)

        render_to_pdf(invoice, book, str(_XSLT_PATH), output, company_info)

        click.echo(f"✓ Successfully printed invoice to {output}")

    finally:
        repo.close()
