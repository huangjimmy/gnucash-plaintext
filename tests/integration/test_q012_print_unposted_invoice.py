"""
Q-012: `print-invoice` on an unposted invoice no longer crashes.

Pre-Q-012, calling `print-invoice` on an invoice with `posted: none`
would hit `posting_txn.CountSplits()` on a None object and crash. Real
user incident: their frontend asked the API to render a draft invoice
and got a 500 with a NoneType AttributeError.

Q-012 makes the renderer treat unposted invoices as drafts:
  - Status attribute = 'draft' (vs 'paid' / 'unpaid' for posted)
  - Subtotal computed from entries directly (qty * price)
  - No tax-line breakdown (would require pre-post tax computation per
    entry; deferred — see issue Q-012)
  - No payment-history table (drafts can't have payments)
  - No amount-remaining

The XSLT shows a DRAFT badge so the user knows the rendered total
doesn't include tax.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_XSLT = _REPO_ROOT / "services" / "invoice.xslt"
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
    """Render the named invoice through the embedded XSLT — same path
    print-invoice uses internally, minus the weasyprint PDF step."""
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
            (i for r in q.run() for i in [Invoice(instance=r)] if i.GetID() == invoice_id),
            None,
        )
        q.destroy()
        assert inv is not None, f"Invoice {invoice_id!r} not found"
        return render_to_html(inv, book, str(_DEFAULT_XSLT))
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
    """The HTML produced for a draft invoice must:
      - mark itself as a draft (status='draft' → DRAFT badge),
      - include all entry rows,
      - omit per-tax breakdown (drafts can't compute taxes pre-post),
      - omit the payment-history table (drafts have no payments)."""

    def test_draft_badge_present(self, gnc_with_draft_invoice):
        """Match the active <span> rather than the class name alone — the
        embedded XSLT defines `.badge-paid`/`.badge-unpaid`/`.badge-draft`
        in the <style> block, so all three substrings appear in every
        rendered HTML. The discriminator is which span is actually
        emitted."""
        html = _render_invoice_html(gnc_with_draft_invoice, "INV-DRAFT-001")
        assert '<span class="badge badge-draft">Draft</span>' in html, (
            f"Draft invoice must render a DRAFT badge span.\nHTML:\n{html}"
        )
        assert '<span class="badge badge-paid">' not in html
        assert '<span class="badge badge-unpaid">' not in html

    def test_entry_rows_present(self, gnc_with_draft_invoice):
        html = _render_invoice_html(gnc_with_draft_invoice, "INV-DRAFT-001")
        # Both entries should appear in the line-items table.
        assert '>Goods<' in html, html
        assert '>Sales<' in html, html

    def test_subtotal_matches_sum_of_entry_amounts(self, gnc_with_draft_invoice):
        """Q-012: drafts compute subtotal as sum of (qty * price). Our
        fixture: 100 * $15 + 5 * $20 = $1500 + $100 = $1600."""
        html = _render_invoice_html(gnc_with_draft_invoice, "INV-DRAFT-001")
        assert '1,600.00' in html, (
            f"Draft subtotal must equal sum of entry amounts ($1,600.00). "
            f"HTML:\n{html}"
        )

    def test_no_payment_history_section(self, gnc_with_draft_invoice):
        html = _render_invoice_html(gnc_with_draft_invoice, "INV-DRAFT-001")
        # Payment History header is conditional on payments existing.
        assert 'Payment History' not in html, (
            f"Draft invoice has no payments — Payment History section must "
            f"NOT render.\nHTML:\n{html}"
        )

    def test_no_amount_remaining(self, gnc_with_draft_invoice):
        """Amount Remaining is part of the payment-history table; absence
        of payments means no remaining row either."""
        html = _render_invoice_html(gnc_with_draft_invoice, "INV-DRAFT-001")
        assert 'Amount Remaining' not in html


class TestPostedInvoicesStillWork:
    """Regression guard: posted invoices must still render with their
    full tax breakdown and (if applicable) payment history. The fix
    branch in invoice_to_xml gates only on `posting_txn is None`, so
    posted invoices flow through the original code path unchanged."""

    def test_posted_invoice_renders_with_unpaid_badge(self, tmp_path):
        runner = CliRunner()
        gnc = tmp_path / "book.gnucash"
        fixture = _ACCOUNTS + _fixture("q012_invoice_posted_simple")
        r = _import_new(runner, gnc, _write(tmp_path / "in.txt", fixture))
        assert r.exit_code == 0, r.output

        html = _render_invoice_html(str(gnc), "INV-POSTED-001")
        assert '<span class="badge badge-unpaid">Unpaid</span>' in html, html
        assert '<span class="badge badge-draft">' not in html
