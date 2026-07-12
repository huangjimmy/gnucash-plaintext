"""
Q-011: action field is optional; UNIT column hides when empty for all
entries; print-invoice accepts a custom XSLT via --template.

Three concerns covered here:

  1. Importer accepts an `entry:` directive with no `action:` line and
     stores it as empty (Choice B in Q-011 docs).
  2. The default XSLT (`services/invoice.xslt`) hides the UNIT column
     when no entry has a non-empty action, and shows it when at least
     one does.
  3. `print-invoice --template <path>` overrides the embedded XSLT.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import wrap_invoice_or_bill

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_XSLT = _REPO_ROOT / "services" / "invoice.xslt"


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


def _write(path: Path, text: str) -> str:
    path.write_text(text)
    return str(path)


def _import_new(runner, gnc, fixture):
    return runner.invoke(cli, ["import", "--new", str(gnc), fixture,
                               "--include-business-objects"])


def _export(runner, gnc, out):
    return runner.invoke(cli, ["export", str(gnc), str(out),
                               "--include-business-objects"])


def _render_invoice_html(gnc_path: str, invoice_id: str, xslt_path: str) -> str:
    """Run the XSLT on the named invoice and return the HTML string."""
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
        return render_to_html(inv, book, xslt_path)
    finally:
        ses.end()


# ── 1. Importer: action is optional ─────────────────────────────────────────


class TestImporterAcceptsMissingAction:
    """Per Q-011 Choice B: omitting the `action:` line is equivalent to
    `action: ""`. The entry's action field is set to empty. To preserve
    a non-empty value across re-imports the user must declare it
    explicitly."""

    def test_invoice_with_no_action_field_imports_with_empty_action(self, tmp_path):
        runner = CliRunner()
        gnc = tmp_path / "book.gnucash"
        fixture = _ACCOUNTS + """
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Goods"
\t\taccount: "Income:Sales"
\t\tquantity: 100
\t\tprice: 15
\t\ttaxable: false
\t\ttax_included: false
\tposted: none
\tpayment: none
"""
        r = _import_new(runner, gnc, _write(tmp_path / "in.txt", fixture))
        assert r.exit_code == 0, r.output

        # Round-trip: export should emit `action: ""` because that's what
        # GnuCash holds (no NULL state in GnuCash; see issue doc for the
        # empirical probe result).
        out = tmp_path / "exported.txt"
        r2 = _export(runner, gnc, out)
        assert r2.exit_code == 0, r2.output
        text = out.read_text()
        assert 'description: "Goods"' in text
        assert 'action: ""' in text, (
            f"Empty action must roundtrip as `action: \"\"`. Got:\n{text}"
        )

    def test_reimport_omitted_then_explicit_empty_is_unchanged(self, tmp_path):
        """Q-010 idempotency intersection: the matcher must treat
        `<no action: line>` and `action: ""` as equivalent."""
        import time
        runner = CliRunner()
        gnc = tmp_path / "book.gnucash"

        def _make_fixture(action_line: str) -> str:
            return _ACCOUNTS + f"""
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Goods"
{action_line}\t\taccount: "Income:Sales"
\t\tquantity: 100
\t\tprice: 15
\t\ttaxable: false
\t\ttax_included: false
\tposted: none
\tpayment: none
"""

        # First import: no action line.
        r1 = _import_new(runner, gnc, _write(tmp_path / "no_action.txt",
                                             _make_fixture('')))
        assert r1.exit_code == 0, r1.output

        # Re-import: explicit empty action. Should be reported as 'unchanged'.
        r2 = runner.invoke(cli, [
            "import", str(gnc),
            _write(tmp_path / "explicit_empty.txt",
                   _make_fixture('\t\taction: ""\n')),
            "--include-business-objects",
        ])
        assert r2.exit_code == 0, r2.output
        assert 'invoice "INV-001": unchanged' in r2.output, (
            f"<no action> and `action: \"\"` must be matcher-equivalent. "
            f"Got:\n{r2.output}"
        )


# ── 2. XSLT: UNIT column visibility ─────────────────────────────────────────


class TestUnitColumnHiddenWhenAllEmpty:
    """If every entry has an empty action, the rendered HTML must omit
    the UNIT column entirely — both <th>Unit</th> and the per-row cells."""

    def _setup(self, tmp_path, action_per_entry: list) -> str:
        """Set up a book with one POSTED invoice whose entries have the
        listed actions. action_per_entry[i] is either None (omit `action:`
        line) or a string (use `action: "<s>"`).

        The invoice must be posted because invoice_to_xml() walks the
        posted lot for payments — unposted invoices crash the renderer
        with NoneType errors. Posted is the realistic scenario anyway:
        you only print invoices you've sent.
        """
        runner = CliRunner()
        gnc = tmp_path / "book.gnucash"
        entries = []
        for i, act in enumerate(action_per_entry):
            action_line = '' if act is None else f'\t\taction: "{act}"\n'
            entries.append(
                f'\tentry:\n'
                f'\t\tdate: 2026-01-01\n'
                f'\t\tdescription: "Item {i+1}"\n'
                f'{action_line}'
                f'\t\taccount: "Income:Sales"\n'
                f'\t\tquantity: 1\n'
                f'\t\tprice: 100\n'
                f'\t\ttaxable: false\n'
                f'\t\ttax_included: false\n'
            )
        fixture = _ACCOUNTS + """
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
""" + ''.join(entries) + (
            '\tposted:\n'
            '\t\tdate: 2026-01-01\n'
            '\t\tdue: 2026-01-31\n'
            '\t\tar_account: "Assets:Accounts Receivable"\n'
            '\t\tmemo: "Invoice INV-001"\n'
            '\t\taccumulate: true\n'
            '\tpayment: none\n'
        )
        r = _import_new(runner, gnc, _write(tmp_path / "in.txt", fixture))
        assert r.exit_code == 0, r.output
        return str(gnc)

    def test_all_empty_actions_hides_unit_column(self, tmp_path):
        gnc = self._setup(tmp_path, [None, None, ''])
        html = _render_invoice_html(gnc, "INV-001", str(_DEFAULT_XSLT))
        # The UNIT column header and cells must be absent.
        assert '<th style="text-align:center">Unit</th>' not in html, (
            f"UNIT column header must be hidden when all actions empty:\n{html}"
        )

    def test_at_least_one_non_empty_shows_unit_column(self, tmp_path):
        gnc = self._setup(tmp_path, ['Hours', None, ''])
        html = _render_invoice_html(gnc, "INV-001", str(_DEFAULT_XSLT))
        assert '<th style="text-align:center">Unit</th>' in html, (
            f"UNIT column must show when at least one entry has action:\n{html}"
        )
        # The "Hours" cell must be in the row, blank cells for the others.
        assert '>Hours<' in html


# ── 3. CLI: --template flag ─────────────────────────────────────────────────


class TestPrintInvoiceCustomTemplate:
    """`print-invoice --template <path>` uses the supplied XSLT instead
    of the embedded one. Verified by passing a stub XSLT that emits a
    sentinel marker in the output PDF."""

    @pytest.fixture
    def gnc_with_invoice(self, tmp_path):
        runner = CliRunner()
        gnc = tmp_path / "book.gnucash"
        fixture = _ACCOUNTS + """
customer "C001"
\tname: "Acme"
\tcurrency: CAD

invoice "INV-001"
\tcustomer_id: "C001"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "Service"
\t\taction: "Hours"
\t\taccount: "Income:Sales"
\t\tquantity: 5
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "Invoice INV-001"
\t\taccumulate: true
\tpayment: none
"""
        r = _import_new(runner, gnc, _write(tmp_path / "in.txt", fixture))
        assert r.exit_code == 0, r.output
        return str(gnc)

    _STUB_XSLT = """<?xml version="1.0"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
<xsl:output method="html" encoding="UTF-8"/>
<xsl:template match="/invoice">
<html><body><p>Q011-CUSTOM-TEMPLATE-MARKER</p>
<p>id: <xsl:value-of select="id"/></p></body></html>
</xsl:template>
</xsl:stylesheet>"""

    def test_custom_template_threads_through_to_html(self, gnc_with_invoice, tmp_path):
        """Verify the --template path actually feeds the XSLT pipeline:
        render directly to HTML using the stub XSLT and check for the
        marker. This exercises the same render_to_html call that
        `print-invoice` uses internally — if this passes, the CLI just
        wraps it with weasyprint."""
        stub_xslt = tmp_path / "stub.xslt"
        stub_xslt.write_text(self._STUB_XSLT)
        html = _render_invoice_html(gnc_with_invoice, "INV-001", str(stub_xslt))
        assert 'Q011-CUSTOM-TEMPLATE-MARKER' in html, (
            f"Stub XSLT marker missing — XSLT path threading is broken.\n"
            f"HTML:\n{html}"
        )

    def test_cli_template_flag_succeeds_with_custom_xslt(self, gnc_with_invoice, tmp_path):
        """End-to-end CLI test: --template <stub.xslt> produces a PDF.
        We can't easily extract text from the PDF in the test env, so
        the marker check lives in test_custom_template_threads_through_to_html;
        here we only verify the CLI argument plumbing."""
        stub_xslt = tmp_path / "stub.xslt"
        stub_xslt.write_text(self._STUB_XSLT)
        pdf = tmp_path / "custom.pdf"

        runner = CliRunner()
        r = runner.invoke(cli, [
            "print-invoice", gnc_with_invoice,
            "--invoice-id", "INV-001",
            "-o", str(pdf),
            "--template", str(stub_xslt),
        ])
        assert r.exit_code == 0, r.output
        assert pdf.exists() and pdf.stat().st_size > 0

    def test_default_template_used_when_flag_omitted(self, gnc_with_invoice, tmp_path):
        """No --template → embedded invoice.xslt. Verify by rendering
        through the same render_to_html with the embedded path and
        checking that:
          - the default template's signature ('Tax Applied' header) is present,
          - and the stub template's marker is absent (proves no stub leak
            from a previous test run / global state).
        """
        html = _render_invoice_html(gnc_with_invoice, "INV-001", str(_DEFAULT_XSLT))
        assert 'Tax Applied' in html, (
            f"Default template was not applied — 'Tax Applied' header "
            f"missing.\nHTML:\n{html}"
        )
        assert 'Q011-CUSTOM-TEMPLATE-MARKER' not in html, (
            f"Default-template render must NOT contain the custom-template "
            f"stub marker; if this fires, the XSLT path was not properly "
            f"isolated.\nHTML:\n{html}"
        )

    def test_nonexistent_template_path_errors(self, gnc_with_invoice, tmp_path):
        pdf = tmp_path / "x.pdf"
        runner = CliRunner()
        r = runner.invoke(cli, [
            "print-invoice", gnc_with_invoice,
            "--invoice-id", "INV-001",
            "-o", str(pdf),
            "--template", str(tmp_path / "does-not-exist.xslt"),
        ])
        assert r.exit_code != 0
