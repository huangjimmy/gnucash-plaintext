"""
Integration tests for the print-invoice CLI command.

Requires Docker (real GnuCash session + lxml/weasyprint).
Uses the business_objects.txt fixture which already contains posted invoices.
"""

import os

import pytest
from click.testing import CliRunner

from cli.main import cli


@pytest.fixture
def gnucash_with_invoice(tmp_path):
    """
    GnuCash file with a posted invoice (INV-2026-001).

    Imports from tests/fixtures/business_objects.txt which contains a full
    set of customers, vendors, and invoices including INV-2026-001 (posted,
    unpaid) suitable for PDF rendering tests.
    """
    gnucash_file = tmp_path / "invoices.gnucash"
    input_file = "tests/fixtures/business_objects.txt"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "import", "--new", str(gnucash_file), input_file,
        "--include-business-objects",
    ])
    assert result.exit_code == 0, f"Fixture import failed:\n{result.output}"
    return str(gnucash_file)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------

class TestPrintInvoiceSuccess:

    def test_prints_posted_invoice_to_pdf(self, gnucash_with_invoice, tmp_path):
        """A valid posted invoice ID produces a non-empty PDF file."""
        pdf_file = tmp_path / "invoice.pdf"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "print-invoice", gnucash_with_invoice,
            "--invoice-id", "INV-2026-001",
            "-o", str(pdf_file),
        ])
        assert result.exit_code == 0, f"print-invoice failed:\n{result.output}"
        assert os.path.exists(pdf_file), "PDF file was not created"
        assert os.path.getsize(pdf_file) > 0, "PDF file is empty"

    def test_success_message_contains_output_path(self, gnucash_with_invoice, tmp_path):
        """Success output includes the PDF output path."""
        pdf_file = tmp_path / "out.pdf"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "print-invoice", gnucash_with_invoice,
            "--invoice-id", "INV-2026-001",
            "-o", str(pdf_file),
        ])
        assert result.exit_code == 0
        assert str(pdf_file) in result.output


# ---------------------------------------------------------------------------
# Error-case tests
# ---------------------------------------------------------------------------

class TestPrintInvoiceErrors:

    def test_nonexistent_invoice_id_exits_nonzero(self, gnucash_with_invoice, tmp_path):
        """An invoice ID that does not exist in the book exits with a non-zero code."""
        pdf_file = tmp_path / "no.pdf"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "print-invoice", gnucash_with_invoice,
            "--invoice-id", "DOES-NOT-EXIST",
            "-o", str(pdf_file),
        ])
        assert result.exit_code != 0, (
            "Expected non-zero exit for unknown invoice ID, got 0"
        )
        assert not os.path.exists(pdf_file), "PDF should not be created for unknown invoice"

    def test_missing_invoice_id_flag_exits_2(self, gnucash_with_invoice, tmp_path):
        """Omitting --invoice-id exits with code 2 (Click UsageError)."""
        pdf_file = tmp_path / "no.pdf"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "print-invoice", gnucash_with_invoice,
            "-o", str(pdf_file),
        ])
        assert result.exit_code == 2

    def test_missing_output_flag_exits_2(self, gnucash_with_invoice):
        """Omitting -o exits with code 2 (Click UsageError)."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "print-invoice", gnucash_with_invoice,
            "--invoice-id", "INV-2026-001",
        ])
        assert result.exit_code == 2

    def test_nonexistent_gnucash_file_exits_2(self, tmp_path):
        """A GnuCash file that does not exist exits with code 2."""
        pdf_file = tmp_path / "no.pdf"
        runner = CliRunner()
        result = runner.invoke(cli, [
            "print-invoice", "/nonexistent/path/book.gnucash",
            "--invoice-id", "INV-2026-001",
            "-o", str(pdf_file),
        ])
        assert result.exit_code == 2
