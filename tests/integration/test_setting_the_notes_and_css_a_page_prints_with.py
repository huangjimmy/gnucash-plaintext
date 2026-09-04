"""The two boxes a reader fills in on a printed page, set from here.

GnuCash's report options give them as **Printable Invoice → Display → Extra
Notes** and **Printable Invoice → Layout → CSS**: the sentence under a
page, and the styling of the page. Until now the only way to set either
was to open GnuCash, which is no use on a machine that prints from a script.

`set-invoice-style` sets them, and the book keeps them, so the same book
prints the same page from a laptop, a server or a build.

**They are not part of the plaintext format.** Nothing exports them and
nothing imports them — a ledger describes what a book *contains*, and how a
page is styled is not that. An export of a book carrying them is the same
file as an export of one that is not, and a book rebuilt from a ledger has
whatever styling it was configured with, not whatever the ledger's author
used.
"""

import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.conftest import a_ledger_without_the_day_it_was_written

FIXTURES = Path('tests/fixtures')
LEDGER = str(FIXTURES / 'a_book_that_prints_a_whole_invoice.txt')
INVOICE = 'INV-WHOLE-001'
A_BILL = 'BILL-WHOLE-001'

A_STYLE = '.entries-table * { border-width: 3px; border-style: dotted }'

#: The shape that actually ships: `--css` takes a *file*, and a stylesheet
#: somebody wrote runs to several lines and has quotes in it. Both are
#: characters that end a Scheme string literal if they are not handled — the
#: text is interpolated into one — so the file that reaches a page is the one
#: worth printing, rather than the single line the other tests use to say
#: which setting won.
A_STYLESHEET_SOMEBODY_WROTE = '''/* Widgets Inc. — "house style" */
.entries-table {
    border-collapse: collapse;
}
.entries-table td {
    border-width: 3px;
    border-style: dashed;
}
'''


def _book(tmp_path):
    path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    return path


def _styled(book, tmp_path, *args):
    time.sleep(1.1)     # GnuCash names its backup by the second
    result = CliRunner().invoke(cli, ['set-invoice-style', str(book), *args])
    assert result.exit_code == 0, result.output
    return result


def _printed(book, tmp_path, *args, name='page.html'):
    out = tmp_path / name
    result = CliRunner().invoke(cli, [
        'print-invoice', str(book), INVOICE, '--format', 'html',
        '--output', str(out), *args])
    assert result.exit_code == 0, result.output
    return out.read_text(encoding='utf-8')


class TestTheFooter:
    def test_what_is_set_is_what_prints(self, tmp_path):
        book = _book(tmp_path)
        _styled(book, tmp_path, '--note', 'Payment due in 30 days')

        page = _printed(book, tmp_path)

        assert 'Payment due in 30 days' in page, page[-2000:]
        assert 'patronage' not in page.lower(), page[-2000:]

    def test_and_an_empty_one_is_no_footer(self, tmp_path):
        """Which is what emptying the box in GnuCash's dialog gives."""
        book = _book(tmp_path)
        _styled(book, tmp_path, '--note', '')

        page = _printed(book, tmp_path)

        assert 'patronage' not in page.lower(), page[-2000:]

    def test_a_book_that_says_nothing_keeps_the_reports_own(self, tmp_path):
        book = _book(tmp_path)

        page = _printed(book, tmp_path)

        assert 'patronage' in page.lower(), page[-2000:]

    def test_and_a_book_can_be_put_back_to_saying_nothing(self, tmp_path):
        """`--note ""` reaches "no footer", a state of its own, so reaching
        "the book says nothing" needs `--clear-note`.

        Wanted twice over: README sends a report declaring an `Extra Notes`
        option of its own to a book carrying neither setting, and a reader
        wanting GnuCash's own sentence back cannot retype it — the default is
        `(G_ "Thank you for your patronage!")`, so a localized build prints
        something the reader has no way to spell.
        """
        book = _book(tmp_path)
        _styled(book, tmp_path, '--note', 'Payment due in 30 days')

        _styled(book, tmp_path, '--clear-note')

        page = _printed(book, tmp_path)
        assert 'patronage' in page.lower(), page[-2000:]
        assert 'Payment due in 30 days' not in page, page[-2000:]
        held = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                        '--show'])
        assert 'note: (none' in held.output, held.output


class TestTheCss:
    def test_what_is_set_is_what_the_page_carries(self, tmp_path):
        book = _book(tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_text(A_STYLE, encoding='utf-8')
        _styled(book, tmp_path, '--css', str(style))

        page = _printed(book, tmp_path)

        assert 'border-style: dotted' in page, page[:2500]

    def test_the_file_is_the_whole_stylesheet(self, tmp_path):
        """`Layout / CSS` ships filled in — the line-item borders, the table
        widths, the padding resets — so a file passed here replaces a
        stylesheet rather than adding to one, and a file holding one rule
        prints a page with no borders.

        README says so and shows the way to start from the report's own:
        print with `--clear-css` and copy the page's `<style>` block. Pinned
        here because the page changes materially and the command reads like
        an addition.
        """
        book = _book(tmp_path)
        assert 'border-collapse: collapse' in _printed(book, tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_text('.entries-table { font-size: 9pt }', encoding='utf-8')
        _styled(book, tmp_path, '--css', str(style))

        page = _printed(book, tmp_path, name='replaced.html')

        assert 'font-size: 9pt' in page, page[:3000]
        assert 'border-collapse: collapse' not in page, page[:3000]

    def test_a_stylesheet_from_a_file_arrives_whole(self, tmp_path):
        """Newlines and quotes and all: `--css` takes a file, and its text
        crosses into GnuCash inside a Scheme string literal."""
        book = _book(tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_text(A_STYLESHEET_SOMEBODY_WROTE, encoding='utf-8')
        _styled(book, tmp_path, '--css', str(style))

        page = _printed(book, tmp_path)

        for line in A_STYLESHEET_SOMEBODY_WROTE.splitlines():
            assert line in page, (line, page[:3000])

    def test_and_clearing_it_gives_the_report_its_own_back(self, tmp_path):
        book = _book(tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_text(A_STYLE, encoding='utf-8')
        _styled(book, tmp_path, '--css', str(style))
        _styled(book, tmp_path, '--clear-css')

        page = _printed(book, tmp_path)

        assert 'border-style: dotted' not in page, page[:2500]
        assert '.entries-table' in page, page[:2500]


class TestEveryReportGnuCashShips:
    """Both settings reach all five, and each box is spelled several ways.

    Read out of the shipped Scheme on 5.10 and 3.8 — the two report families
    disagree about both boxes, and the eras disagree about the footer:

        report family    footer                    styling
        invoice.scm      Display / Extra Notes     Layout / CSS
        taxinvoice.scm   Notes   / Extra Notes     Notes  / Embedded CSS
        taxinvoice 3.8   Notes   / Extra notes     Notes  / Embedded CSS

    A spelling left out is not an error anywhere — the option is asked for
    before it is written, so the page draws and the setting simply does not
    arrive. Which is why both settings are asked of every shipped report
    here: the styling had one spelling for a while, and reached the invoice
    family alone while `--show` reported the whole stylesheet as set.
    """

    ALL_OF_THEM = ['Printable Invoice', 'Fancy Invoice', 'Easy Invoice',
                   'Tax Invoice', 'Australian Tax Invoice']

    @pytest.mark.parametrize('name', ALL_OF_THEM)
    def test_the_books_footer_reaches_it(self, tmp_path, name):
        book = _book(tmp_path)
        _styled(book, tmp_path, '--note', 'A FOOTER FROM THE BOOK')

        page = _printed(book, tmp_path, '--report', name)

        assert 'A FOOTER FROM THE BOOK' in page, page[-2500:]
        assert 'patronage' not in page.lower(), page[-2500:]

    @pytest.mark.parametrize('name', ALL_OF_THEM)
    def test_and_so_does_the_books_styling(self, tmp_path, name):
        book = _book(tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_text(A_STYLE, encoding='utf-8')
        _styled(book, tmp_path, '--css', str(style))

        page = _printed(book, tmp_path, '--report', name)

        assert 'border-style: dotted' in page, page[:3000]


class TestABillIsPrintedTheSameWay:
    """The setting is on the book, so both of its pages carry it.

    `print-bill` is a second call site that renders the same way, and a
    setting that reached one of two near-identical paths is the kind of gap
    that survives a passing suite.
    """

    def test_the_footer_reaches_a_printed_bill(self, tmp_path):
        book = _book(tmp_path)
        _styled(book, tmp_path, '--note', 'Remit by EFT within 30 days')

        out = tmp_path / 'bill.html'
        result = CliRunner().invoke(cli, [
            'print-bill', str(book), A_BILL, '--format', 'html',
            '--output', str(out)])

        assert result.exit_code == 0, result.output
        page = out.read_text(encoding='utf-8')
        assert 'Remit by EFT within 30 days' in page, page[-2000:]
        assert 'patronage' not in page.lower(), page[-2000:]

    def test_and_so_does_the_css(self, tmp_path):
        book = _book(tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_text(A_STYLE, encoding='utf-8')
        _styled(book, tmp_path, '--css', str(style))

        out = tmp_path / 'bill.html'
        assert CliRunner().invoke(cli, [
            'print-bill', str(book), A_BILL, '--format', 'html',
            '--output', str(out)]).exit_code == 0

        assert 'border-style: dotted' in out.read_text(encoding='utf-8')


class TestWhateverReportDraws:
    """The book's words go on whatever report draws the page.

    A report loaded with `--report-file` goes without the three display
    switches — an opinion about what a page should show, and no business of a
    page laid out elsewhere. A footer set with `set-invoice-style` is a
    different thing: the reader wrote the sentence, onto the book, for every
    page the book prints, so the sentence reaches whichever report draws.

    The report drawn below declares a `Display/Extra Notes` of the report's
    own, which is where the two rules meet.
    """

    OWN_REPORT = str(FIXTURES / 'a_report_of_your_own.scm')

    def test_a_report_of_your_own_prints_the_books_footer(self, tmp_path):
        book = _book(tmp_path)
        _styled(book, tmp_path, '--note', 'THE BOOK SAYS THIS')

        page = _printed(book, tmp_path, '--report-file', self.OWN_REPORT,
                        '--report', 'A Report Of Your Own')

        assert 'THIS PAGE WAS DRAWN BY A REPORT OF MY OWN' in page, page[:2000]
        assert 'extra notes: THE BOOK SAYS THIS' in page, page[:2000]

    def test_and_keeps_its_own_where_the_book_says_nothing(self, tmp_path):
        """An unset setting is not an instruction, here as everywhere."""
        book = _book(tmp_path)

        page = _printed(book, tmp_path, '--report-file', self.OWN_REPORT,
                        '--report', 'A Report Of Your Own')

        assert 'extra notes: MY OWN EXTRA NOTES' in page, page[:2000]


class TestWhatTheBookHolds:
    def test_show_says_what_is_set(self, tmp_path):
        book = _book(tmp_path)
        _styled(book, tmp_path, '--note', 'Payment due in 30 days')

        result = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                          '--show'])

        assert result.exit_code == 0, result.output
        assert 'Payment due in 30 days' in result.output

    def test_show_prints_the_css_it_holds(self, tmp_path):
        """All of it, rather than saying that some is set: this is the only
        way to read back what a book carries, the file it came from being
        read once and not needed again."""
        book = _book(tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_text(A_STYLE, encoding='utf-8')
        _styled(book, tmp_path, '--css', str(style))

        result = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                          '--show'])

        assert result.exit_code == 0, result.output
        assert A_STYLE in result.output, result.output

    def test_a_footer_set_to_nothing_reads_as_set(self, tmp_path):
        """`note: ` on its own reads as truncated output, and telling a
        footer set empty from a book naming none is what `--show` is for —
        the two print different pages."""
        book = _book(tmp_path)
        _styled(book, tmp_path, '--note', '')

        result = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                          '--show'])

        assert result.exit_code == 0, result.output
        assert 'empty' in result.output, result.output
        assert 'none' not in result.output, result.output

    def test_and_says_when_neither_is_set(self, tmp_path):
        book = _book(tmp_path)

        result = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                          '--show'])

        assert result.exit_code == 0, result.output
        assert 'note: (none' in result.output, result.output
        assert 'the report\'s own' in result.output, result.output


class TestWhenThereIsNothingToDo:
    def test_a_bare_command_says_what_it_takes(self, tmp_path):
        book = _book(tmp_path)

        result = CliRunner().invoke(cli, ['set-invoice-style', str(book)])

        assert result.exit_code != 0
        assert '--note' in result.output and '--show' in result.output

    def test_setting_what_is_already_set_writes_nothing(self, tmp_path):
        """The book is not saved for a run that changes nothing — a save
        rewrites the file and rotates a backup beside it."""
        book = _book(tmp_path)
        _styled(book, tmp_path, '--note', 'Payment due in 30 days')
        was = book.stat().st_mtime_ns

        again = _styled(book, tmp_path, '--note', 'Payment due in 30 days')

        assert 'Already set' in again.output, again.output
        assert book.stat().st_mtime_ns == was


class TestTwoWaysToSayOneThing:
    """A command line saying two things about one setting is refused.

    Both of these had an order, and an order is an answer nobody asked for:
    `--note x --show` printed the footer the book held *before* the run and
    set nothing, which reads exactly like a write that happened.
    """

    def test_show_alongside_a_setting_is_refused(self, tmp_path):
        book = _book(tmp_path)

        result = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                          '--note', 'Payment due', '--show'])

        assert result.exit_code != 0
        assert '--show' in result.output
        held = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                        '--show'])
        assert 'note: (none' in held.output, held.output

    def test_note_and_clear_note_together_are_refused(self, tmp_path):
        book = _book(tmp_path)

        result = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                          '--note', 'A footer',
                                          '--clear-note'])

        assert result.exit_code != 0
        assert '--clear-note' in result.output
        page = _printed(book, tmp_path)
        assert 'A footer' not in page, page[-2000:]

    def test_an_empty_css_file_is_refused_rather_than_read_as_clearing(
            self, tmp_path):
        """A file a build step truncated says the same thing as
        `--clear-css` and means the opposite, and `✓ Set css` over a page
        carrying none of the styling is the report of a write that happened.
        """
        book = _book(tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_text('', encoding='utf-8')

        result = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                          '--css', str(style)])

        assert result.exit_code != 0
        assert 'empty' in result.output and '--clear-css' in result.output

    def test_a_css_file_of_whitespace_is_refused_too(self, tmp_path):
        """`echo > invoice.css` holds a newline, which is not empty and is
        not styling: stored, the newline *replaces* the report's own CSS, so
        the page loses the styling `--clear-css` would have given back."""
        book = _book(tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_text('\n', encoding='utf-8')

        result = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                          '--css', str(style)])

        assert result.exit_code != 0
        assert '--clear-css' in result.output, result.output
        assert '.entries-table' in _printed(book, tmp_path)

    def test_a_css_file_that_is_not_utf8_is_named(self, tmp_path):
        """A stylesheet saved as Latin-1 — a `©` in a comment is all it
        takes. The text is stored in the book and crosses into GnuCash as
        UTF-8, so the file has to be UTF-8, and a sentence beats a
        traceback."""
        book = _book(tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_bytes('/* \xa9 Widgets Inc. */\n.x { color: red }\n'
                          .encode('latin-1'))

        result = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                          '--css', str(style)])

        assert result.exit_code != 0
        assert 'UTF-8' in result.output, result.output

    def test_css_and_clear_css_together_are_refused(self, tmp_path):
        book = _book(tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_text(A_STYLE, encoding='utf-8')

        result = CliRunner().invoke(cli, [
            'set-invoice-style', str(book), '--css', str(style),
            '--clear-css'])

        assert result.exit_code != 0
        assert '--clear-css' in result.output
        page = _printed(book, tmp_path)
        assert 'border-style: dotted' not in page, page[:2500]


class TestABookWrittenBySomethingElse:
    """A slot holding a value nothing here wrote.

    `set-invoice-style` stores the text behind a prefix so a footer set to
    nothing survives `qof_book_set_string_option` deleting an empty slot. A
    book whose slot was written by hand — or by something written later —
    carries no prefix, and the value is taken as it stands rather than losing
    its first five characters to the strip.
    """

    def test_the_value_is_read_as_it_stands(self, tmp_path):
        from infrastructure.gnucash.kvp import set_book_string_option
        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )

        book = _book(tmp_path)
        time.sleep(1.1)
        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.NORMAL)
        try:
            assert set_book_string_option(repo.book, 'Business',
                                          'Invoice Extra Notes',
                                          'Written by another hand')
            repo.save()
        finally:
            repo.close()

        result = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                          '--show'])

        assert 'note: Written by another hand' in result.output, result.output
        assert 'Written by another hand' in _printed(book, tmp_path)

    def test_and_so_is_a_stylesheet_written_the_same_way(self, tmp_path):
        from infrastructure.gnucash.kvp import set_book_string_option
        from repositories.gnucash_repository import (
            GnuCashRepository,
            SessionMode,
        )

        book = _book(tmp_path)
        time.sleep(1.1)
        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.NORMAL)
        try:
            assert set_book_string_option(repo.book, 'Business',
                                          'Invoice CSS', A_STYLE)
            repo.save()
        finally:
            repo.close()

        assert 'border-style: dotted' in _printed(book, tmp_path)


class TestWhenTheBookRefusesTheWrite:
    """A refused write is reported with the reason, and exits non-zero.

    `set_book_string_option` logs the reason and answers `False`, which is
    right for an import setting many options and wrong for a command whose
    whole job is one write — so `set-invoice-style` takes the raising form.
    Reached here by making the write raise, there being no book a person can
    hand the command that refuses one slot and takes the next.
    """

    def test_the_reason_is_quoted_and_nothing_claims_success(self, tmp_path,
                                                             monkeypatch):
        book = _book(tmp_path)

        def refuse(*args, **kwargs):
            raise RuntimeError('qof_book_set_string_option went nowhere')

        monkeypatch.setattr('use_cases.set_invoice_style'
                            '.write_book_string_option', refuse)
        result = CliRunner().invoke(cli, ['set-invoice-style', str(book),
                                          '--note', 'Payment due in 30 days'])

        assert result.exit_code != 0, result.output
        assert 'qof_book_set_string_option went nowhere' in result.output
        assert '✓' not in result.output, result.output


class TestTheyAreNotPartOfTheFormat:
    """A ledger says what a book contains; styling is not that.

    So neither of these is written by an export or read by an import: two
    books that differ only in how their pages are styled export the same
    ledger, and a book rebuilt from one is styled however it was configured
    rather than however its ledger's author printed.
    """

    def test_an_export_says_nothing_about_them(self, tmp_path):
        book = _book(tmp_path)
        style = tmp_path / 'invoice.css'
        style.write_text(A_STYLE, encoding='utf-8')
        _styled(book, tmp_path, '--note', 'Payment due in 30 days',
                '--css', str(style))

        out = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        exported = out.read_text(encoding='utf-8')
        assert 'Payment due in 30 days' not in exported, exported
        assert 'border-style' not in exported, exported
        assert 'css' not in exported.lower(), exported

    def test_and_the_export_is_the_same_file_either_way(self, tmp_path):
        """One book, exported before and after the styling is set.

        Compared without the day each export was written on: an account and a
        commodity have no date of their own, so the export stamps the day it
        runs, and two exports either side of midnight differ over that alone.
        """
        book = _book(tmp_path)
        first = tmp_path / 'first.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(first),
            '--include-business-objects']).exit_code == 0

        style = tmp_path / 'invoice.css'
        style.write_text(A_STYLE, encoding='utf-8')
        _styled(book, tmp_path, '--note', 'Anything at all',
                '--css', str(style))

        second = tmp_path / 'second.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(second),
            '--include-business-objects']).exit_code == 0

        assert a_ledger_without_the_day_it_was_written(
            first.read_text(encoding='utf-8')
        ) == a_ledger_without_the_day_it_was_written(
            second.read_text(encoding='utf-8'))
