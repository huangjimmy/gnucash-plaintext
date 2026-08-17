"""The printed page is GnuCash's, drawn by GnuCash.

`services/gnucash_report` hands the book and the document's guid to GnuCash's
own **Printable Invoice** — the report GnuCash's own Print Invoice button
draws — and asks it to render. Nothing about the layout, the columns or the
totals is computed here, so the document a customer receives is the one
GnuCash itself produces.

The figures are the point of the first test: this invoice is USD 100.00 in a
CAD book whose income account is CAD, which is the shape that printed
`USD 140.00` — the book's valuation — under a USD label.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
USD_IN_CAD = str(FIXTURES / 'fx_usd_invoice_cad_income.txt')
RATES = str(FIXTURES / 'fx_rates_usd_dated.yaml')


@pytest.fixture
def book(tmp_path):
    gnc = tmp_path / 'usd.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(gnc), USD_IN_CAD,
                                      '--include-business-objects',
                                      '--fx-rates', RATES])
    assert result.exit_code == 0, result.output
    return gnc


@pytest.fixture
def rendered(book):
    """The page GnuCash draws, with the book open in this very process."""
    from gnucash import Query

    from infrastructure.gnucash.utils import wrap_invoice_or_bill
    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    from services.gnucash_importer import _swig_invoice_guid_str
    from services.gnucash_report import render_document_html

    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        guid = _swig_invoice_guid_str(wrap_invoice_or_bill(list(query.run())[0]))
        query.destroy()
        yield render_document_html(repo.session, guid)
    finally:
        repo.close()


class TestTheFiguresAreTheDocumentsOwn:
    def test_the_books_valuation_is_nowhere_on_the_page(self, rendered):
        """140.00 is what a CAD book values this USD 100.00 invoice at."""
        assert '140.00' not in rendered, rendered[-1500:]

    def test_the_hundred_dollars_owed_is_stated(self, rendered):
        assert '$100.00' in rendered, rendered[-1500:]

    def test_no_figure_is_priced_in_the_books_currency(self, rendered):
        """GnuCash writes CAD as `C$` and USD as `$`, so the prefix is the
        test: a page carrying `C$` at all is a page pricing this USD document
        in the book's currency."""
        assert 'C$' not in rendered, rendered[-1500:]


class TestWhenItCannotDrawTheDocument:
    """A refusal is a sentence, and it reaches the person who ran the command.

    GnuCash's report resolves a document from a guid against whichever book is
    current. Asked for one the open book does not hold, it draws its "no
    invoice selected" page instead — which is not a document, and returning it
    would print an empty page as though it were one.
    """

    @pytest.fixture
    def another_books_guid(self, tmp_path):
        from gnucash import Query

        from infrastructure.gnucash.utils import wrap_invoice_or_bill
        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )
        from services.gnucash_importer import _swig_invoice_guid_str

        other = tmp_path / 'other.gnucash'
        built = CliRunner().invoke(cli, ['import', '--new', str(other),
                                         USD_IN_CAD,
                                         '--include-business-objects',
                                         '--fx-rates', RATES])
        assert built.exit_code == 0, built.output

        repo = GnuCashRepository(str(other))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            query = Query()
            query.search_for('gncInvoice')
            query.set_book(repo.book)
            guid = _swig_invoice_guid_str(
                wrap_invoice_or_bill(list(query.run())[0]))
            query.destroy()
            return guid
        finally:
            repo.close()

    def test_a_document_this_book_does_not_hold_is_refused(
            self, book, another_books_guid):
        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )
        from services.gnucash_report import (
            DocumentNotRenderedError,
            render_document_html,
        )

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            with pytest.raises(DocumentNotRenderedError) as refused:
                render_document_html(repo.session, another_books_guid)
        finally:
            repo.close()

        assert another_books_guid in str(refused.value), str(refused.value)

    @pytest.mark.parametrize('named', ['Printable Invoice', 'Fancy Invoice',
                                       'Easy Invoice', 'Tax Invoice',
                                       'Australian Tax Invoice'])
    def test_naming_the_report_does_not_lose_the_refusal(
            self, book, another_books_guid, named):
        """The check is on which report drew, not on whether one was named.

        Printable, Easy and Fancy Invoice are three `gnc:define-report` calls
        in one `invoice.scm` sharing one `'renderer reg-renderer` — read out
        of the shipped file on 5.10 and 3.8. That renderer draws
        `gnc:html-make-generic-warning` for a document the book does not hold:
        "No valid invoice selected. Click on the Options button and select the
        invoice to use.", with no `invoice-title` div.

        Keyed on `report is None`, naming any of the three — including the
        default by its own name — skipped the check, and the warning page was
        written to a PDF and reported as `✓ Wrote 1 invoice(s)`. That page
        goes to a customer.

        Tax Invoice is here because it is advertised the same way: named in
        `--report`, its module loaded on purpose, documented in README. It is
        not of that family and writes neither the heading div nor the same
        warning — measured on 5.10, it draws a 232-byte fragment reading "No
        invoice has been selected -- please use the Options menu to select
        one.", against 4192 bytes for a real document — so it is checked on
        what its own page carries. A report of the *reader's* own stays
        exempt: this project has no claim on someone else's markup.
        """
        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )
        from services.gnucash_report import (
            DocumentNotRenderedError,
            render_document_html,
        )

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            with pytest.raises(DocumentNotRenderedError) as refused:
                render_document_html(repo.session, another_books_guid,
                                     report=named)
        finally:
            repo.close()

        assert another_books_guid in str(refused.value), str(refused.value)

    def test_a_report_file_with_no_report_named_is_refused(self, book):
        """Asked of the service, which is where the guard has to hold.

        Both commands refuse this pair before reaching here, so nothing
        through the CLI can test it — and a library caller is the real
        scenario for a service entry point. It matters because everything
        downstream reads `report is None` as "the page this tool chose": with
        this pair allowed that meant it while drawing the Printable Invoice
        with both of its guards switched off.
        """
        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )
        from services.gnucash_report import (
            DocumentNotRenderedError,
            render_document_html,
        )

        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            with pytest.raises(DocumentNotRenderedError) as refused:
                render_document_html(
                    repo.session, 'whatever',
                    report_file='tests/fixtures/a_report_of_your_own.scm')
        finally:
            repo.close()

        assert 'no report named' in str(refused.value), str(refused.value)

    def test_asking_without_a_session_says_so(self):
        """A guid names a document and says nothing about which book holds
        it, so a caller can reach here with no session. That has to state what
        is missing, not fail somewhere inside a ctypes call."""
        from services.gnucash_report import (
            DocumentNotRenderedError,
            render_document_html,
        )

        with pytest.raises(DocumentNotRenderedError) as refused:
            render_document_html(None, 'whatever')

        assert 'session' in str(refused.value), str(refused.value)


class TestItIsGnuCashsPage:
    def test_the_heading_is_the_one_gnucash_writes(self, rendered):
        """`Invoice #<id>`, top left — the Printable Invoice's own title."""
        assert '<div class="invoice-title">Invoice #INV-USD-001</div>' \
            in rendered, rendered[:2000]

    def test_the_columns_are_the_ones_gnucash_ships(self, rendered):
        for heading in ('Date', 'Description', 'Action', 'Quantity',
                        'Unit Price', 'Discount', 'Taxable', 'Total'):
            assert f'<th>{heading}</th>' in rendered, (heading, rendered)

    def test_the_totals_are_the_ones_gnucash_ships(self, rendered):
        """This invoice is `taxable: false`, so there is no tax row at all —
        the tax rows are one per tax account, named, and an untaxed document
        has none. `test_q019_draft_tax_render` covers a taxed one."""
        for label in ('Net Price', 'Total Price', 'Amount Due'):
            assert f'>{label}</td>' in rendered, (label, rendered[-2500:])

    def test_the_customer_is_named(self, rendered):
        assert 'US Customer' in rendered, rendered[:3000]

    def test_the_reports_own_footer_is_left_as_gnucash_wrote_it(self,
                                                                rendered):
        """`Extra Notes` belongs to the reader, and `print-invoice` writes
        nothing into the option.

        The default is the literal "Thank you for your patronage!"
        (`invoice.scm`), printed here because GnuCash draws the page. A
        reader wanting a different footer, or none, says so in GnuCash's
        report options dialog or with `set-invoice-style` on the book — both
        reach the render below.
        """
        # By the block the report puts it in rather than by its words: the
        # default is `(G_ "Thank you for your patronage!")`, translated at
        # render time, so a localized build says something else entirely. The
        # English is asserted beside it because the suite runs under C.UTF-8,
        # where it is what GnuCash writes.
        assert 'invoice-notes' in rendered, rendered[-1500:]
        assert 'patronage' in rendered.lower(), rendered[-1500:]
