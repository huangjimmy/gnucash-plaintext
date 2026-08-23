"""
Q-012: `print-invoice` on an unposted invoice no longer crashes.

Pre-Q-012, calling `print-invoice` on an invoice with `posted: none`
would hit `posting_txn.CountSplits()` on a None object and crash. Real
user incident: their frontend asked the API to render a draft invoice
and got a 500 with a NoneType AttributeError.

An unposted invoice reaches GnuCash's own Printable Invoice like any
other, and GnuCash prices it from its entries and marks it "Invoice in
progress...". No status is decided here and no badge is drawn here; what
this pins is that the invoice is rendered rather than dropped, and that
what the page says about it is what the entries say.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import wrap_invoice_or_bill
from tests.integration.rendered_page import is_in_progress

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


_ACCOUNTS = """
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
"""


def _fixture(name: str) -> str:
    """Load a `tests/fixtures/<name>.txt` file as a string."""
    return (_FIXTURES / f"{name}.txt").read_text()


def _write(path: Path, text: str) -> str:
    path.write_text(text)
    return str(path)


def _import_new(runner, gnc, fixture):
    return runner.invoke(cli, ["import", "--new", str(gnc), fixture,
                               "--include-business-objects"])


def _render_invoice_html(gnc_path: str, invoice_id: str) -> str:
    """The page GnuCash draws — the same path `print-invoice` takes,
    minus the WebKit step that lays it out."""
    from gnucash import Query, Session
    from gnucash.gnucash_business import Invoice

    from services.invoice_renderer import render_to_html

    ses = Session(f"xml://{gnc_path}")
    try:
        book = ses.book
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(book)
        inv = next(
            (i for r in q.run() for i in [wrap_invoice_or_bill(r)] if i.GetID() == invoice_id),
            None,
        )
        q.destroy()
        assert inv is not None, f"Invoice {invoice_id!r} not found"
        return render_to_html(inv, ses)
    finally:
        ses.end()


@pytest.fixture
def gnc_with_draft_invoice(tmp_path):
    runner = CliRunner()
    gnc = tmp_path / "book.gnucash"
    fixture = _ACCOUNTS + _fixture("q012_invoice_unposted_draft")
    r = _import_new(runner, gnc, _write(tmp_path / "in.txt", fixture))
    assert r.exit_code == 0, r.output
    return str(gnc)


class TestPrintInvoiceOnUnpostedNoLongerCrashes:
    """The original bug: 500 with `'NoneType' object has no attribute
    'CountSplits'`. After Q-012 the renderer must succeed and produce
    a PDF."""

    def test_print_unposted_invoice_succeeds(self, gnc_with_draft_invoice, tmp_path):
        pdf = tmp_path / "draft.pdf"
        runner = CliRunner()
        r = runner.invoke(cli, [
            "print-invoice", gnc_with_draft_invoice,
            "--invoice-id", "INV-DRAFT-001",
            "-o", str(pdf),
        ])
        assert r.exit_code == 0, (
            f"print-invoice on an unposted invoice must not crash. Got:\n"
            f"{r.output}"
        )
        assert pdf.exists() and pdf.stat().st_size > 0


class TestRenderedDraftInvoice:
    """The page GnuCash draws for an unposted invoice: priced from its
    entries, marked as in progress, and carrying no payments."""

    def test_it_is_marked_as_not_yet_posted(self, gnc_with_draft_invoice):
        html = _render_invoice_html(gnc_with_draft_invoice, "INV-DRAFT-001")
        assert is_in_progress(html), (
            f"An unposted invoice is drawn as in progress.\nHTML:\n{html}"
        )

    def test_entry_rows_present(self, gnc_with_draft_invoice):
        html = _render_invoice_html(gnc_with_draft_invoice, "INV-DRAFT-001")
        # Both entries should appear in the line-items table.
        assert '>Goods<' in html, html
        assert '>Sales<' in html, html

    def test_the_total_is_the_sum_of_the_entry_amounts(self,
                                                       gnc_with_draft_invoice):
        """Priced from the entries: 100 x $15 + 5 x $20 = $1,600.00."""
        html = _render_invoice_html(gnc_with_draft_invoice, "INV-DRAFT-001")
        assert '>C$1,600.00<' in html, (
            f"An unposted invoice is priced from its entries.\nHTML:\n{html}"
        )

    def test_nothing_has_been_paid_on_it(self, gnc_with_draft_invoice):
        """An invoice that is not posted cannot have been paid, so the whole
        of it is still due and no payment row is drawn."""
        html = _render_invoice_html(gnc_with_draft_invoice, "INV-DRAFT-001")
        assert 'Payment' not in html, html


class TestPostedInvoicesStillWork:
    """Regression guard: a posted invoice is still drawn, with what it is
    for and what is still owed on it."""

    def test_posted_invoice_renders_as_owed_in_full(self, tmp_path):
        runner = CliRunner()
        gnc = tmp_path / "book.gnucash"
        fixture = _ACCOUNTS + _fixture("q012_invoice_posted_simple")
        r = _import_new(runner, gnc, _write(tmp_path / "in.txt", fixture))
        assert r.exit_code == 0, r.output

        html = _render_invoice_html(str(gnc), "INV-POSTED-001")
        assert '<div class="invoice-title">Invoice #INV-POSTED-001</div>' \
            in html, html
        assert not is_in_progress(html), html
        assert '>Amount Due</td>' in html, html
