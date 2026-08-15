"""Customising a printed document means writing a GnuCash report.

There is no template of this project's to override, because there is no layout
of this project's — the page is a GnuCash report, and GnuCash's reports are
Scheme files that call `gnc:define-report`. So the way to change what a
document looks like is to write one of those, which is the same thing every
report GnuCash ships is, and name it:

    print-invoice book.gnucash INV-001 -o inv.pdf \\
        --report-file my-invoice.scm --report "My Invoice"

`--report` alone picks between the reports already registered — GnuCash ships
several — and `--report-file` loads yours first so it is registered by the
time it is looked for.

What this file pins is that the seam is real: a report written here, in a
fixture, draws the page instead of GnuCash's, and its own words come out.

**Before naming a report by guid in a new test, read this.** A report
registers into a registry that lives as long as the process and that nothing
resets, so a fixture loaded by one test is still registered for every test
after it — and pytest's collection order decides which those are. Two of the
fixtures here register deliberately awkward things:

* `two_reports_of_one_name.scm` collides two reports of its own, under a name
  nothing else uses, precisely so it cannot affect anything else;
* `a_report_reusing_a_shipped_guid_in_caps.scm` cannot do that, because the
  collision it exists to test *is* with a shipped guid. It leaves
  `5123A759…` — the Printable Invoice's, capitalised — registered for the
  rest of the run, which makes `--report 5123a759…` ambiguous from then on.
  It leaves a second report behind too, `5b1e5b1e…` / "A Report In Caps That
  Collides With Nothing", which is there so the refusal's list can be checked
  for naming only what collided. That one collides with nothing, as it says,
  but it is registered for the rest of the run like the other.

So a test naming the **Printable Invoice by guid** will pass alone and refuse
for ambiguity once it collects after that one. Name it by name, or use
another report's guid — `TestChoosingBetweenTheReportsGnuCashShips` uses
Fancy Invoice's for exactly this reason.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
LEDGER = str(FIXTURES / 'q019_unposted_cash_with_tax.txt')
OWN_REPORT = str(FIXTURES / 'a_report_of_your_own.scm')


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(path), ACCOUNTS])
    assert made.exit_code == 0, made.output
    imported = CliRunner().invoke(cli, [
        'import', str(path), LEDGER, '--include-business-objects'])
    assert imported.exit_code == 0, imported.output
    return path


BLOCKS = ('company-table', 'client-table')


def _row_sits_in_its_own_block(page: str, block: str) -> bool:
    """Whether `<block>-extra` landed between its own anchor and the next
    block's, rather than merely somewhere on the page.

    Bounded by the *other* block rather than by the next `<div>`, because
    these blocks contain divs of their own — the company name is one — so
    "before the next div" is false for a row that is exactly where it belongs.
    """
    anchor = page.find(f'class="{block}"')
    row = page.find(f'{block}-extra', anchor) if anchor >= 0 else -1
    if anchor < 0 or row < 0:
        return False
    following = [page.find(f'class="{other}"') for other in BLOCKS
                 if other != block]
    nxt = min([at for at in following if at > anchor], default=len(page))
    return row < nxt


def _printed(book, tmp_path, *extra):
    out = tmp_path / 'inv.html'
    result = CliRunner().invoke(cli, [
        'print-invoice', str(book), 'INV-Q19-CASH-TAX-200', '--format', 'html',
        '--output', str(out), *extra])
    assert result.exit_code == 0, result.output
    return out.read_text(encoding='utf-8')


class TestAReportOfYourOwn:
    def test_it_draws_the_page(self, book, tmp_path):
        page = _printed(book, tmp_path, '--report-file', OWN_REPORT,
                        '--report', 'A Report Of Your Own')

        assert 'THIS PAGE WAS DRAWN BY A REPORT OF MY OWN' in page, page[:2000]

    def test_it_is_handed_the_document_that_was_asked_for(self, book,
                                                          tmp_path):
        """Not just any page: the one `print-invoice` was given."""
        page = _printed(book, tmp_path, '--report-file', OWN_REPORT,
                        '--report', 'A Report Of Your Own')

        assert 'document: INV-Q19-CASH-TAX-200' in page, page[:2000]

    @pytest.mark.parametrize('guid', [
        'B0DCB0DCB0DCB0DCB0DCB0DCB0DCB0DC',   # as the fixture registers it
        'b0dcb0dcb0dcb0dcb0dcb0dcb0dcb0dc',   # as a reader might type it
        'b0dcb0dc-b0dc-b0dc-b0dc-b0dcb0dcb0dc',   # as `uuidgen` prints it
        'B0DCB0DC-B0DC-B0DC-B0DC-B0DCB0DCB0DC',
    ])
    def test_it_can_be_named_by_guid_in_either_case(self, book, tmp_path,
                                                    guid):
        """The registry is a hash compared with `equal?`, so case has to match
        exactly — and neither case is the safe guess. GnuCash's own reports
        register lowercase guids, so looking up only what was typed refused
        `--report 5123A759…`; a `.scm` written from `uuidgen` on macOS says
        `B0DC…`, so lowercasing unconditionally refuses that instead. Both are
        tried, and this fixture registers the uppercase half."""
        page = _printed(book, tmp_path, '--report-file', OWN_REPORT,
                        '--report', guid)

        assert 'THIS PAGE WAS DRAWN BY A REPORT OF MY OWN' in page, page[:2000]

    DASHED = str(FIXTURES / 'a_report_whose_guid_has_dashes.scm')

    @pytest.mark.parametrize('guid', [
        '7cd07cd0-7cd0-7cd0-7cd0-7cd07cd07cd0',   # as the `.scm` registers it
        '7cd07cd07cd07cd07cd07cd07cd07cd0',       # and without the dashes
        '7CD07CD0-7CD0-7CD0-7CD0-7CD07CD07CD0',   # and in the other case
    ])
    def test_a_report_that_registered_a_dashed_guid_is_reachable(
            self, book, tmp_path, guid):
        """`uuidgen` prints dashes, so a first `.scm` has them in it.

        Which makes this work on both sides or on neither. Stripping only
        what the reader types compares a bare 32 characters against a dashed
        registry key; leaving both alone fails for anyone who typed the
        undashed form. Either way the refusal is the one about translated
        names, for a string plainly a guid.
        """
        page = _printed(book, tmp_path, '--report-file', self.DASHED,
                        '--report', guid)

        assert 'A REPORT WHOSE GUID CAME FROM UUIDGEN' in page, page[:2000]

    def test_a_report_with_a_dashed_guid_can_be_named_too(self, book,
                                                          tmp_path):
        """And by name, which is the ordinary way — the guid handling must not
        have cost that."""
        page = _printed(book, tmp_path, '--report-file', self.DASHED,
                        '--report', 'A Report With A Dashed Guid')

        assert 'A REPORT WHOSE GUID CAME FROM UUIDGEN' in page, page[:2000]

    def test_its_own_options_are_left_alone(self, book, tmp_path):
        """This tool empties `Extra Notes` on the reports it advertises, to
        take out "Thank you for your patronage!". Fired at every report, that
        silently blanks whatever a reader declared under the same name — the
        same overreach as demanding a `div` of someone else's page."""
        page = _printed(book, tmp_path, '--report-file', OWN_REPORT,
                        '--report', 'A Report Of Your Own')

        assert 'extra notes: MY OWN EXTRA NOTES' in page, page[:2000]

    def test_an_empty_name_is_no_name_and_draws_the_default(self, book,
                                                            tmp_path):
        """`--report "$REPORT"` with the variable unset is how a shell script
        arrives here. Read as a name it matched nothing, and the refusal then
        filled the blank in with the default's own name — telling the reader
        that `Printable Invoice`, which they never typed and which is
        registered, is not registered on this build."""
        assert _printed(book, tmp_path, '--report', '') == \
            _printed(book, tmp_path)

    def test_the_default_is_still_gnucashs_own(self, book, tmp_path):
        """Nothing changes for anyone who asks for nothing."""
        page = _printed(book, tmp_path)

        assert '<div class="invoice-title">Invoice #INV-Q19-CASH-TAX-200</div>'\
            in page, page[:2000]
        assert 'A REPORT OF MY OWN' not in page


class TestABookWithRegistrationNumbersAndFreeText:
    """A book with something to splice in, against each kind of page.

    The two blocks this project adds — the GST and PST numbers, and the
    `extra_text` lines — go into `company-table` and `client-table`. Which
    reports have those, measured, decides what each page here should show:

    | page | blocks | so |
    |---|---|---|
    | the default (Printable Invoice) | both | spliced, and refused without |
    | Fancy Invoice, Easy Invoice | both | spliced |
    | Tax Invoice | neither | printed as it is |
    | a report of your own | neither | printed as it is |

    Every other test in this file uses a book carrying none of it, where all
    four of those are the same page — which is why nothing here caught either
    half of the rule.
    """

    EXTRA = str(FIXTURES / 'a_document_with_extra_text.txt')

    @pytest.fixture
    def book_with_extras(self, tmp_path):
        path = tmp_path / 'extras.gnucash'
        built = CliRunner().invoke(cli, ['import', '--new', str(path),
                                         self.EXTRA,
                                         '--include-business-objects'])
        assert built.exit_code == 0, built.output
        return path

    def test_a_report_of_your_own_still_draws_it(self, book_with_extras,
                                                 tmp_path):
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book_with_extras), 'INV-EXTRA-001',
            '--format', 'html', '--output', str(out),
            '--report-file', OWN_REPORT, '--report', 'A Report Of Your Own'])

        assert result.exit_code == 0, result.output
        assert 'THIS PAGE WAS DRAWN BY A REPORT OF MY OWN' in \
            out.read_text(encoding='utf-8')

    def _printed_with(self, book_with_extras, tmp_path, *extra):
        # Named after the flags so two calls in one test do not share a file,
        # with everything that is not a letter or digit flattened: one of them
        # is a path, and its separators would name directories that do not
        # exist.
        stem = re.sub(r'[^A-Za-z0-9]+', '_', ''.join(extra))[:40] or 'default'
        out = tmp_path / f'inv_{stem}.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book_with_extras), 'INV-EXTRA-001',
            '--format', 'html', '--output', str(out), *extra])
        assert result.exit_code == 0, result.output
        return out.read_text(encoding='utf-8')

    def test_what_it_prints_is_its_own_and_nothing_is_spliced_in(
            self, book_with_extras, tmp_path):
        """The registration numbers are on the book, not owed to every page.

        A report of your own prints what it prints; if it wants the GST
        number it reads `Business/Company GST Number` as it reads the company
        name. What must not happen is this project deciding its layout for it.
        """
        page = self._printed_with(book_with_extras, tmp_path,
                                  '--report-file', OWN_REPORT,
                                  '--report', 'A Report Of Your Own')

        assert 'company-table-extra' not in page, page[:2000]
        assert 'client-table-extra' not in page, page[:2000]

    def test_the_default_page_carries_them(self, book_with_extras, tmp_path):
        """And nothing about the above weakens the page that does owe them."""
        page = self._printed_with(book_with_extras, tmp_path)

        assert 'GST: 111222333RT0001' in page, page[-2000:]
        assert 'Remit to: Bank 000-111' in page, page[-2000:]

    @pytest.mark.parametrize('name', ['Fancy Invoice', 'Easy Invoice'])
    def test_a_sibling_with_the_same_page_furniture_carries_them_too(
            self, book_with_extras, tmp_path, name):
        """Not spliced only into the default page — into every page built to
        hold them.

        Fancy and Easy are the same `invoice.scm` as Printable with different
        option defaults, so they write the same `company-table` and
        `client-table`. Left out of the splice they would print a Canadian
        book's invoice with no GST number on it, which is not an invoice —
        and the reader asked for a different *layout*, not for their
        registration to be dropped.
        """
        page = self._printed_with(book_with_extras, tmp_path, '--report', name)

        assert 'GST: 111222333RT0001' in page, page[-2000:]
        assert 'Portal: portal.example.test/acme' in page, page[-2000:]

        # And in the seller's own block rather than merely somewhere on the
        # page. The row goes in at the first `</tbody>` *after* the anchor, so
        # a report whose `company-table` div did not itself close a tbody
        # would put the GST number in whatever table does — still passing a
        # substring check, on a document where it sits under the customer's
        # address or among the line items.
        assert _row_sits_in_its_own_block(page, 'company-table'), page[:3000]
        assert _row_sits_in_its_own_block(page, 'client-table'), page[:3000]

    FROM_INVOICE_SCM = str(FIXTURES /
                           'a_report_of_your_own_from_invoice_scm.scm')

    def test_your_own_report_that_kept_the_blocks_gets_them(
            self, book_with_extras, tmp_path):
        """README's own instruction is "start from `invoice.scm`", and a
        reader who does keeps `make-company-table` and `make-client-table`.

        So their page has somewhere to put the registration numbers and they
        go in — which is what README promises, and the one branch of
        `_with_extra_row` no other fixture reaches: the block is there and
        `required` is false. Every other `.scm` here draws a bare paragraph
        and exercises the opposite half.

        Without this, making a report of the reader's own skip the splice
        outright would read as a tidy simplification, leave the suite green,
        and print a Canadian book's invoice with no GST number on it and no
        warning either.
        """
        page = self._printed_with(
            book_with_extras, tmp_path,
            '--report-file', self.FROM_INVOICE_SCM,
            '--report', 'A Report From Invoice Scm')

        assert 'A PAGE THAT KEPT GNUCASH\'S BLOCKS' in page, page[:2000]
        assert 'GST: 111222333RT0001' in page, page[-2500:]
        assert 'Portal: portal.example.test/acme' in page, page[-2500:]
        assert _row_sits_in_its_own_block(page, 'company-table'), page[-2500:]
        assert _row_sits_in_its_own_block(page, 'client-table'), page[-2500:]

    TEXTUAL_BLOCK = str(FIXTURES /
                        'a_report_whose_company_block_is_not_a_table.scm')

    def test_a_block_with_no_table_in_it_is_nowhere_to_put_anything(
            self, book_with_extras, tmp_path):
        """Found is not the same as placeable, and the difference had a cost.

        A reader who keeps `company-table` but writes the seller's details as
        text, laying the line items out in a table below, has a block with no
        `</tbody>` of its own. Taken as the first one after the anchor, that
        is the line items' — so the GST and PST numbers went in as a row
        **among the invoice lines**, with no refusal (the anchor was found)
        and no warning (same reason).
        """
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book_with_extras), 'INV-EXTRA-001',
            '--format', 'html', '--output', str(out),
            '--report-file', self.TEXTUAL_BLOCK,
            '--report', 'A Report With A Textual Block'])

        assert result.exit_code == 0, result.output
        page = out.read_text(encoding='utf-8')
        assert 'MY COMPANY, WRITTEN OUT AS TEXT' in page, page[:2000]
        # Not among the line items, and not anywhere else on the page either.
        assert 'GST: 111222333RT0001' not in page, page
        assert 'company-table-extra' not in page, page

        # And said out loud, though this is a report of the reader's own,
        # because they kept `class="company-table"` — which is the signal
        # README uses to say the registration numbers come with you. A page
        # with no such block is laid out some other way and says nothing; a
        # page that has one and cannot hold the row would otherwise drop a
        # GST number from someone with every reason to think it is printed.
        assert 'with no table in it' in result.output, result.output
        assert 'no document printed in this run states it' in result.output, \
            result.output

    def test_a_report_with_no_such_blocks_is_left_alone(self, book_with_extras,
                                                        tmp_path):
        """Tax Invoice builds its page from an eguile template and writes
        neither block — measured. That is its design, not a build this tool
        does not know, so it prints rather than being refused for it."""
        page = self._printed_with(book_with_extras, tmp_path,
                                  '--report', 'Tax Invoice')

        assert 'INV-EXTRA-001' in page, page[:2000]
        assert 'company-table-extra' not in page, page[:2000]

    def test_but_it_says_out_loud_what_it_could_not_print(self,
                                                          book_with_extras,
                                                          tmp_path):
        """Printing anyway is right; printing silently is not.

        Tax Invoice is a report this tool names, loads the module for and
        documents, so a reader can reach it with one flag — and on a book
        carrying a GST number it then prints a document stating none, exit 0.
        README warns, and nobody re-reads README while typing a flag.
        """
        out = tmp_path / 'tax.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book_with_extras), 'INV-EXTRA-001',
            '--format', 'html', '--output', str(out),
            '--report', 'Tax Invoice'])

        assert result.exit_code == 0, result.output
        assert 'GST: 111222333RT0001' in result.output, result.output
        assert 'no document printed in this run states it' in result.output, \
            result.output

    def test_and_says_nothing_of_the_kind_for_a_report_of_your_own(
            self, book_with_extras, tmp_path):
        """Their page, their layout — the numbers are on the book and a report
        that wants them reads them. A warning here would be this project
        second-guessing a page it was told to draw."""
        out = tmp_path / 'own.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book_with_extras), 'INV-EXTRA-001',
            '--format', 'html', '--output', str(out),
            '--report-file', OWN_REPORT, '--report', 'A Report Of Your Own'])

        assert result.exit_code == 0, result.output
        assert 'states it' not in result.output, result.output

    def test_a_whole_book_says_it_once(self, book_with_extras, tmp_path):
        """One process, many documents, one page layout — so each sentence
        once, not once per document.

        The fixture holds two invoices, and what a report's page can hold is a
        property of the report: both drop the same two blocks. Said per
        document that is four lines for a two-document book, and a hundred for
        a book of fifty.
        """
        outdir = tmp_path / 'out'
        one = CliRunner().invoke(cli, [
            'print-invoice', str(book_with_extras), 'INV-EXTRA-001',
            '--format', 'html', '--output', str(tmp_path / 'one.html'),
            '--report', 'Tax Invoice'])
        assert one.exit_code == 0, one.output

        whole = CliRunner().invoke(cli, [
            'print-invoice', str(book_with_extras), '*', '--format', 'html',
            '--output', f'{outdir}/', '--report', 'Tax Invoice'])
        assert whole.exit_code == 0, whole.output
        assert len(list(outdir.glob('*.html'))) == 2, list(outdir.iterdir())

        said = 'no document printed in this run states it'
        assert whole.output.count(said) == one.output.count(said), whole.output
        # And it claims the run rather than a document, because that is what
        # it is deduped over: the two invoices go to two customers, so the
        # owner's block dropped different text on each and only the first is
        # named.
        assert 'the printed document does not' not in whole.output, \
            whole.output


class TestChoosingBetweenTheReportsGnuCashShips:
    """The four names README offers, each drawing the document asked for.

    Asserted on that rather than on their markup: what belongs to this project
    is that the choice reaches GnuCash and comes back with the right document,
    not what GnuCash then draws.

    `Tax Invoice` is here because it is the one that had to be *made* true.
    Its siblings live in the invoice module the setup already loads and came
    with it; Tax Invoice is a module of its own, so the name README offered
    resolved to nothing on 4.x and 5.x — measured registered by the stock
    setup on 3.8 alone. Its module is loaded now, under whichever of the two
    era spellings this build has.
    """

    # Every report a reader can reach with `--report` on a stock run. The
    # fifth arrives with Tax Invoice's module rather than being asked for —
    # measured — and being reachable is what earns it the same treatment.
    ALL_OF_THEM = ['Printable Invoice', 'Fancy Invoice', 'Easy Invoice',
                   'Tax Invoice', 'Australian Tax Invoice']

    @pytest.mark.parametrize('name', ALL_OF_THEM)
    def test_it_draws_the_document(self, book, tmp_path, name):
        page = _printed(book, tmp_path, '--report', name)

        assert 'INV-Q19-CASH-TAX-200' in page, page[:2000]

    @pytest.mark.parametrize('name', ALL_OF_THEM)
    def test_none_of_them_thanks_the_reader_for_their_patronage(
            self, book, tmp_path, name):
        """The option that empties that line is set on every report offered.

        "Thank you for your patronage!" is a text option's *default*, appended
        to every page — a sentence the seller never wrote on an invoice, and
        backwards on a bill, where it thanks the supplier for their patronage
        of you. Emptying it is one `try-set`, and a `try-set` that misses is
        silent by design, so each report has to be asked rather than assumed:
        measured, `Display/Extra Notes` is the invoice family's spelling and
        Tax Invoice keeps the same row under `Notes`, so that page carried the
        line until both were set.
        """
        page = _printed(book, tmp_path, '--report', name)

        assert 'patronage' not in page.lower(), page[-1500:]

    def test_they_are_not_all_the_same_page(self, book, tmp_path):
        """Or the name would be reaching GnuCash and changing nothing."""
        pages = {name: _printed(book, tmp_path, '--report', name)
                 for name in ('Printable Invoice', 'Fancy Invoice',
                              'Easy Invoice', 'Tax Invoice')}

        assert len(set(pages.values())) == len(pages), \
            {name: len(page) for name, page in pages.items()}

    # Fancy Invoice's, from `invoice.scm`. Fancy's rather than the Printable
    # Invoice's because `a_report_reusing_a_shipped_guid_in_caps.scm`
    # registers a capitalised spelling of *that* one into a registry nothing
    # resets, which would make this refuse for ambiguity depending on which
    # test collected first. Fancy's guid nothing else in the suite touches.
    FANCY_GUID = '3ce293441e894423a2425d7a22dd1ac6'

    # Dashed too, since README promises that spelling for these as well and
    # the treatment is what has to survive it, not just the resolution.
    FANCY_DASHED = '-'.join([FANCY_GUID[:8], FANCY_GUID[8:12],
                             FANCY_GUID[12:16], FANCY_GUID[16:20],
                             FANCY_GUID[20:]])

    @pytest.mark.parametrize('guid', [FANCY_GUID, FANCY_GUID.upper(),
                                      FANCY_DASHED, FANCY_DASHED.upper()])
    def test_one_of_gnucashs_own_named_by_guid_is_still_gnucashs(
            self, book, tmp_path, guid):
        """The form the help text and README send localized readers to.

        A guid is the same in every language, so it is what someone whose
        GnuCash lists `Facture améliorée` has to type — and naming a report
        that way must be the same as naming it by name, not a way around the
        treatment that comes with it. Every other guid test here goes through
        `--report-file`, where the report is the reader's and all of that is
        deliberately skipped, so this is the only path asking whether a
        *shipped* report reached by guid still gets it.
        """
        by_guid = _printed(book, tmp_path, '--report', guid)
        by_name = _printed(book, tmp_path, '--report', 'Fancy Invoice')

        assert by_guid == by_name
        # And the treatment came with it: tax named per account, the
        # report's own marketing line taken out.
        assert 'GST' in by_guid, by_guid[-2000:]
        assert 'PST' in by_guid, by_guid[-2000:]
        assert 'patronage' not in by_guid.lower(), by_guid[-1500:]

    def test_the_default_is_the_printable_invoice(self, book, tmp_path):
        assert _printed(book, tmp_path) == \
            _printed(book, tmp_path, '--report', 'Printable Invoice')

    @pytest.mark.parametrize('name', ['Printable Invoice', 'Fancy Invoice',
                                      'Easy Invoice'])
    def test_the_family_names_each_tax_rather_than_adding_them_up(
            self, book, tmp_path, name):
        """`Display/Use Detailed Tax Summary`, on all three that have it.

        A Canadian invoice has to state the GST/HST *amount*, and GST + PST
        added into one `Tax` figure does not state it — which is why this tool
        sets that option rather than taking the report's default. The three
        share `invoice.scm`'s option names, so this is one assertion each
        rather than an assumption from the one that was tested.

        Tax Invoice is not here: it has no such option and states tax its own
        way, a Tax Rate and a Tax Amount column per line — measured, and the
        reason `--report` documents it as printing differently.
        """
        page = _printed(book, tmp_path, '--report', name)

        assert 'GST' in page, page[-2000:]
        assert 'PST' in page, page[-2000:]


class TestWhenTheReportIsNotThere:
    def test_a_name_nothing_is_registered_under_is_refused(self, book,
                                                           tmp_path):
        """As a sentence, not a traceback — and naming what was asked for."""
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(out),
            '--report', 'No Such Report'])

        assert result.exit_code != 0
        assert 'no report of that name' in result.output.lower(), result.output
        assert 'No Such Report' in result.output, result.output
        assert not out.exists(), 'a refused run must leave no file behind'

    def test_a_guid_nothing_is_registered_under_is_refused_the_same_way(
            self, book, tmp_path):
        """A guid is a spelling of the same question and gets the same answer.

        Passed straight to `gnc:make-report-options` it always looked like a
        real template, so an unregistered one skipped this refusal and died
        inside the option setter as a raw `wrong-type-arg` naming nothing the
        reader typed.
        """
        out = tmp_path / 'inv.html'
        absent = 'deadbeefdeadbeefdeadbeefdeadbeef'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(out), '--report', absent])

        assert result.exit_code != 0
        assert 'no report of that name' in result.output.lower(), result.output
        assert absent in result.output, result.output
        assert not out.exists()


class TestAFileWithNothingToNameIt:
    """`--report-file` on its own is refused, because it would print.

    Loading a `.scm` registers a report; it does not choose one. So this ran
    the reader's file, drew GnuCash's stock page from it, exited 0 and said
    `Wrote 1 invoice(s)` — the one outcome worse than an error, since the
    document looks right and is not the one they wrote a report for.
    """

    def test_a_report_file_alone_is_refused(self, book, tmp_path):
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(out),
            '--report-file', OWN_REPORT])

        assert result.exit_code != 0
        assert '--report' in result.output, result.output
        assert not out.exists(), 'a refused run must leave no file behind'

    def test_a_bill_is_refused_the_same_way(self, tmp_path):
        path = tmp_path / 'bills.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(path), ACCOUNTS]).exit_code == 0
        assert CliRunner().invoke(cli, [
            'import', str(path), str(FIXTURES / 'two_bills_to_print.txt'),
            '--include-business-objects']).exit_code == 0

        result = CliRunner().invoke(cli, [
            'print-bill', str(path), 'BILL-PRINT-001', '--format', 'html',
            '--output', str(tmp_path / 'b.html'), '--report-file', OWN_REPORT])

        assert result.exit_code != 0
        assert '--report' in result.output, result.output

    def test_naming_it_is_all_it_took(self, book, tmp_path):
        """The refusal is about the missing half, not about the file."""
        page = _printed(book, tmp_path, '--report-file', OWN_REPORT,
                        '--report', 'A Report Of Your Own')

        assert 'THIS PAGE WAS DRAWN BY A REPORT OF MY OWN' in page, page[:2000]


class TestWhenTwoReportsAnswerToOneName:
    """A name is only an answer while it names one report.

    `gnc:report-templates-for-each` walks a hash, so keeping the first match
    would hand back whichever the hash yielded — a different document each
    way, with nothing on the page saying which. The situation is what
    replacing one of GnuCash's pages looks like: keep the name, write the
    layout. See the fixture for why the two colliding reports are both its
    own rather than one of GnuCash's.
    """

    AMBIGUOUS = str(FIXTURES / 'two_reports_of_one_name.scm')
    NAME = 'A Name Two Reports Answer To'

    def test_it_is_refused(self, book, tmp_path):
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(out),
            '--report-file', self.AMBIGUOUS, '--report', self.NAME])

        assert result.exit_code != 0
        assert 'more than one report' in result.output, result.output
        assert not out.exists()

    def test_the_refusal_names_both_ids(self, book, tmp_path):
        """So the reader can tell them apart and pick one."""
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(tmp_path / 'i.html'),
            '--report-file', self.AMBIGUOUS, '--report', self.NAME])

        # Quoted, which is how `object->string` writes the matched ids — so
        # this pins the *list*, not a mention of an id somewhere in the prose.
        assert '"fa9cefa9cefa9cefa9cefa9cefa9ce01"' in result.output, \
            result.output
        assert '"fa9cefa9cefa9cefa9cefa9cefa9ce02"' in result.output, \
            result.output
        # And tells them what to do with the pair — which for an ambiguous
        # *name* is to say a guid, the escape the guid branch cannot offer.
        assert 'name the one you mean by its guid instead' in result.output, \
            result.output

    IN_CAPS = str(FIXTURES / 'a_report_reusing_a_shipped_guid_in_caps.scm')

    @pytest.mark.parametrize('typed', [
        '5123a759ceb9483abf2182d01c140e8d',
        '5123a759-ceb9-483a-bf21-82d01c140e8d',   # the same, as uuidgen writes
    ])
    def test_the_refusal_quotes_the_guid_as_it_was_typed(self, book, tmp_path,
                                                         typed):
        """Compared stripped, quoted as written.

        Every other refusal on this path names what the reader typed, and this
        one showed them a spelling they had not used: the dashes come out
        before the comparison, and the stripped form was what got quoted back.
        """
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(tmp_path / 'i.html'),
            '--report-file', self.IN_CAPS, '--report', typed])

        assert result.exit_code != 0
        assert 'more than one report' in result.output, result.output
        assert typed in result.output, result.output

    def test_and_says_what_to_do_about_it(self, book, tmp_path):
        """Which is not "name it by its guid" — that is the escape from an
        ambiguous *name*, and here the guid is what is ambiguous: both ids
        match every spelling of it, including either one quoted back.

        What does work is the name, since two reports colliding on a guid
        spelling usually have different names — these do. And where the names
        collide too, not loading the file does.
        """
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(tmp_path / 'i.html'),
            '--report-file', self.IN_CAPS,
            '--report', '5123a759ceb9483abf2182d01c140e8d'])

        assert 'by its name instead' in result.output, result.output
        assert 'name the one you mean by its guid' not in result.output, \
            result.output

    def test_an_innocent_file_is_not_named(self, book, tmp_path):
        """The file this run was given may have nothing to do with it.

        A collision needs two entries equal once case and dashes are set
        aside, and GnuCash's own guids are distinct — so through either
        command the colliding entry is always in the file just loaded. In one
        process it need not be: the caps file registered the collision on an
        earlier call, and a later one passing a different `--report-file` has
        nothing of its own in the pair. That file is not the one to stop
        loading, and the refusal does not say it is.
        """
        primed = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(tmp_path / 'primed.html'),
            '--report-file', self.IN_CAPS, '--report', 'A Report In Caps'])
        assert primed.exit_code == 0, primed.output

        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(tmp_path / 'i.html'),
            '--report-file', OWN_REPORT,
            '--report', '5123a759ceb9483abf2182d01c140e8d'])

        assert result.exit_code != 0
        assert 'more than one report' in result.output, result.output
        assert 'by its name instead' in result.output, result.output
        assert 'stop loading the report file' not in result.output, \
            result.output
        assert 'a_report_of_your_own' not in result.output, result.output

    def test_and_names_the_fix_and_not_only_the_ways_around_it(self, book,
                                                               tmp_path):
        """Neither escape ends it.

        A name gets today's document printed and leaves the guid ambiguous
        for every run after; not loading the file throws the report away. The
        reader copied `invoice.scm` — README tells them to — and changed the
        guid's case instead of minting one, so what ends it is minting one,
        which is always open to them because the guid is theirs to change.
        """
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(tmp_path / 'i.html'),
            '--report-file', self.IN_CAPS,
            '--report', '5123a759ceb9483abf2182d01c140e8d'])

        assert 'needs a guid of its own' in result.output, result.output

    def test_and_names_the_file_s_own_guid_rather_than_a_position(
            self, book, tmp_path):
        """"The second of these" points into a hash walk.

        `matches` is built by `gnc:report-templates-for-each`, so which id
        prints second is whichever the hash yielded — the exact
        non-determinism this refusal exists to prevent, and on a build that
        ordered them the other way it named GnuCash's own report, which there
        is no file to stop loading.
        """
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(tmp_path / 'i.html'),
            '--report-file', self.IN_CAPS,
            '--report', '5123a759ceb9483abf2182d01c140e8d'])

        assert 'registered 5123A759CEB9483ABF2182D01C140E8D' in \
            result.output, result.output
        # And only that one. The file registers a second report that collides
        # with nothing, and naming it here would send the reader to look at a
        # report with no part in this — with a list of unbounded length ahead
        # of the matched ids the message's limit exists to keep.
        assert '5b1e5b1e5b1e5b1e5b1e5b1e5b1e5b1e' not in result.output, \
            result.output

    def test_the_escape_it_offers_works(self, book, tmp_path):
        """A refusal that names a way out is worth only as much as the way
        out. Both reports are reachable by their own names."""
        mine = _printed(book, tmp_path, '--report-file', self.IN_CAPS,
                        '--report', 'A Report In Caps')
        gnucashs = _printed(book, tmp_path, '--report-file', self.IN_CAPS,
                            '--report', 'Printable Invoice')

        assert 'A REPORT WHOSE GUID IS CAPS' in mine, mine[:2000]
        assert '<div class="invoice-title">Invoice #INV-Q19-CASH-TAX-200' \
            in gnucashs, gnucashs[:2000]

    def test_two_spellings_of_one_guid_are_refused_like_two_names(
            self, book, tmp_path):
        """A guid is matched without regard to case, and the registry keeps
        case — so a `.scm` taking a shipped guid in capitals registers a
        second entry that the same `--report` matches.

        Kept to the first the hash yielded, the command would draw either
        page: the registration numbers spliced in or not, the heading check
        enforced or not, a different document each way with nothing saying
        which. The guid branch collects every match and refuses, as the name
        branch does.
        """
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(out),
            '--report-file', self.IN_CAPS,
            '--report', '5123a759ceb9483abf2182d01c140e8d'])

        assert result.exit_code != 0
        assert 'more than one report' in result.output, result.output
        # Both ids, quoted as `object->string` writes them — which is what
        # tells this apart from an id mentioned in the remedy sentence. The
        # bare-substring form passed on that prose alone, so the list the
        # refusal exists to print stopped being pinned by anything, at the
        # same moment the message grew ~300 characters against the cut that
        # once lost exactly this list.
        assert '"5123A759CEB9483ABF2182D01C140E8D"' in result.output, \
            result.output
        assert '"5123a759ceb9483abf2182d01c140e8d"' in result.output, \
            result.output
        assert not out.exists()

    @pytest.mark.parametrize('guid,drawn', [
        ('fa9cefa9cefa9cefa9cefa9cefa9ce01', 'the first'),
        ('fa9cefa9cefa9cefa9cefa9cefa9ce02', 'the second'),
    ])
    def test_a_guid_still_says_which(self, book, tmp_path, guid, drawn):
        """Which is what the refusal tells the reader to do — and it draws
        the one named, not whichever the hash would have yielded."""
        page = _printed(book, tmp_path, '--report-file', self.AMBIGUOUS,
                        '--report', guid)

        assert f'A REPORT NAMED LIKE ANOTHER: {drawn}' in page, page[:2000]


class TestAReportThatForgotItsName:
    """One nameless template must not break every name lookup after it.

    `gnc:define-report` accepts a definition with no `'name`, and a lookup
    walks every registered template — so `(string=? #f "Fancy Invoice")`
    raised, and the reader who asked for a report GnuCash ships was told
    `(wrong-type-arg …)` about a mistake in a file of theirs somewhere else.
    """

    NAMELESS = str(FIXTURES / 'a_report_that_forgot_its_name.scm')

    def test_a_name_beside_it_still_resolves(self, book, tmp_path):
        """The lookup walks past the nameless template to reach this one."""
        page = _printed(book, tmp_path, '--report-file', self.NAMELESS,
                        '--report', 'A Report That Did Name Itself')

        assert 'A REPORT THAT DID NAME ITSELF' in page, page[:2000]

    def test_and_so_does_a_report_gnucash_ships(self, book, tmp_path):
        """The cost was never local to the file with the mistake in it: one
        nameless template broke every later `--report <name>` in the
        process, including the ones the reader did not write.

        The fixture is loaded here too, rather than left to whichever sibling
        pytest happened to run first. A report registers into a registry that
        outlives the test, so relying on that is a test that passes alone
        while proving nothing — the `string?` guard could be reverted under
        it. `_loaded_report_files` makes the second load a no-op.
        """
        page = _printed(book, tmp_path, '--report-file', self.NAMELESS,
                        '--report', 'Fancy Invoice')

        assert 'INV-Q19-CASH-TAX-200' in page, page[:2000]


class TestAReportThatTakesNoDocument:
    """A registered report with no `General / Invoice Number` option.

    That option is how a document reaches a report, so one without it cannot
    be told which invoice to draw — and because it is the single write that
    is not optional, GnuCash's own error came out as it stood: `(misc-error
    (#f ~A (Attempt to write non-existent option …)))` on 4.x and 5.x, a bare
    `wrong-type-arg` out of `vector-ref` on 3.8. Every other first-attempt
    mistake in this area earns a sentence.

    Reached through `--report-file`, which is where it is reachable: GnuCash
    ships reports like this — a Balance Sheet, a Transaction Report — but a
    run of this tool loads only the invoice modules, so those are not
    registered and are refused earlier, by name. A `.scm` of the reader's own
    can be anything.
    """

    NO_DOCUMENT = str(FIXTURES / 'a_report_that_takes_no_document.scm')
    NAME = 'A Report That Takes No Document'

    def test_it_says_so_rather_than_failing_in_scheme(self, book, tmp_path):
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(out),
            '--report-file', self.NO_DOCUMENT, '--report', self.NAME])

        assert result.exit_code != 0
        assert 'does not print a document' in result.output, result.output
        assert self.NAME in result.output, result.output
        assert 'wrong-type-arg' not in result.output, result.output
        assert not out.exists()


class TestAFileThatWillNotLoad:
    """A `.scm` with a syntax error names the file, and names the load.

    Scheme is parentheses and a first attempt is often one short. The failure
    used to read "GnuCash could not render the document: (misc-error …)",
    which points at the invoice the reader asked for rather than at the file
    they wrote — and it is the likeliest of the mistakes in this area.
    """

    BROKEN = str(FIXTURES / 'a_report_that_will_not_parse.scm')

    def test_it_names_the_file_and_the_load(self, book, tmp_path):
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(out),
            '--report-file', self.BROKEN,
            '--report', 'A Report That Will Not Parse'])

        assert result.exit_code != 0
        assert 'could not be loaded' in result.output, result.output
        assert 'a_report_that_will_not_parse.scm' in result.output, \
            result.output
        assert not out.exists(), 'a refused run must leave no file behind'


class TestAReportReusingAShippedGuid:
    """GnuCash refuses a duplicate guid; this tool agrees with it.

    README says to start from GnuCash's `invoice.scm`, which carries the
    Printable Invoice's guid, so copying it without minting a new one is a
    keystroke away. Measured on 5.10 and 3.8: `gnc:define-report` logs "One of
    your reports has a report-guid that is a duplicate" and leaves the
    original in place — the copy registers nothing.

    So the page under that guid is still GnuCash's, and this pins that the
    tool decides whose report it is from the registry rather than from the
    guid having been named on a command line beside a `--report-file`.
    """

    REUSED = str(FIXTURES / 'a_report_reusing_a_shipped_guid.scm')

    def test_gnucash_keeps_its_own_report(self, book, tmp_path):
        page = _printed(book, tmp_path, '--report-file', self.REUSED,
                        '--report', 'Printable Invoice')

        assert 'THIS SHOULD NEVER DRAW' not in page, page[:2000]
        assert '<div class="invoice-title">' in page, page[:2000]

    def test_and_that_page_is_still_treated_as_gnucashs(self,
                                                        book_with_extras,
                                                        tmp_path):
        """Which is what matters: the registration numbers still go on it, and
        the "did it draw a document" check still applies to it."""
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book_with_extras), 'INV-EXTRA-001',
            '--format', 'html', '--output', str(out),
            '--report-file', self.REUSED, '--report', 'Printable Invoice'])

        assert result.exit_code == 0, result.output
        page = out.read_text(encoding='utf-8')
        assert 'GST: 111222333RT0001' in page, page[-2000:]

    def test_naming_their_own_report_says_why_it_is_not_there(self, book,
                                                              tmp_path):
        """The refusal has to name the cause, and the cause is the guid.

        This is the invocation that follows the mistake: they copied
        `invoice.scm`, changed the layout and the name, kept the guid, and
        asked for their name. GnuCash registered nothing, so the name matches
        nothing — and the refusal, written for a reader who typed a
        *translated* name, told them theirs might be one. It is English, it is
        exactly what they wrote in the file, and the problem is elsewhere.
        """
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(out),
            '--report-file', self.REUSED,
            '--report', 'Not The Printable Invoice'])

        assert result.exit_code != 0
        assert 'registered no report at all' in result.output, result.output
        assert 'guid of its own' in result.output, result.output
        assert not out.exists()

    HELPERS = str(FIXTURES / 'a_scm_of_helpers_only.scm')

    def test_a_file_of_helpers_is_told_both_causes_and_blamed_for_neither(
            self, book, tmp_path):
        """"Registered nothing" is the symptom of the guid mistake and also
        of a perfectly ordinary file.

        `--report-file` is only constrained to be accompanied by `--report`,
        so loading shared helpers beside one of GnuCash's own reports is a
        legitimate use of it — and that file registers nothing either. From
        here the two are the same fact, an empty difference, so the sentence
        names both rather than asserting the one that sends the writer of a
        helpers file to change a guid they do not have.
        """
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(out),
            '--report-file', self.HELPERS, '--report', 'A Name Of Mine'])

        assert result.exit_code != 0
        assert 'registered no report at all' in result.output, result.output
        assert 'either it defines none' in result.output, result.output
        assert not out.exists()

    def test_and_it_still_draws_the_report_that_was_named(self, book,
                                                          tmp_path):
        """Loading helpers changes nothing about which report draws."""
        page = _printed(book, tmp_path, '--report-file', self.HELPERS,
                        '--report', 'Fancy Invoice')

        assert 'INV-Q19-CASH-TAX-200' in page, page[:2000]

    @pytest.fixture
    def book_with_extras(self, tmp_path):
        path = tmp_path / 'extras.gnucash'
        built = CliRunner().invoke(cli, [
            'import', '--new', str(path),
            str(FIXTURES / 'a_document_with_extra_text.txt'),
            '--include-business-objects'])
        assert built.exit_code == 0, built.output
        return path


class TestANameIsDataAndNotCode:
    """A report name reaches a Scheme evaluator, so it is escaped on the way.

    Until `--report` existed, every string interpolated into
    `scm_c_eval_string` came from this project — a hex guid, a
    `TemporaryDirectory` path. These two come from the command line, and a
    name carrying a `"` would otherwise close the literal and leave the rest
    being read as code. Written as `f'"{name}"'` the tests below hand Guile a
    syntax error at best and an expression of the caller's choosing at worst;
    what they should get is the ordinary refusal.
    """

    @pytest.mark.parametrize('name', [
        'x") (display "elsewhere',       # closes the literal, then evaluates
        'a "quoted" report',             # the innocent version of the same
        r'back\slash',                   # the other character that escapes
        'both " and \\ together',
    ])
    def test_a_name_full_of_scheme_is_only_a_name(self, book, tmp_path, name):
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'html', '--output', str(out), '--report', name])

        assert result.exit_code != 0
        assert 'no report of that name' in result.output.lower(), result.output
        assert name in result.output, result.output
        assert not out.exists()

    def test_a_report_file_path_is_escaped_too(self, book, tmp_path):
        """The other string the command line supplies. A directory may be
        named anything, and this one is `load`ed by a Scheme expression."""
        awkward = tmp_path / 'a "quoted" dir'
        awkward.mkdir()
        copied = awkward / 'report.scm'
        copied.write_text(Path(OWN_REPORT).read_text(encoding='utf-8'),
                          encoding='utf-8')

        page = _printed(book, tmp_path, '--report-file', str(copied),
                        '--report', 'A Report Of Your Own')

        assert 'THIS PAGE WAS DRAWN BY A REPORT OF MY OWN' in page, page[:2000]


class TestWhereAReportCannotApply:
    """`--format plaintext` draws no page, so naming a report is refused.

    Ignoring it would be worse than refusing: the reader gets a document, it
    just is not the one they asked for — and `-o -` is plaintext by
    definition, which is where the silence would be hardest to notice.
    """

    def test_plaintext_with_a_report_is_refused(self, book, tmp_path):
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'plaintext', '--output', str(tmp_path / 'i.txt'),
            '--report', 'Fancy Invoice'])

        assert result.exit_code != 0
        assert 'draws no page' in result.output, result.output

    def test_plaintext_with_a_report_file_is_refused(self, book, tmp_path):
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-Q19-CASH-TAX-200',
            '--format', 'plaintext', '--output', '-',
            '--report-file', OWN_REPORT])

        assert result.exit_code != 0
        assert 'draws no page' in result.output, result.output

    def test_a_bill_is_refused_the_same_way(self, tmp_path):
        path = tmp_path / 'bills.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(path), ACCOUNTS]).exit_code == 0
        assert CliRunner().invoke(cli, [
            'import', str(path), str(FIXTURES / 'two_bills_to_print.txt'),
            '--include-business-objects']).exit_code == 0

        result = CliRunner().invoke(cli, [
            'print-bill', str(path), 'BILL-PRINT-001', '--format', 'plaintext',
            '--output', str(tmp_path / 'b.txt'), '--report', 'Fancy Invoice'])

        assert result.exit_code != 0
        assert 'draws no page' in result.output, result.output


class TestTheBillCommandTakesThemToo:
    """Wired identically, so exercised identically rather than assumed."""

    @pytest.fixture
    def bills(self, tmp_path):
        path = tmp_path / 'bills.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(path), ACCOUNTS]).exit_code == 0
        assert CliRunner().invoke(cli, [
            'import', str(path), str(FIXTURES / 'two_bills_to_print.txt'),
            '--include-business-objects']).exit_code == 0
        return path

    def test_a_report_of_your_own_draws_a_bill(self, bills, tmp_path):
        out = tmp_path / 'bill.html'
        result = CliRunner().invoke(cli, [
            'print-bill', str(bills), 'BILL-PRINT-001', '--format', 'html',
            '--output', str(out),
            '--report-file', OWN_REPORT, '--report', 'A Report Of Your Own'])

        assert result.exit_code == 0, result.output
        page = out.read_text(encoding='utf-8')
        assert 'THIS PAGE WAS DRAWN BY A REPORT OF MY OWN' in page, page[:2000]
        assert 'document: BILL-PRINT-001' in page, page[:2000]

    def test_a_report_of_your_own_lays_out_a_pdf_too(self, bills, tmp_path):
        """The format the flag defaults to, and the one a reader sends.

        Every other test here reads HTML, because that is what a page can be
        read from — but the PDF path lays that HTML out through WeasyPrint,
        and a report reaching print through `--format pdf` is the whole point
        of writing one.
        """
        out = tmp_path / 'bill.pdf'
        result = CliRunner().invoke(cli, [
            'print-bill', str(bills), 'BILL-PRINT-001', '--format', 'pdf',
            '--output', str(out),
            '--report-file', OWN_REPORT, '--report', 'A Report Of Your Own'])

        assert result.exit_code == 0, result.output
        assert out.read_bytes().startswith(b'%PDF-'), out.read_bytes()[:40]

    def test_every_document_in_a_run_is_drawn_by_it(self, bills, tmp_path):
        """The `.scm` is loaded once per process, not once per document — a
        whole-book print re-registering the same report guid for each one is
        the question that raises, and one file is the answer to it."""
        outdir = tmp_path / 'out'
        result = CliRunner().invoke(cli, [
            'print-bill', str(bills), 'BILL-PRINT-*', '--format', 'html',
            '--output', f'{outdir}/',
            '--report-file', OWN_REPORT, '--report', 'A Report Of Your Own'])

        assert result.exit_code == 0, result.output
        for bill_id in ('BILL-PRINT-001', 'BILL-PRINT-002'):
            page = (outdir / f'{bill_id}.html').read_text(encoding='utf-8')
            assert f'document: {bill_id}' in page, page[:2000]
