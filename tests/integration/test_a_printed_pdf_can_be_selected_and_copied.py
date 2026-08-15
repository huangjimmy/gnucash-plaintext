"""A printed PDF carries text, not a picture of text.

`print-invoice --format pdf` is what a customer receives, and what they do with
it is select it, copy it, search it, and feed it to whatever reads invoices.
That needs the page's glyphs to map back to characters — a `/ToUnicode` CMap
per embedded font — which a PDF laid out from HTML gets and a rasterised one
does not.

So the check is to read the text back out of the file with a PDF reader and
look for what the page says. Asserting on the HTML instead would prove nothing
about the PDF, which is the artefact that leaves the building.

The figures are asserted too, because the same run proves them: this invoice is
2 hours at C$100.00 with GST 5% + PST 7%, so the page owes C$224.00.
"""

import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.rendered_page import readable

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
INVOICE = str(FIXTURES / 'q019_unposted_cash_with_tax.txt')
BILL = str(FIXTURES / 'q019_unposted_cash_bill.txt')
TWO_BILLS = str(FIXTURES / 'two_bills_to_print.txt')

@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(path), ACCOUNTS])
    assert made.exit_code == 0, made.output
    # Two saves inside one second collide on the backup file's name, which
    # GnuCash reports as ERR_FILEIO_BACKUP_ERROR and the import treats as a
    # failure — the backup name is stamped to the second.
    time.sleep(1.1)
    for fixture in (INVOICE, BILL):
        result = CliRunner().invoke(cli, [
            'import', str(path), fixture, '--include-business-objects'])
        assert result.exit_code == 0, result.output
        time.sleep(1.1)
    return path


def _text_of(pdf_path):
    """Everything a reader would get from selecting the whole document.

    Whitespace is collapsed because a PDF's line breaks are the layout's, not
    the text's: `Amount Due` sits in a narrow cell and comes back as `Amount`
    and `Due` on two lines. Selecting both words is selecting the label.
    """
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    return ' '.join(readable('\n'.join(page.extract_text()
                                       for page in reader.pages)).split())


def _printed(book, tmp_path, command, doc_id, name):
    out = tmp_path / name
    result = CliRunner().invoke(cli, [
        command, str(book), doc_id, '--format', 'pdf', '--output', str(out)])
    assert result.exit_code == 0, result.output
    return out


class TestAnInvoice:
    @pytest.fixture
    def text(self, book, tmp_path):
        return _text_of(_printed(book, tmp_path, 'print-invoice',
                                 'INV-Q19-CASH-TAX-200', 'inv.pdf'))

    def test_the_customer_can_be_selected(self, text):
        assert 'Beta Industries' in text, text

    def test_the_invoice_number_can_be_selected(self, text):
        assert 'INV-Q19-CASH-TAX-200' in text, text

    def test_the_figures_can_be_selected(self, text):
        """2 × C$100.00, GST 5% and PST 7% each named → C$224.00 owed."""
        for figure in ('C$200.00', 'C$10.00', 'C$14.00', 'C$224.00'):
            assert figure in text, (figure, text)

    def test_each_tax_is_named_and_selectable(self, text):
        """A reader has to be able to copy the GST figure out on its own — it
        is the one a filer reclaims, and a combined GST+PST total is not it."""
        for name in ('GST', 'PST'):
            assert name in text, (name, text)

    def test_the_total_says_what_is_owed(self, text):
        assert 'Amount Due' in text, text


class TestABill:
    @pytest.fixture
    def text(self, book, tmp_path):
        return _text_of(_printed(book, tmp_path, 'print-bill',
                                 'BILL-Q19-CASH-TAX-400', 'bill.pdf'))

    def test_the_vendor_can_be_selected(self, text):
        assert 'Office Depot Wholesale' in text, text

    def test_the_figures_can_be_selected(self, text):
        for figure in ('C$200.00', 'C$10.00', 'C$14.00', 'C$224.00'):
            assert figure in text, (figure, text)

    def test_each_tax_is_named_and_selectable(self, text):
        for name in ('GST', 'PST'):
            assert name in text, (name, text)

    def test_it_does_not_thank_the_vendor_for_their_patronage(self, text):
        """The report's `Extra Notes` default says exactly that, and a bill is
        a document the *vendor* sent us — so on this side of the transaction
        the sentence is not merely uninvited, it is backwards."""
        assert 'patronage' not in text.lower(), text


class TestSeveralDocumentsInOnePdf:
    """Two documents in one file, one per page.

    The shell they are wrapped in is built here — the pages are rendered
    separately and joined — so a swallowed `<body>` or a lost page break shows
    up as a page that reads blank or as two documents printed on top of each
    other.
    """

    @pytest.fixture
    def two_bills(self, tmp_path):
        path = tmp_path / 'bills.gnucash'
        made = CliRunner().invoke(cli, ['import', '--new', str(path), ACCOUNTS])
        assert made.exit_code == 0, made.output
        time.sleep(1.1)
        result = CliRunner().invoke(cli, [
            'import', str(path), TWO_BILLS, '--include-business-objects'])
        assert result.exit_code == 0, result.output
        return path

    def test_each_one_is_on_its_own_page(self, two_bills, tmp_path):
        import pypdf

        out = tmp_path / 'both.pdf'
        result = CliRunner().invoke(cli, [
            'print-bill', str(two_bills), 'BILL-PRINT-*',
            '--format', 'pdf', '--output', str(out)])
        assert result.exit_code == 0, result.output

        pages = [readable(page.extract_text())
                 for page in pypdf.PdfReader(str(out)).pages]
        assert len(pages) == 2, pages
        assert 'BILL-PRINT-001' in pages[0], pages[0]
        assert 'BILL-PRINT-002' in pages[1], pages[1]
