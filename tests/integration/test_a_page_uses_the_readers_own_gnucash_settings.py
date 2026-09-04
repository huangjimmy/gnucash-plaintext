"""A printed page is drawn with the reader's GnuCash settings, not defaults.

Three things decide what a printed page looks like: the book, the report,
and the settings made in GnuCash. `print-invoice` read the book and the report
and never the settings — the command embeds the library and draws the report,
while GnuCash *starts* by reading a user configuration, `gnc_load_scm_config`
taking in `stylesheets-2.0` and the saved-report files before any report is
drawn.

The cost, measured from one invoice printed by GnuCash and by `print-invoice`,
one book and one report:

    GnuCash          <table cellspacing="0.0" cellpadding="4.0" border="1.0">
    print-invoice    <table cellspacing="0.0" cellpadding="4.0" border="0.0">
    GnuCash          <body bgcolor="#f6f5f4">    print-invoice  #ffffff
    GnuCash          font-size: 12pt             print-invoice  10pt

Every one of those is an option of the *stylesheet* — `Table border width`,
`Background Color`, the font sizes — which the reader had set years ago in
GnuCash's own dialog and which is kept in `stylesheets-2.0`. Their invoice has
a box round every table and a grey page; the same invoice printed here had
neither, and nothing about the book, the report or the page's CSS differed.

So the files are read where GnuCash keeps them, through the same
`gnc-build-userdata-path` its own stylesheet code calls. Nothing is copied out
of them and no style is invented here: they are the reader's settings, applied
by the reader's GnuCash, which is the whole of the fix.

**A stylesheet outlives the file it came from**, registering into a hash that
lives as long as the process exactly as a report does — so a customised
`Default` loaded here would draw every later page in the run, across test
files, with a box round every table. The fixture puts the stock one back; see
`_put_the_default_stylesheet_back`.

The reports are the half that cannot be undone, `gnc:define-report` refusing a
duplicate guid, and they are additions rather than replacements: a saved
configuration registered under its own guid changes no page that does not name
it.
"""

import os
import re
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')

#: A whole invoice, not a sparse one: a seller with an address and
#: registration numbers, a customer with an address, a posted invoice with a
#: described line, dates written the book's way. A page drawn from a book
#: missing those is boxes around nothing, and a test reading it cannot tell an
#: empty address from a stylesheet that never applied.
LEDGER = str(FIXTURES / 'a_book_that_prints_a_whole_invoice.txt')
INVOICE = 'INV-WHOLE-001'
A_BILL = 'BILL-WHOLE-001'

#: The invoice's `notes:`, printed only where `Display/Invoice Notes` is on —
#: which `print-invoice` sets on GnuCash's own invoice reports and a saved
#: configuration carries only if saved with the switch on.
THE_INVOICES_NOTES = 'Net 30. Quoted 2026-07-01.'

#: The shape GnuCash writes, from `gnc:save-style-sheet-options` in
#: `html-style-sheet.scm`: find the template, generate its options, restore the
#: ones that differ from their defaults, register it under its name.
#: `Table border width` and nothing else, though a real reader's file carries
#: whatever they changed. It is a plain number on every supported build, where
#: a colour is not: 3.8 keeps one as a list and 5.x as a hex string, so a file
#: setting a colour the 5.x way fails to load on 3.8 — and a saved-report file
#: that fails to load takes down every setting the file holds, including the
#: border width. GnuCash's own format differing across GnuCash versions is the
#: cause, decided nowhere in `print-invoice`, and one number proves the
#: mechanism without dragging the difference in.
A_STYLESHEET_THE_READER_CHANGED = '''(let ((template (gnc:html-style-sheet-template-find "Plain")))
  (if template
    (let ((options ((gnc:html-style-sheet-template-options-generator template))))
(let ((option (gnc:lookup-option options
                                 "Tables"
                                 "Table border width")))
  ((lambda (o) (if o (gnc:option-set-value o 1))) option))

 (gnc:restore-html-style-sheet "Default" "Plain" options))))
'''


def _where_gnucash_keeps_them() -> Path:
    """The directory `gnc-build-userdata-path` resolves to in this process.

    Not one of the test's choosing: GnuCash settles its user data directory
    when it initialises, so moving `HOME` from a test moves nothing — measured,
    the path came back under the original `HOME` while the environment said
    otherwise. The file has to go where this process will actually look, which
    is where the reader's GnuCash would have written it.

    `GNC_DATA_HOME` and `XDG_DATA_HOME` are honoured in the same order
    `gnc_filepath_utils` honours them, so a suite run with either set writes
    where that run will read rather than somewhere it will not look.
    """
    if os.environ.get('GNC_DATA_HOME'):
        return Path(os.environ['GNC_DATA_HOME']).expanduser()
    if os.environ.get('XDG_DATA_HOME'):
        return Path(os.environ['XDG_DATA_HOME']).expanduser() / 'gnucash'
    return Path(os.environ.get('HOME', '~')).expanduser() / '.local' \
        / 'share' / 'gnucash'


@pytest.fixture
def a_fresh_process():
    """The read-once flag as a new process has it.

    GnuCash reads its configuration when it starts, and so does this — the
    files register into an interpreter that lives as long as the process. A
    test writing one of them after some other test has already rendered would
    be writing it after that read, and would then assert against a page that
    never saw it. Every test here that puts a file in place takes this.
    """
    from services import gnucash_report

    was = gnucash_report._read_the_readers_gnucash
    gnucash_report._read_the_readers_gnucash = False
    try:
        yield
    finally:
        gnucash_report._read_the_readers_gnucash = was


#: Putting the registry back. A stylesheet is registered by name into a hash
#: that lives as long as the process — `(hash-set! *gnc:_style-sheets_*
#: style-sheet-name ss)` in `html-style-sheet.scm` — so registering `Default`
#: again under the options its template generates is the stock instance
#: exactly, and replaces the customised one. `gnc:make-html-style-sheet` is
#: the call GnuCash itself makes for the stock `Default`, arguments in that
#: order: template first, instance name second.
#:
#: Caught, because deleting the file is not enough on its own and failing to
#: restore must not fail the test that succeeded: the modules are loaded by a
#: render, so nothing here is bound until one has happened.
_THE_STOCK_DEFAULT = '''(catch #t
  (lambda () (gnc:make-html-style-sheet "Plain" "Default"))
  (lambda ignored #f))'''


def _put_the_default_stylesheet_back():
    """Undo the registration, so the next test file draws GnuCash's page.

    The customised `Default` outlives the file it came from: the file is read
    once per process and what it registers stays. Without this, every later
    render in the same pytest process draws with a box round every table —
    across test *files*, so a test elsewhere asserting on borders or
    background would pass or fail by collection order.
    """
    from infrastructure.guile import load_guile

    load_guile().scm_c_eval_string(_THE_STOCK_DEFAULT.encode('utf-8'))


@pytest.fixture
def a_setting_of_the_readers(a_fresh_process):
    """One stylesheet setting, saved the way GnuCash saves it.

    Removed afterwards, and only if this fixture is what wrote it — a file
    this did not create is somebody's real configuration and is left alone.
    The registration it made is undone with it.
    """
    where = _where_gnucash_keeps_them()
    where.mkdir(parents=True, exist_ok=True)
    path = where / 'stylesheets-2.0'
    if path.exists():
        pytest.skip(f'{path} exists already and is not this test\'s to move')
    path.write_text(A_STYLESHEET_THE_READER_CHANGED, encoding='utf-8')
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
        _put_the_default_stylesheet_back()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    return path


def _printed(book, tmp_path):
    out = tmp_path / 'page.html'
    result = CliRunner().invoke(cli, [
        'print-invoice', str(book), INVOICE,
        '--format', 'html', '--output', str(out)])
    assert result.exit_code == 0, result.output
    return out.read_text(encoding='utf-8')


class TestWhatTheReaderSet:
    def test_their_table_borders_reach_the_page(self, book,
                                                a_setting_of_the_readers,
                                                tmp_path):
        """`Table border width` puts a box round every table, and the box is
        the first difference a reader sees between a page from GnuCash and a
        page from `print-invoice`.

        Matched on `border="1` rather than the whole attribute, because the
        eras write the number differently — 5.10 says `border="1.0"` and 3.8
        says `border="1"` — and the digit is the setting either way.
        """
        page = _printed(book, tmp_path)

        assert 'border="1' in page, page[:1500]
        assert 'border="0' not in page, page[:1500]

    def test_and_the_page_is_otherwise_the_one_gnucash_draws(
            self, book, a_setting_of_the_readers, tmp_path):
        """The reader's setting is applied to GnuCash's page, and the page
        stays GnuCash's — no page is drawn anywhere in `print-invoice`."""
        page = _printed(book, tmp_path)

        assert INVOICE in page, page[:1500]
        assert 'class="entries-table"' in page, page[:1500]


#: The guid the configuration below registers under, and which a book naming
#: its own invoice report holds.
SAVED_REPORT_GUID = '7c7d1f1b9a5e4d0f8b2a3c4d5e6f7a8b'

A_REPORT_SAVED_IN_GNUCASH = '''(let ()
  (define (options-gen)
    (let
         (
           (options (gnc:report-template-new-options/report-guid "5123a759ceb9483abf2182d01c140e8d" "Printable Invoice"))
           (new-embedded-report-ids '())
         )

(let ((option (gnc:lookup-option options
                                 "Layout"
                                 "CSS")))
  ((lambda (o) (if o (gnc:option-set-value o ".entries-table * { border-width: 3px; border-style: dotted }"))) option))

      options
    )
  )
  (gnc:define-report
    'version 1
    'name "A Report Saved In GnuCash"
    'report-guid "7c7d1f1b9a5e4d0f8b2a3c4d5e6f7a8b"
    'parent-type "5123a759ceb9483abf2182d01c140e8d"
    'options-generator options-gen
    'menu-path (list gnc:menuname-custom)
    'renderer (gnc:report-template-renderer/report-guid "5123a759ceb9483abf2182d01c140e8d" "Printable Invoice")
  )
)
'''

@pytest.fixture
def saved_report(a_fresh_process):
    """A report configuration, saved the way GnuCash saves one."""
    where = _where_gnucash_keeps_them()
    where.mkdir(parents=True, exist_ok=True)
    path = where / 'saved-reports-2.8'
    if path.exists():
        pytest.skip(f'{path} exists already and is not this test\'s')
    path.write_text(A_REPORT_SAVED_IN_GNUCASH, encoding='utf-8')
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


class TestAReportSavedInGnuCash:
    """The other half of what GnuCash reads at startup.

    A report configuration saved from a report's own options dialog goes into
    `saved-reports-2.8`, and it is where a CSS of the reader's lives — the
    Layout → CSS box is a *report* option, not a stylesheet one.
    """

    def test_it_can_be_named_and_draws_the_page(self, book, saved_report,
                                                    tmp_path):
        out = tmp_path / 'page.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out),
            '--report', 'A Report Saved In GnuCash'])

        assert result.exit_code == 0, result.output
        assert INVOICE in out.read_text(encoding='utf-8')

    def test_and_the_css_it_carries_is_on_the_page(self, book, saved_report,
                                                   tmp_path):
        """Which is how a reader's own CSS reaches a printed page."""
        out = tmp_path / 'page.html'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out),
            '--report', 'A Report Saved In GnuCash']).exit_code == 0

        assert 'border-style: dotted' in out.read_text(encoding='utf-8')

    def test_it_is_drawn_with_the_options_that_were_saved(self, book,
                                                          saved_report,
                                                          tmp_path):
        """And not with the switches `print-invoice` sets elsewhere.

        The three display switches — the invoice's `notes:`, the seller's
        `contact:`, tax per account — go on the reports `print-invoice` and
        `print-bill` advertise, to show fields the ledger carries and GnuCash
        ships hidden. A saved configuration carries the choices a reader made
        in GnuCash's dialog, and setting the three switches over the top
        would override choices made deliberately on a configured page.

        So a saved configuration prints as saved: `Display/Invoice Notes` was
        not among the options saved below, and the invoice's `notes:` stay
        off the page — while the Printable Invoice, drawn by the same book a
        line later, prints the same `notes:` because the switch goes on
        there.

        Read by the notes rather than by the tax summary: the fixture book
        carries no tax table, so a missing `GST` row proves nothing about
        `Use Detailed Tax Summary`, and an assertion on the row passed with
        the switch-setting code deleted.
        """
        out = tmp_path / 'page.html'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out),
            '--report', 'A Report Saved In GnuCash']).exit_code == 0

        assert THE_INVOICES_NOTES not in out.read_text(encoding='utf-8')
        assert THE_INVOICES_NOTES in _printed(book, tmp_path)


class TestTheReportTheBookPrintsWith:
    """A book that names its own invoice report is printed with it.

    GnuCash keeps that in File → Properties → Business and reads it when its
    own Print Invoice button draws — so a reader who set their book up that
    way does not have to repeat the choice on the command line, and this asks
    the book rather than assuming a report.
    """

    def _the_book_names(self, book, guid, name):
        import ctypes

        from infrastructure.gnucash.engine import load_gnc_engine

        lib = load_gnc_engine()
        # GnuCash 3.8 and the whole 4.x line have neither the setter nor the
        # getter — measured on 4.4, 4.8 and 4.13 as well as 3.8 — so a book
        # on those builds cannot name a report, and its own printing draws
        # with the default. There is nothing to state there, rather than
        # something stated differently.
        #
        # This is the first call in every test of this class, so all of them
        # skip on four of the ten supported builds: the book-option path is
        # exercised by six, not nine.
        if not hasattr(lib, 'qof_book_set_default_invoice_report'):
            pytest.skip('this GnuCash has no default-invoice-report option')
        # Three parameters, as `qofbook.h` declares it on every 5.x build:
        # `(QofBook *, const gchar *guid, const gchar *name)`. A fourth was
        # passed for a while and worked by accident — the extra integer lands
        # in a register the callee ignores under the SysV x86-64 ABI — which
        # is exactly the accident this repo's ctypes rule exists to keep out.
        setter = lib.qof_book_set_default_invoice_report
        setter.restype = None
        setter.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.NORMAL)
        try:
            setter(int(repo.book.instance), guid.encode(), name.encode())
            repo.save()
        finally:
            repo.close()

    def test_no_flag_is_needed_for_it(self, book, saved_report, tmp_path):
        self._the_book_names(book, SAVED_REPORT_GUID,
                             'A Report Saved In GnuCash')

        out = tmp_path / 'page.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert 'border-style: dotted' in out.read_text(encoding='utf-8')

    def test_and_the_run_says_which_report_the_book_named(self, book,
                                                          saved_report,
                                                          tmp_path):
        """Nobody typed it, so nothing on screen would otherwise say it.

        A saved configuration carries the options it was saved with, and this
        tool's three display switches are not among them — so a page can state
        one combined `Tax` figure where the same book prints GST and PST by
        name elsewhere. That is the configuration doing what it was saved to
        do, and the reader is told which one it was.
        """
        self._the_book_names(book, SAVED_REPORT_GUID,
                             'A Report Saved In GnuCash')

        out = tmp_path / 'page.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert 'Default Invoice Report' in result.output, result.output
        # Both: the name is what the reader chose in the chooser and can
        # recognise, and the guid is what identifies it when two of their
        # configurations are called something similar.
        assert 'A Report Saved In GnuCash' in result.output, result.output
        assert SAVED_REPORT_GUID in result.output, result.output

    def test_a_stock_report_it_names_is_not_called_a_saved_one(self, book,
                                                               tmp_path):
        """Tax Invoice is GnuCash's own, and `print-invoice` sets the three
        switches on Tax Invoice.

        The chooser that writes this book option lists it — `taxinvoice.scm`
        declares `'hook 'invoice`, which is what `gnc:report-is-invoice-report?`
        collects — so a book can arrive here naming it without anyone having
        saved anything. Told from the invoice family alone, such a book was
        informed that its page carried options somebody saved and went without
        the three switches, while the switches were being set. Nothing to say,
        so nothing is said.
        """
        from services.gnucash_report import TAX_INVOICE_GUID

        self._the_book_names(book, TAX_INVOICE_GUID, 'Tax Invoice')

        out = tmp_path / 'page.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert 'display switches' not in result.output, result.output
        assert INVOICE in out.read_text(encoding='utf-8')

        # And what *is* said about that page names the report the way the
        # reader knows it. Tax Invoice has neither the company block nor the
        # client one, so this book's GST number is dropped and said so — a
        # sentence that would otherwise open with a bare guid out of File →
        # Properties, which nobody typed and nobody has seen.
        assert f'Tax Invoice ({TAX_INVOICE_GUID})' in result.output, \
            result.output

    def test_and_one_that_draws_nothing_prints_too(self, book,
                                                       _a_saved_report,
                                                       tmp_path):
        """A registered report with no `General / Invoice Number` option
        cannot be told which invoice to draw. Typed on the command line
        that is a sentence; named by the *book* it is the Printable Invoice,
        for the reason an unregistered guid is — the setting was made in File
        → Properties, and the refusal would quote a guid nobody typed here.

        GnuCash's own chooser cannot offer such a report, so a book reaching
        this was written by hand or by another tool.
        """
        _a_saved_report(A_REPORT_THAT_DRAWS_NOTHING)
        self._the_book_names(book, A_REPORTLESS_GUID, 'Account Summary')

        out = tmp_path / 'page.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert INVOICE in out.read_text(encoding='utf-8')
        # And said as what it is. All three ways a book's report fails end
        # with the Printable Invoice drawing, so the sentence is the only
        # thing that separates them — and "nothing is registered under that
        # guid, look in the saved-report files" would send this reader to a
        # file that is there and is not the problem.
        assert 'prints no invoice or bill' in result.output, result.output
        assert 'nothing is registered' not in result.output, result.output

    def test_one_this_gnucash_does_not_have_still_prints(self, book,
                                                         tmp_path):
        """A configuration saved in GnuCash is a file in the GnuCash it was
        saved in.

        The reader's laptop has it; the build server printing the same book
        does not, and neither does a colleague. Refusing there would stop the
        book printing anywhere but on one machine — over a setting made in
        File → Properties rather than on this command line, so the refusal
        would name a guid nobody typed. The page draws with GnuCash's own
        report instead, and the run says so.
        """
        self._the_book_names(book, 'deadbeefdeadbeefdeadbeefdeadbeef',
                             'A Report That Is Not Here')

        out = tmp_path / 'page.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        page = out.read_text(encoding='utf-8')
        assert INVOICE in page, page[:1500]
        assert 'class="entries-table"' in page, page[:1500]
        assert 'deadbeef' in result.output, result.output


    def test_a_named_report_overrides_the_book(self, book, saved_report,
                                               tmp_path):
        """The book is asked only where the caller has said nothing.

        And nothing is said about the book's choice either: both sentences
        are about a report the reader did not pick for this run, and this run
        they picked one.
        """
        self._the_book_names(book, SAVED_REPORT_GUID,
                             'A Report Saved In GnuCash')

        out = tmp_path / 'page.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out),
            '--report', 'Printable Invoice'])

        assert result.exit_code == 0, result.output
        page = out.read_text(encoding='utf-8')
        assert 'border-style: dotted' not in page, page[:2500]
        assert 'Default Invoice Report' not in result.output, result.output

    def test_a_bill_is_printed_with_it_too(self, book, saved_report,
                                           tmp_path):
        """It is called the Default *Invoice* Report, and a bill is drawn by
        the invoice report — so the one setting decides both, which is why a
        bill printed here follows it too."""
        self._the_book_names(book, SAVED_REPORT_GUID,
                             'A Report Saved In GnuCash')

        out = tmp_path / 'bill.html'
        result = CliRunner().invoke(cli, [
            'print-bill', str(book), A_BILL,
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert 'border-style: dotted' in out.read_text(encoding='utf-8')


#: Two configurations under one name — what "Save Report Configuration As…"
#: leaves behind twice, its name field being pre-filled with the report each
#: was saved from. Reading the saved-report files brings both here, and
#: `--report "<that name>"` then answers to neither.
#:
#: Each under a guid of its own, and under a name no other test uses, because
#: a report registers for the life of the *process* and `gnc:define-report`
#: has no way back: reusing a guid registers nothing at all (measured — the
#: second definition logs "report-guid that is a duplicate" and is dropped),
#: and reusing the name `Printable Invoice` would leave every later test in
#: the run unable to name that report.
A_NAME_TWO_CONFIGURATIONS_ANSWER_TO = 'My Invoice'
TWO_CONFIGURATIONS_OF_ONE_NAME = (
    A_REPORT_SAVED_IN_GNUCASH.replace(
        SAVED_REPORT_GUID, '9f1e2d3c4b5a60718293a4b5c6d7e8f9')
    .replace('"A Report Saved In GnuCash"',
             f'"{A_NAME_TWO_CONFIGURATIONS_ANSWER_TO}"')
    + A_REPORT_SAVED_IN_GNUCASH.replace(
        SAVED_REPORT_GUID, '0a1b2c3d4e5f60718293a4b5c6d7e8f0')
    .replace('"A Report Saved In GnuCash"',
             f'"{A_NAME_TWO_CONFIGURATIONS_ANSWER_TO}"'))

#: The same guid in another case. GnuCash writes lowercase and refuses an
#: exact duplicate, so two entries answering to one guid takes a hand-edited
#: file — and `--report <guid>` matches without regard to case, because a guid
#: is hex.
THE_SAME_GUID_IN_CAPS = \
    A_REPORT_SAVED_IN_GNUCASH.replace(SAVED_REPORT_GUID,
                                      SAVED_REPORT_GUID.upper()) \
                             .replace('"A Report Saved In GnuCash"',
                                      '"A Report Saved In Caps"')


#: A report that registers and cannot be told which invoice to draw: its
#: options carry no `General / Invoice Number`. GnuCash's own chooser offers
#: only reports hooked to `'invoice`, all of which have the option, so a book
#: naming this was written by hand or by another tool.
#:
#: Options declared the way both eras declare them — `gnc-new-optiondb` on
#: 4.x/5.x, `gnc:new-options` on 3.8 — asked of the build rather than
#: inferred from its version.
A_REPORTLESS_GUID = '4d5e6f708192a3b4c5d6e7f809a1b2c3'
A_REPORT_THAT_DRAWS_NOTHING = '''
(gnc:define-report
  'version 1
  'name "A Report With No Invoice Option"
  'report-guid "4d5e6f708192a3b4c5d6e7f809a1b2c3"
  'menu-path (list gnc:menuname-custom)
  'options-generator (lambda ()
    (if (defined? 'gnc-new-optiondb) (gnc-new-optiondb) (gnc:new-options)))
  'renderer (lambda (report-obj) (gnc:make-html-document)))
'''


@pytest.fixture
def _a_saved_report(a_fresh_process):
    """Write a `saved-reports-2.8` of the caller's choosing, then read it."""
    where = _where_gnucash_keeps_them()
    where.mkdir(parents=True, exist_ok=True)
    path = where / 'saved-reports-2.8'
    if path.exists():
        pytest.skip(f'{path} exists already and is not this test\'s')

    def write(text):
        path.write_text(text, encoding='utf-8')
        return path

    try:
        yield write
    finally:
        path.unlink(missing_ok=True)


class TestWhenTwoReportsAnswerToOneName:
    """Reading the saved-report files can make a name ambiguous.

    Nothing the reader typed changed, so the refusal says where the second
    registration came from and which files hold configurations.
    """

    def test_the_refusal_says_where_the_second_one_came_from(
            self, book, _a_saved_report, tmp_path):
        _a_saved_report(TWO_CONFIGURATIONS_OF_ONE_NAME)

        out = tmp_path / 'page.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out),
            '--report', A_NAME_TWO_CONFIGURATIONS_ANSWER_TO])

        assert result.exit_code != 0, result.output
        assert 'saved-reports-2.8' in result.output, result.output
        assert 'saved in GnuCash' in result.output, result.output

    def test_but_a_book_naming_a_guid_two_answer_to_still_prints(
            self, book, _a_saved_report, tmp_path):
        """A guid the book names has two ways to fail — no match, and more
        than one — and both are a setting made in File → Properties rather
        than on this command line. The page draws either way."""
        _a_saved_report(A_REPORT_SAVED_IN_GNUCASH + THE_SAME_GUID_IN_CAPS)
        TestTheReportTheBookPrintsWith()._the_book_names(
            book, SAVED_REPORT_GUID, 'A Report Saved In GnuCash')

        out = tmp_path / 'page.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert INVOICE in out.read_text(encoding='utf-8')
        # The sentence covers both ways the lookup declines, this being the
        # one where the configuration *is* on the machine — twice — so
        # "nothing is registered under it" alone would send the reader
        # looking for a missing file that is present.
        assert 'two configurations' in result.output, result.output
        assert 'saved-reports-2.8' in result.output, result.output


class TestTwoStylesheetsForOnePage:
    """A book carrying CSS, and a saved configuration carrying CSS.

    The book wins: `set-invoice-style` writes onto the options the
    configuration generated, so the setting made for the book's own invoices
    is the one on the page. `--clear-css` takes the book's back off and
    leaves the configuration's, which is the way back for a reader who set
    the styling in GnuCash's dialog and wants it.
    """

    A_STYLE = '.entries-table * { border-style: double }'

    def test_the_books_css_is_the_one_on_the_page(self, book, saved_report,
                                                  tmp_path):
        style = tmp_path / 'invoice.css'
        style.write_text(self.A_STYLE, encoding='utf-8')
        assert CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                        '--css', str(style)]).exit_code == 0

        out = tmp_path / 'page.html'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out),
            '--report', 'A Report Saved In GnuCash']).exit_code == 0

        page = out.read_text(encoding='utf-8')
        assert 'border-style: double' in page, page[:2500]
        assert 'border-style: dotted' not in page, page[:2500]

    def test_and_clearing_it_leaves_the_configurations(self, book,
                                                       saved_report,
                                                       tmp_path):
        style = tmp_path / 'invoice.css'
        style.write_text(self.A_STYLE, encoding='utf-8')
        assert CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                        '--css', str(style)]).exit_code == 0
        assert CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                        '--clear-css']).exit_code == 0

        out = tmp_path / 'page.html'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out),
            '--report', 'A Report Saved In GnuCash']).exit_code == 0

        assert 'border-style: dotted' in out.read_text(encoding='utf-8')


def _rectangles_painted(pdf: Path) -> int:
    """How many rectangles a PDF draws — its borders, in other words.

    Content streams are Flate-compressed, so each is decompressed and its
    path operators counted. A page with a box round every table cell paints
    many; a page whose borders were dropped paints few.
    """
    import zlib

    data = pdf.read_bytes()
    painted = 0
    for stream in re.finditer(rb'stream\r?\n(.*?)endstream', data, re.S):
        try:
            body = zlib.decompress(stream.group(1))
        except zlib.error:
            continue
        painted += len(re.findall(rb'\bre\b', body))
    return painted


def _the_sheet_this_machine_prints_on() -> tuple:
    """GTK's own default paper, in points, asked of GTK.

    Asked rather than written down, because the answer is the locale's — A4
    in most of the world, US Letter under `en_US` and `en_CA` — and a test
    naming one would pass in the images and fail on the reader's machine, or
    the other way round. In a subprocess, so a GTK main loop is never
    initialised in the process holding an open book and a live Guile.
    """
    import subprocess

    from infrastructure.pdf.printing import a_display

    asking = ('import gi; gi.require_version("Gtk", "3.0")\n'
              'from gi.repository import Gtk\n'
              's = Gtk.PageSetup().get_paper_size()\n'
              'print(round(s.get_width(Gtk.Unit.POINTS)),'
              '      round(s.get_height(Gtk.Unit.POINTS)))\n')
    with a_display() as (prefix, env):
        said = subprocess.run([*prefix, sys.executable, '-c', asking],
                              capture_output=True, text=True, env=env,
                              timeout=120)
    assert said.returncode == 0, said.stderr
    width, height = said.stdout.split()
    return int(width), int(height)


class TestThePdfIsDrawnTheWayGnuCashDrawsIt:
    """The page's boxes reach the PDF, and the sheet is the machine's.

    GnuCash's report writes its borders as HTML-4 presentational attributes
    — `<table border="1.0" cellpadding="4.0">` — and WeasyPrint does not
    implement those: measured on one page, WebKit paints 97 rectangles where
    WeasyPrint paints 0, so a printed invoice had no lines round anything
    while the same invoice printed from GnuCash did.

    Not a test of the *reader's* `Table border width` reaching the PDF,
    though the fixture supplies one: the report's own stylesheet draws the
    entry table's borders whatever that setting says, so the count does not
    separate the two. What it separates is an engine that paints GnuCash's
    page from one that paints its own reading of it.
    """

    def test_the_borders_are_drawn_in_the_pdf(self, book,
                                              a_setting_of_the_readers,
                                              tmp_path):
        out = tmp_path / 'with-borders.pdf'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'pdf', '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert out.read_bytes()[:5] == b'%PDF-'
        assert _rectangles_painted(out) > 50, _rectangles_painted(out)

    def test_and_the_sheet_is_the_one_the_machine_prints_on(self, book,
                                                            a_fresh_process,
                                                            tmp_path):
        """The sheet GTK derives from the reader's locale, which is the sheet
        GnuCash starts from on the same machine — A4 under the `C` locale the
        images run in, US Letter under `en_US` or `en_CA`.

        Nothing here names a paper size. Naming one printed every reader's
        page on the author's paper, and a book that prints Letter here
        and A4 from GnuCash is the mismatch this path exists to remove — the
        same mismatch WeasyPrint produced from the other direction, laying
        the page out on its own default rather than the machine's.
        """
        out = tmp_path / 'sheet.pdf'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'pdf', '--output', str(out)]).exit_code == 0

        box = re.search(rb'/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)',
                        out.read_bytes())
        assert box is not None, 'no MediaBox in the printed PDF'
        sheet = (round(float(box.group(1))), round(float(box.group(2))))
        assert sheet == _the_sheet_this_machine_prints_on(), sheet


class TestSkippingTheReadAltogether:
    """`GNUCASH_PLAINTEXT_NO_USER_CONFIG=1`, and the page is GnuCash's own.

    Reading Scheme is evaluating it, and the directory it comes from is
    chosen by environment variables — so a run on a shared build account
    executes whatever is in that account's home directory. One variable puts
    the command back where it was: the book, the report, and nothing else.
    """

    def test_the_readers_settings_are_left_unread(self, book,
                                                  a_setting_of_the_readers,
                                                  tmp_path, monkeypatch):
        monkeypatch.setenv('GNUCASH_PLAINTEXT_NO_USER_CONFIG', '1')

        page = _printed(book, tmp_path)

        assert 'border="0' in page, page[:1500]
        assert 'border="1' not in page, page[:1500]


class TestAMachineWithNoGnuCashConfiguration:
    """The quiet path, which every other test here talks over.

    A build server has no `stylesheets-2.0` and no saved reports, and the
    read says nothing about the files it did not find. Asserted because the
    failure mode is silent in the other direction: a probe that starts
    reporting an absent file, or an unbound `gnc-build-userdata-path` landing
    in the same `catch` as an unreadable file, is three stderr lines per
    printed page — on the stream a dropped GST number is reported on —
    and every other test in this file would still pass.

    `scripts/test.sh` runs with `HOME=/tmp/home`, so the clean state is the
    one CI is in.
    """

    def test_nothing_is_said_about_files_that_are_not_there(self, book,
                                                            a_fresh_process,
                                                            tmp_path):
        where = _where_gnucash_keeps_them()
        for name in ('stylesheets-2.0', 'saved-reports-2.4',
                     'saved-reports-2.8'):
            if (where / name).exists():
                pytest.skip(f'{where / name} is somebody\'s real one')

        out = tmp_path / 'page.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), INVOICE,
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert 'could not be read' not in result.output, result.output
        assert 'stylesheets-2.0' not in result.output, result.output


class TestWhenTheFileIsUnusable:
    def test_a_broken_one_does_not_cost_the_page(self, book,
                                                     a_fresh_process,
                                                     tmp_path):
        """The reader may not know the file is there, it is not this
        invoice's fault, and the page can still be drawn from what did
        load.

        `a_fresh_process` because without it this asserts nothing: the flag
        would already be set by whatever rendered earlier in the run, the
        broken file would never be opened, and the page would draw for a
        reason that has nothing to do with the `catch` this is here for.
        """
        where = _where_gnucash_keeps_them()
        where.mkdir(parents=True, exist_ok=True)
        path = where / 'stylesheets-2.0'
        if path.exists():
            pytest.skip(f'{path} exists already and is not this test\'s')
        path.write_text('(this is not scheme', encoding='utf-8')
        out = tmp_path / 'page.html'
        try:
            result = CliRunner().invoke(cli, [
                'print-invoice', str(book), INVOICE,
                '--format', 'html', '--output', str(out)])
        finally:
            path.unlink(missing_ok=True)

        assert result.exit_code == 0, result.output
        assert INVOICE in out.read_text(encoding='utf-8')

    def test_and_the_reader_is_told_which_file(self, book, a_fresh_process,
                                               tmp_path):
        """Otherwise the refusal blames them.

        One bad entry aborts the whole file, so every saved report in it goes
        unregistered — and `--report "My Invoice"` then fails with "no report
        of that name is registered on this build", which sends the reader to
        look at their locale for a problem in their own file.
        """
        where = _where_gnucash_keeps_them()
        where.mkdir(parents=True, exist_ok=True)
        path = where / 'saved-reports-2.8'
        if path.exists():
            pytest.skip(f'{path} exists already and is not this test\'s')
        path.write_text('(this is not scheme', encoding='utf-8')
        out = tmp_path / 'page.html'
        try:
            result = CliRunner().invoke(cli, [
                'print-invoice', str(book), INVOICE,
                '--format', 'html', '--output', str(out)])
        finally:
            path.unlink(missing_ok=True)

        assert result.exit_code == 0, result.output
        assert 'saved-reports-2.8' in result.output, result.output
        assert 'could not be read' in result.output, result.output
