"""What `print-bill` actually writes, in each format and each output mode.

Its sibling file covers what the command refuses. Nothing covered what it
produces: every existing test stops at a `UsageError`, so the renderer's
posted-bill path — where the tax lines and the subtotal are derived from the
posting transaction's splits rather than from the entries — was never run at
all, on any supported version (T-009).

Three formats and two output modes make six combinations, plus the selection
that decides which bills reach them. A bill with two taxes and a payment
beside one with neither is what keeps a renderer honest about both.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
BILLS = str(FIXTURES / 'two_bills_to_print.txt')


def _book(tmp_path):
    """A book holding BILL-PRINT-001 (with tax, part-paid) and BILL-PRINT-002."""
    runner = CliRunner()
    gnc = tmp_path / 'book.gnucash'
    created = runner.invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert created.exit_code == 0, created.output
    imported = runner.invoke(cli, ['import', str(gnc), BILLS,
                                   '--include-business-objects'])
    assert imported.exit_code == 0, imported.output
    return gnc


class TestPlaintext:
    def test_a_posted_bill_prints_its_taxes_and_what_is_left_owing(self, tmp_path):
        """The figures come from the posting transaction, not from the entries."""
        gnc = _book(tmp_path)
        out = tmp_path / 'bill.txt'
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-001',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert f'Wrote 1 bill(s) to {out}' in result.output
        text = out.read_text()
        assert 'BILL-PRINT-001' in text
        assert 'Alpha Supply' in text
        assert 'Office chairs' in text
        # 2 × 500 net, 5% + 7% on top: 1000 + 50 + 70.
        assert '1000.00' in text
        assert '1120.00' in text
        assert '400.00' in text          # the payment

    def test_a_bill_with_no_tax_prints_without_inventing_a_tax_line(self, tmp_path):
        gnc = _book(tmp_path)
        out = tmp_path / 'plain.txt'
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-002',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code == 0, result.output
        text = out.read_text()
        assert 'Printer paper' in text
        assert '120.00' in text
        assert 'Beta Trading' in text

    def test_stdout_takes_the_stream_of_both(self, tmp_path):
        """`-o -` writes the bills joined, and says nothing else on the way."""
        gnc = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-001', 'BILL-PRINT-002',
            '--format', 'plaintext', '-o', '-'])

        assert result.exit_code == 0, result.output
        assert 'BILL-PRINT-001' in result.output
        assert 'BILL-PRINT-002' in result.output
        assert 'Wrote' not in result.output, 'a success line landed in the stream'

    def test_a_directory_gets_one_file_per_bill(self, tmp_path):
        gnc = _book(tmp_path)
        outdir = tmp_path / 'bills'
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-*',
            '--format', 'plaintext', '-o', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        assert 'Wrote 2 bill(s)' in result.output
        assert (outdir / 'BILL-PRINT-001.txt').exists()
        assert (outdir / 'BILL-PRINT-002.txt').exists()
        assert 'Office chairs' in (outdir / 'BILL-PRINT-001.txt').read_text()


class TestHtml:
    def test_two_bills_combine_into_one_page(self, tmp_path):
        """One outer shell, whatever the per-bill fragments carry.

        Each fragment is a whole page of GnuCash's, with its own DOCTYPE,
        `<html>` and `<body>`; left in place they nest, and the combined file
        is neither valid HTML nor valid XML.
        """
        gnc = _book(tmp_path)
        out = tmp_path / 'both.html'
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-001', 'BILL-PRINT-002',
            '--format', 'html', '-o', str(out)])

        assert result.exit_code == 0, result.output
        text = out.read_text()
        # One of each, and the report's own — the shell is carried from the
        # first fragment rather than synthesised, so the tags keep their
        # attributes and the count is one, not zero.
        assert text.count('<!DOCTYPE') == 1
        assert text.count('<html') == 1
        assert text.count('<body') == 1
        assert text.count('page-break-after') == 2
        assert 'BILL-PRINT-001' in text
        assert 'BILL-PRINT-002' in text

    def test_a_directory_gets_one_html_per_bill(self, tmp_path):
        gnc = _book(tmp_path)
        outdir = tmp_path / 'html'
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-*',
            '--format', 'html', '-o', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        assert (outdir / 'BILL-PRINT-001.html').exists()
        assert (outdir / 'BILL-PRINT-002.html').exists()


class TestPdf:
    def test_two_bills_combine_into_one_pdf(self, tmp_path):
        gnc = _book(tmp_path)
        out = tmp_path / 'both.pdf'
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-001', 'BILL-PRINT-002',
            '--format', 'pdf', '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert out.read_bytes().startswith(b'%PDF')

    def test_a_directory_gets_one_pdf_per_bill(self, tmp_path):
        gnc = _book(tmp_path)
        outdir = tmp_path / 'pdfs'
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-*',
            '--format', 'pdf', '-o', f'{outdir}/'])

        assert result.exit_code == 0, result.output
        assert (outdir / 'BILL-PRINT-001.pdf').read_bytes().startswith(b'%PDF')
        assert (outdir / 'BILL-PRINT-002.pdf').read_bytes().startswith(b'%PDF')

    def test_stdout_is_refused_for_a_binary_format(self, tmp_path):
        gnc = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-001',
            '--format', 'pdf', '-o', '-'])

        assert result.exit_code != 0
        assert 'only supported for --format plaintext' in result.output


class TestSelection:
    def test_a_vendor_narrows_to_that_vendors_bills(self, tmp_path):
        gnc = _book(tmp_path)
        out = tmp_path / 'vendor.txt'
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), '--vendor', 'V-PRINT-B',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert 'Wrote 1 bill(s)' in result.output
        assert 'BILL-PRINT-002' in out.read_text()
        assert 'BILL-PRINT-001' not in out.read_text()

    def test_a_date_range_narrows_by_when_the_bill_was_opened(self, tmp_path):
        gnc = _book(tmp_path)
        out = tmp_path / 'dated.txt'
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), '--from', '2026-03-01', '--to', '2026-03-31',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert 'Wrote 1 bill(s)' in result.output
        assert 'BILL-PRINT-002' in out.read_text()

    def test_a_glob_that_matches_nothing_leaves_the_other_selectors_alone(
            self, tmp_path):
        """Selectors are OR-ed, so a miss has to fall through to the next one."""
        gnc = _book(tmp_path)
        out = tmp_path / 'mixed.txt'
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'NOTHING-*', 'BILL-PRINT-002',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert 'Wrote 1 bill(s)' in result.output
        assert 'BILL-PRINT-002' in out.read_text()

    def test_a_selection_that_matches_nothing_names_every_criterion_it_used(
            self, tmp_path):
        """All four are listed, so the reader can see which one excluded them."""
        gnc = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'BILL-PRINT-001',
            '--from', '2020-01-01', '--to', '2020-12-31',
            '--vendor', 'V-PRINT-A',
            '--format', 'plaintext', '-o', str(tmp_path / 'none.txt')])

        assert result.exit_code != 0
        assert 'no bills matched the selection' in result.output
        assert "selectors=['BILL-PRINT-001']" in result.output
        assert "from='2020-01-01'" in result.output
        assert "to='2020-12-31'" in result.output
        assert "vendor='V-PRINT-A'" in result.output

    def test_the_bill_id_flag_names_the_same_bill_a_positional_does(self, tmp_path):
        """`--bill-id` is the back-compat spelling and nothing exercised it."""
        gnc = _book(tmp_path)
        out = tmp_path / 'flagged.txt'
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), '--bill-id', 'BILL-PRINT-001',
            '--format', 'plaintext', '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert 'BILL-PRINT-001' in out.read_text()


class TestABookThatAlsoHoldsInvoices:
    """The ordinary book, for anyone who both invoices and bills.

    GnuCash keeps invoices and bills in one `gncInvoice` type, so `print-bill`
    asks every record whether it has a vendor. `GetOwner().GetVendor()`
    answers None for a customer invoice rather than raising, which is why
    `_all_bills` needs no `except` around it — but a book of bills only never
    asks the question, so nothing here executed that call on an invoice on any
    supported build. CLAUDE.md's findings about per-distro SWIG accessors are
    the reason that is worth a test rather than a probe.
    """

    def _mixed_book(self, tmp_path):
        gnc = _book(tmp_path)
        added = CliRunner().invoke(cli, [
            'import', str(gnc), str(FIXTURES / 'an_invoice_beside_the_bills.txt'),
            '--include-business-objects'])
        assert added.exit_code == 0, added.output
        return gnc

    def test_the_premise_the_book_holds_an_invoice_too(self, tmp_path):
        """Or the rest is about a book no different from the others."""
        gnc = self._mixed_book(tmp_path)

        listing = tmp_path / 'listing.txt'
        assert CliRunner().invoke(cli, [
            'export', str(gnc), str(listing),
            '--include-business-objects']).exit_code == 0
        text = listing.read_text()
        assert 'invoice "INV-BESIDE-001"' in text, text
        assert 'bill "BILL-PRINT-001"' in text, text

    def test_every_bill_still_prints(self, tmp_path):
        gnc = self._mixed_book(tmp_path)
        out = tmp_path / 'all.txt'
        # `'*'` rather than either bill's id: the point is that every record
        # in the book is offered to the vendor test, invoice included.
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), '*', '--format', 'plaintext',
            '-o', str(out)])

        assert result.exit_code == 0, result.output
        text = out.read_text()
        assert 'BILL-PRINT-001' in text, text
        assert 'BILL-PRINT-002' in text, text

    def test_the_invoice_is_not_printed_as_one_of_them(self, tmp_path):
        gnc = self._mixed_book(tmp_path)
        out = tmp_path / 'all.txt'
        assert CliRunner().invoke(cli, [
            'print-bill', str(gnc), '*', '--format', 'plaintext',
            '-o', str(out)]).exit_code == 0

        text = out.read_text()
        assert 'BILL-PRINT-001' in text, text
        assert 'INV-BESIDE-001' not in text, text
        assert 'Print Customer A' not in text, text

    def test_naming_the_invoice_is_refused_rather_than_obeyed(self, tmp_path):
        gnc = self._mixed_book(tmp_path)
        result = CliRunner().invoke(cli, [
            'print-bill', str(gnc), 'INV-BESIDE-001',
            '--format', 'plaintext', '-o', str(tmp_path / 'no.txt')])

        assert result.exit_code != 0, result.output
        assert 'INV-BESIDE-001' in result.output, result.output
