"""What `print-invoice` writes, in each format and each output mode.

Its sibling file prints one invoice to PDF and otherwise covers refusals, so
the plaintext and HTML renderers, the per-file output mode, the combining of
several invoices into one document and the custom template were code no test
ran (T-009). The bill side is covered the same way, in
`test_cli_print_bill_output.py`; the two commands are separate implementations
of the same shape and neither stands in for the other.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli


@pytest.fixture
def book(tmp_path):
    """A book holding INV-2026-001 … INV-2026-005 for customer 1."""
    gnucash_file = tmp_path / 'invoices.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(gnucash_file), 'tests/fixtures/business_objects.txt',
        '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return str(gnucash_file)


class TestPlaintext:
    def test_an_invoice_prints_its_lines_and_totals(self, book, tmp_path):
        out = tmp_path / 'inv.txt'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, '--invoice-id', 'INV-2026-001',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code == 0, result.output
        text = out.read_text()
        assert 'INV-2026-001' in text
        assert 'invoice_subtotal:' in text
        assert 'invoice_total:' in text

    def test_stdout_takes_the_stream(self, book):
        result = CliRunner().invoke(cli, [
            'print-invoice', book, '--invoice-id', 'INV-2026-001',
            '--format', 'plaintext', '-o', '-'])

        assert result.exit_code == 0, result.output
        assert 'INV-2026-001' in result.output
        assert 'Wrote' not in result.output, 'a success line landed in the stream'

    def test_a_directory_gets_one_file_per_invoice(self, book, tmp_path):
        outdir = tmp_path / 'invoices'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, 'INV-2026-00*',
            '--format', 'plaintext', '-o', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        assert (outdir / 'INV-2026-001.txt').exists()
        assert (outdir / 'INV-2026-002.txt').exists()


class TestHtml:
    def test_several_invoices_combine_into_one_document(self, book, tmp_path):
        """One outer shell, whatever the per-invoice fragments carry."""
        out = tmp_path / 'all.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, 'INV-2026-001', 'INV-2026-002',
            '--format', 'html', '-o', str(out)])

        assert result.exit_code == 0, result.output
        text = out.read_text()
        assert text.count('<!DOCTYPE') == 0
        assert text.count('<html>') == 1
        assert text.count('<body>') == 1
        assert text.count('page-break-after') == 2

    def test_a_directory_gets_one_html_per_invoice(self, book, tmp_path):
        outdir = tmp_path / 'html'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, 'INV-2026-001', 'INV-2026-002',
            '--format', 'html', '-o', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        assert (outdir / 'INV-2026-001.html').exists()
        assert (outdir / 'INV-2026-002.html').exists()

    def test_a_custom_template_is_used_in_place_of_the_embedded_one(self, book,
                                                                    tmp_path):
        template = tmp_path / 'minimal.xslt'
        template.write_text(
            '<?xml version="1.0"?>\n'
            '<xsl:stylesheet version="1.0" '
            'xmlns:xsl="http://www.w3.org/1999/XSL/Transform">\n'
            '  <xsl:template match="/">\n'
            '    <html><body><p>TEMPLATE MARKER</p></body></html>\n'
            '  </xsl:template>\n'
            '</xsl:stylesheet>\n')
        out = tmp_path / 'custom.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, '--invoice-id', 'INV-2026-001',
            '--format', 'html', '--template', str(template), '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert 'TEMPLATE MARKER' in out.read_text()


class TestPdf:
    def test_several_invoices_combine_into_one_pdf(self, book, tmp_path):
        out = tmp_path / 'all.pdf'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, 'INV-2026-001', 'INV-2026-002',
            '--format', 'pdf', '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert out.read_bytes().startswith(b'%PDF')

    def test_a_directory_gets_one_pdf_per_invoice(self, book, tmp_path):
        outdir = tmp_path / 'pdfs'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, 'INV-2026-001', 'INV-2026-002',
            '--format', 'pdf', '-o', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        assert (outdir / 'INV-2026-001.pdf').read_bytes().startswith(b'%PDF')
        assert (outdir / 'INV-2026-002.pdf').read_bytes().startswith(b'%PDF')

    def test_stdout_is_refused_for_a_binary_format(self, book):
        result = CliRunner().invoke(cli, [
            'print-invoice', book, '--invoice-id', 'INV-2026-001',
            '--format', 'pdf', '-o', '-'])

        assert result.exit_code != 0
        assert 'only supported for --format plaintext' in result.output


class TestSelection:
    def test_a_customer_narrows_to_that_customers_invoices(self, book, tmp_path):
        """Filtered to a customer who has none, so the filter has to bite.

        Every invoice in the fixture belongs to customer 1, so `--customer 1`
        selects the whole book and reads exactly like passing no filter at
        all. Customer 2 exists and has nothing, which is the only way to see
        the filter work.
        """
        out = tmp_path / 'cust.txt'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, '--customer', '2',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code != 0, result.output
        assert 'no invoices matched the selection' in result.output
        assert "customer='2'" in result.output

    def test_the_customer_who_has_them_gets_them_all(self, book, tmp_path):
        out = tmp_path / 'cust1.txt'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, '--customer', '1',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert 'INV-2026-001' in out.read_text()

    def test_a_glob_that_matches_nothing_leaves_the_other_selectors_alone(
            self, book, tmp_path):
        out = tmp_path / 'mixed.txt'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, 'NOTHING-*', 'INV-2026-001',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert 'Wrote 1 invoice(s)' in result.output
        assert 'INV-2026-001' in out.read_text()

    def test_a_selection_that_matches_nothing_names_every_criterion_it_used(
            self, book, tmp_path):
        result = CliRunner().invoke(cli, [
            'print-invoice', book, 'INV-2026-001',
            '--from', '2020-01-01', '--to', '2020-12-31', '--customer', '1',
            '--format', 'plaintext', '-o', str(tmp_path / 'none.txt')])

        assert result.exit_code != 0
        assert 'no invoices matched the selection' in result.output
        assert "selectors=['INV-2026-001']" in result.output
        assert "from='2020-01-01'" in result.output
        assert "to='2020-12-31'" in result.output
        assert "customer='1'" in result.output

    def test_a_date_range_alone_matching_nothing_reports_only_the_dates(
            self, book, tmp_path):
        """No selector was given, so none is named — the criteria list is built
        from what the reader actually passed."""
        result = CliRunner().invoke(cli, [
            'print-invoice', book, '--from', '2020-01-01', '--to', '2020-12-31',
            '--format', 'plaintext', '-o', str(tmp_path / 'none.txt')])

        assert result.exit_code != 0
        assert 'no invoices matched the selection' in result.output
        assert 'selectors=' not in result.output
        assert "from='2020-01-01'" in result.output

    def test_a_date_range_narrows_by_when_the_invoice_was_opened(self, book,
                                                                 tmp_path):
        """A range that excludes the book, so the filter's false side runs.

        2020–2030 covers every invoice in the fixture, which exercises the
        filter without ever taking its false branch — the output is identical
        to passing no range at all.
        """
        out = tmp_path / 'dated.txt'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, '--from', '2020-01-01', '--to', '2020-12-31',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code != 0, result.output
        assert 'no invoices matched the selection' in result.output

    def test_a_range_that_covers_them_writes_them(self, book, tmp_path):
        out = tmp_path / 'covered.txt'
        result = CliRunner().invoke(cli, [
            'print-invoice', book, '--from', '2026-01-01', '--to', '2026-12-31',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert 'INV-2026-001' in out.read_text()
