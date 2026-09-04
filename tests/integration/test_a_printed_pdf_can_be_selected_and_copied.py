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
2 hours at C$100.00 with GST 5% + PST 7%, so it owes C$224.00.
"""

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
    for fixture in (INVOICE, BILL):
        result = CliRunner().invoke(cli, [
            'import', str(path), fixture, '--include-business-objects'])
        assert result.exit_code == 0, result.output
    return path


def _text_of(pdf_path):
    """Everything a reader would get from selecting the whole page.

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

    def test_the_reports_own_footer_reaches_the_pdf(self, text):
        """`Extra Notes` is the reader's option and is left as GnuCash set it,
        so its default sentence prints — on a bill too, where it reads oddly,
        because that is what GnuCash prints for a bill and the option belongs
        to whoever is printing. `set-invoice-style --note` is where a book
        says otherwise."""
        assert 'patronage' in text.lower(), text


class TestThePrintingPageRunsNoScript:
    """A deliberate difference from GnuCash's own viewer, which leaves
    scripting on because it is a browser as well as a printer.

    A report interpolates book text into the page it draws — a customer's
    name, an entry description, a logo filename — so a field it does not
    escape is script executing while an invoice is printed. Nothing about
    laying a page out needs scripting, and the page comes out the same
    without it.

    Asserted through the service that lays pages out, on a page written here:
    a page GnuCash drew has no script to run, which is the point, so
    there is nothing in one to assert against.
    """

    def test_what_a_script_would_have_written_is_not_on_the_page(self,
                                                                 tmp_path):
        from infrastructure.pdf.printing import laid_out_by_webkit

        # `document.write` is the DOM's, and the spelling is what makes this
        # assertion mean anything: renamed to something JavaScript does not
        # define, the script throws instead of writing and the assertion
        # below passes with scripting fully enabled.
        page = ('<html><body><p>PRINTED BY THE REPORT</p>'
                '<script>document.write("WRITTEN BY A SCRIPT")</script>'
                '</body></html>')
        out = tmp_path / 'scripted.pdf'
        out.write_bytes(laid_out_by_webkit(page))

        text = _text_of(out)

        assert 'PRINTED BY THE REPORT' in text, text
        assert 'WRITTEN BY A SCRIPT' not in text, text


class TestTheCharactersReachThePdf:
    """Accented text survives the handoff into the printed file.

    Newly load-bearing: WeasyPrint took a `str`, and WebKit reads the page
    off a `file://` URI — so what reaches the printer depends on the
    `<meta charset>` GnuCash writes surviving `combine_pages` and on the file
    being written UTF-8. Both hold, and a change to either would mojibake
    every printed invoice with an accent in it while every other test here
    stayed green.

    Latin-1-range letters rather than the CJK of
    `test_a_printed_page_keeps_its_characters`: no image ships a CJK
    font, so that one can say nothing about a PDF, while `Café Ltée` is
    drawn by the fonts every image has.
    """

    def test_an_accented_name_is_selectable(self, tmp_path):
        """Through the whole pipeline, not a page written here: GnuCash draws
        it, `combine_pages` rebuilds the shell around it, the parent writes
        the file, WebKit reads it back. A hand-written page proves only that
        WebKit honours a `<meta charset>` somebody typed, and would pass with
        the head dropped or the file written in the locale's encoding."""
        book = tmp_path / 'accented.gnucash'
        made = CliRunner().invoke(cli, [
            'import', '--new', str(book),
            'tests/fixtures/an_invoice_in_more_than_ascii.txt',
            '--include-business-objects'])
        assert made.exit_code == 0, made.output

        out = tmp_path / 'accented.pdf'
        printed = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-UNICODE-001',
            '--format', 'pdf', '--output', str(out)])
        assert printed.exit_code == 0, printed.output

        text = _text_of(out)
        assert 'Éditions Cliché Inc.' in text, text
        assert 'Montréal' in text, text
        assert 'étude de marché' in text, text


class TestOnADisplayTheCallerAlreadyHas:
    """A desktop, where `DISPLAY` is set before the command runs.

    The images have none, so the arm a person at a screen takes is the one
    the suite would otherwise never enter — and it is the arm that starts no
    server and cleans nothing up. Entered here by arranging a display the
    ordinary way and then handing its `DISPLAY` back in, which is what a
    desktop looks like from inside this function.
    """

    def test_the_page_is_printed_on_it(self, tmp_path, monkeypatch):
        from infrastructure.pdf.printing import a_display, laid_out_by_webkit

        with a_display() as (_, arranged):
            monkeypatch.setenv('DISPLAY', arranged['DISPLAY'])
            if 'XAUTHORITY' in arranged:
                monkeypatch.setenv('XAUTHORITY', arranged['XAUTHORITY'])

            with a_display() as (prefix, env):
                assert prefix == [], prefix       # nothing wrapped
                assert env is None, env           # nothing arranged

            out = tmp_path / 'on-a-desktop.pdf'
            out.write_bytes(laid_out_by_webkit(
                '<html><body><p>PRINTED ON A DESKTOP</p></body></html>'))

        assert 'PRINTED ON A DESKTOP' in _text_of(out)


class TestWhenTheEngineIsNotThere:
    """The sentence a reader without the bindings meets.

    WebKit's library arrives with GnuCash, its Python bindings do not — so
    `import gi` failing in the child is the likeliest way this path breaks on
    a real machine, and what comes back must name the package rather than a
    traceback. Reached by pointing the parent at a child that is not there,
    which is what a machine missing them amounts to: `python3 -m` exits
    non-zero and says why.
    """

    def test_it_names_what_to_install(self, monkeypatch):
        from infrastructure.pdf import printing

        monkeypatch.setattr(printing, '_CHILD',
                            'infrastructure.pdf.no_such_child')

        with pytest.raises(printing.PdfEngineUnavailableError) as told:
            printing.laid_out_by_webkit('<html><body>x</body></html>')

        assert 'python3-gi' in str(told.value), told.value
        assert 'No module named' in str(told.value), told.value


class TestSeveralInvoicesInOnePdf:
    """Two pages in one file, one per page.

    The shell they are wrapped in is built here — the pages are rendered
    separately and joined — so a swallowed `<body>` or a lost page break shows
    up as a page that reads blank or as two pages printed on top of each
    other.
    """

    @pytest.fixture
    def two_bills(self, tmp_path):
        path = tmp_path / 'bills.gnucash'
        made = CliRunner().invoke(cli, ['import', '--new', str(path), ACCOUNTS])
        assert made.exit_code == 0, made.output
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
