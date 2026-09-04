"""A book's date format is a book option, and it is set from the ledger.

GnuCash keeps one — `Business` → `Fancy Date Format` → `custom`, which its
File → Properties → Business dialog writes — and reads it when it draws a
page: `invoice.scm` calls `gnc:options-fancy-date`, whose fallback when
the option is absent is `qof-date-format-get`, the *application's* preference.
That preference is GSettings, not the file, so a book with no format of its
own is dated by whoever prints it.

Which made it the one thing on a printed page this tool could not set. Every
other field the report reads comes off the book and round-trips through the
`company` directive; this one had to be clicked into the GnuCash GUI, on every
machine that prints, and was lost by an export and re-import.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import (
    get_book_custom_metadata,
    get_book_string_option,
    merge_book_custom_metadata,
    set_book_string_option,
)
from repositories.gnucash_repository import GnuCashRepository, SessionMode


def _the_state_an_older_version_left(path, keys):
    """A book holding these keys in its custom blob and nothing on the option.

    `set-book-key` reached this state until it learned to refuse the `company`
    block's own field names — a key written there is read by nothing, since
    every reader looks at the Business option — so the state is staged through
    the helper that command calls, one layer down. That is the same write an
    older `import` performed, which is the book these tests are about.
    """
    repo = GnuCashRepository(str(path))
    repo.open(SessionMode.NORMAL)
    try:
        merge_book_custom_metadata(repo.book, keys)
        repo.save()
    finally:
        repo.close()

FIXTURES = Path('tests/fixtures')
LEDGER = str(FIXTURES / 'a_book_with_a_date_format.txt')


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'dates.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    return path


class TestThePrintedPage:
    """What the reader actually sees, drawn by GnuCash's own report."""

    def test_the_invoice_is_dated_the_way_the_book_says(self, book,
                                                         tmp_path):
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-DATE-001',
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        page = out.read_text(encoding='utf-8')
        assert '09 March 2026' in page, page[:3000]

    def test_and_so_is_a_bill(self, book, tmp_path):
        """`print-bill` reads the same two settings through the same
        renderer. Asserted rather than assumed, because a fix applied to one
        of two near-identical call sites is the kind that comes back."""
        out = tmp_path / 'bill.html'
        result = CliRunner().invoke(cli, [
            'print-bill', str(book), 'BILL-DATE-001',
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        page = out.read_text(encoding='utf-8')
        assert '09 March 2026' in page, page[:3000]

    # Every format the docs promise is consistent, and what each prints. The
    # invoice is dated 2026-03-09 and due 2026-04-09; the entry is the same
    # day. `docs/dates-on-printed-pages.md` states this table, so it is
    # pinned here rather than left as prose someone measured once.
    @pytest.mark.parametrize('fmt,posted,due', [
        ('%Y-%m-%d', '2026-03-09', '2026-04-09'),
        ('%m/%d/%Y', '03/09/2026', '04/09/2026'),
        ('%d/%m/%Y', '09/03/2026', '09/04/2026'),
        ('%d.%m.%Y', '09.03.2026', '09.04.2026'),
    ])
    def test_one_format_on_the_whole_page(self, tmp_path, fmt, posted, due):
        """The point of stating it: one page, one way of writing dates.

        GnuCash's own GUI gives you this because it pushes its date setting
        into QOF at startup and every date then agrees. A process that only
        loaded the library sets nothing, so the invoice's own dates came off the
        book and the entry rows off whoever's machine was running the
        command. The book decides both now.
        """
        ledger = tmp_path / 'ledger.txt'
        ledger.write_text(
            Path(LEDGER).read_text(encoding='utf-8')
            .replace('date_format: "%d %B %Y"', f'date_format: "{fmt}"'),
            encoding='utf-8')
        path = tmp_path / 'book.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(path), str(ledger),
            '--include-business-objects']).exit_code == 0

        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(path), 'INV-DATE-001', '--format', 'html',
            '--output', str(out)])
        assert result.exit_code == 0, result.output
        page = out.read_text(encoding='utf-8')

        assert posted in page, page[:3000]                # the posted date
        assert due in page, page[:3000]                   # its due date
        assert f'<td>{posted}</td>' in page, page[-3000:]   # the entry row
        # and nothing left reading the machine's way
        assert '03/09/26' not in page, page[-3000:]
        assert 'no date style' not in result.output, result.output

    def test_a_format_gnucash_has_no_style_for_says_so(self, book, tmp_path):
        """`%d %B %Y` is a fine thing to want and QOF cannot match it.

        `qof_date_format_set` takes a style, not a format string — US, UK, CE
        or ISO — so the entry rows cannot be made to read `09 March 2026`.
        The invoice still prints, with its own dates that way, and the run
        says which dates could not follow so nobody has to work out why one
        page has two formats.
        """
        out = tmp_path / 'inv.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-DATE-001', '--format', 'html',
            '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert 'no date style for' in result.output, result.output
        assert '%Y-%m-%d' in result.output, result.output   # what would work
        # Word for word, because README and docs/dates-on-printed-pages.md
        # both print this warning as output a reader will see, and the doc
        # says outright that everything it quotes came from a real run. A
        # substring check let the sentence be reworded in the code and leave
        # both copies quoting a message the program no longer prints.
        assert ("which GnuCash has no date style for — the posted date and "
                "the due date will read that way and every other date on the "
                "page will follow this machine's locale. For one format "
                "throughout, use one of: "
                "%Y-%m-%d, %d.%m.%Y, %d/%m/%Y, %m/%d/%Y") in result.output, \
            result.output

    def test_it_reaches_the_invoices_own_dates_and_not_the_entry_dates(
            self, book, tmp_path):
        """Which dates it governs, measured — because it is not all of them.

        GnuCash's reports hand the book's format to the posted and due dates
        (`gnc-print-time64`) and call `qof-print-date` for each entry's date,
        each payment's date and the "printed on" date, and that reads the
        *machine's* preference. So a page legitimately shows one format at the
        top and another in the table, and someone who set `date_format` and
        looked at the line items would think it had not worked.

        README states this as a table; this is what makes the table true.
        """
        out = tmp_path / 'inv.html'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-DATE-001', '--format', 'html',
            '--output', str(out)]).exit_code == 0
        page = out.read_text(encoding='utf-8')

        # The invoice's own two dates, in the book's format.
        assert '09 March 2026' in page, page[:3000]
        assert '09 April 2026' in page, page[:3000]
        # The entry's date, in the table, untouched by it.
        assert '<td>03/09/26</td>' in page, page[-3000:]

    def test_and_not_the_way_it_would_have_been_without_one(self, tmp_path):
        """The same invoice in a book that names no format.

        The difference is the point — the fallback is the machine's own
        preference, which is the whole objection: it is not a property of the
        book, so it is not a property of the invoice either. Both sides are
        asserted all the same. "Not `09 March 2026`" alone is satisfied by a
        page with no dates on it, which would be a defect rather than a
        fallback, and the run these containers give is `03/09/26`.
        """
        plain = tmp_path / 'plain.gnucash'
        ledger = Path(LEDGER).read_text(encoding='utf-8')
        without = tmp_path / 'without.txt'
        without.write_text(ledger.replace('  date_format: "%d %B %Y"\n', ''),
                           encoding='utf-8')
        built = CliRunner().invoke(cli, ['import', '--new', str(plain),
                                         str(without),
                                         '--include-business-objects'])
        assert built.exit_code == 0, built.output

        out = tmp_path / 'plain.html'
        result = CliRunner().invoke(cli, [
            'print-invoice', str(plain), 'INV-DATE-001',
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        page = out.read_text(encoding='utf-8')
        assert '09 March 2026' not in page
        assert '03/09/26' in page, page[:3000]


class TestTheBookOption:
    """That it is GnuCash's own option, in GnuCash's own place."""

    def test_gnucash_reads_it_back(self, book):
        """Through `gnc:options-fancy-date`, which is what the reports call —
        so this is the same question the page asks, without the page."""
        from infrastructure.guile import load_guile
        from services import gnucash_report as gr

        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.READ_ONLY)
        answer = None
        try:
            lib = load_guile()
            gr._make_current(repo.session)
            import tempfile
            work = Path(tempfile.mkdtemp(prefix='date-format-'))
            out = work / 'answer.txt'
            errors = work / 'errors.txt'

            def run(scheme):
                wrapped = (f'(catch #t (lambda () {scheme} #t)'
                           f' (lambda (key . args)'
                           f'   (call-with-output-file "{errors}"'
                           f'     (lambda (port)'
                           f'       (display (list key args) port)))))')
                lib.scm_eval_string(
                    lib.scm_from_utf8_string(wrapped.encode('utf-8')))
                if errors.exists() and errors.read_text().strip():
                    message = errors.read_text().strip()[:200]
                    errors.unlink()
                    raise gr.PageNotRenderedError(message)

            gr._dialect(run, work)
            run(f'''(call-with-output-file "{out}"
                      (lambda (port)
                        (set-port-encoding! port "UTF-8")
                        (display (gnc:options-fancy-date
                                   (gnc-get-current-book)) port)))''')
            answer = out.read_text(encoding='utf-8')
        finally:
            gr._make_current(None)
            repo.close()

        assert answer == '%d %B %Y', answer


class TestItSurvivesTheRoundTrip:
    """Export and re-import, which is the flow this tool exists for."""

    def test_the_export_states_it(self, book, tmp_path):
        out = tmp_path / 'exported.txt'
        result = CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'date_format: "%d %B %Y"' in out.read_text(encoding='utf-8')

    def test_and_a_book_rebuilt_from_it_prints_the_same_dates(self, book,
                                                              tmp_path):
        exported = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(exported),
            '--include-business-objects']).exit_code == 0

        rebuilt = tmp_path / 'rebuilt.gnucash'
        built = CliRunner().invoke(cli, ['import', '--new', str(rebuilt),
                                         str(exported),
                                         '--include-business-objects'])
        assert built.exit_code == 0, built.output

        out = tmp_path / 'rebuilt.html'
        printed = CliRunner().invoke(cli, [
            'print-invoice', str(rebuilt), 'INV-DATE-001',
            '--format', 'html', '--output', str(out)])
        assert printed.exit_code == 0, printed.output
        assert '09 March 2026' in out.read_text(encoding='utf-8')


class TestABookThatUsedItAsACustomKey:
    """`date_format` was any old key before it was a field of its own.

    A ledger naming it was kept as book-level custom metadata — one JSON blob
    that round-trips and is never rendered — so a book written before this
    change carries it there. CLAUDE.md finding 11 says what has to happen
    next: a key that has since become a field is dropped from the slot on the
    next import and filtered out of every writer, because emitted from both
    the line appears twice and the stale copy comes second, which is the one
    a re-import keeps.

    Staged by writing that blob directly — the same state an older `import`
    left behind.
    """

    def test_the_stale_copy_is_not_exported_beside_the_real_one(self, book,
                                                                tmp_path):
        _the_state_an_older_version_left(book, {'date_format': '%Y-%m-%d'})

        out = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        emitted = [line for line in out.read_text(encoding='utf-8').splitlines()
                   if 'date_format:' in line]
        assert len(emitted) == 1, emitted

    def test_and_the_book_keeps_the_one_gnucash_reads(self, book, tmp_path):
        """Of the two, the field wins — it is the one GnuCash's reports read,
        and the blob copy is a leftover of how the key used to be stored."""
        _the_state_an_older_version_left(book, {'date_format': '%Y-%m-%d'})

        out = tmp_path / 'inv.html'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-DATE-001', '--format', 'html',
            '--output', str(out)]).exit_code == 0
        assert '09 March 2026' in out.read_text(encoding='utf-8')

    def test_a_later_import_clears_the_stale_copy(self, book, tmp_path):
        """So it stops being carried at all, rather than being filtered
        forever."""
        _the_state_an_older_version_left(book, {'date_format': '%Y-%m-%d'})

        again = tmp_path / 'again.txt'
        again.write_text('company\n  date_format: "%d %B %Y"\n',
                         encoding='utf-8')
        assert CliRunner().invoke(cli, [
            'import', str(book), str(again),
            '--include-business-objects']).exit_code == 0

        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.READ_ONLY)
        try:
            held = get_book_custom_metadata(repo.book) or {}
        finally:
            repo.close()

        assert 'date_format' not in held, held


class TestABookWhoseOnlyCopyIsTheOldOne:
    """The legacy state itself: in the custom slot, and nowhere else.

    A book written before `date_format` was a field of its own has it as
    book-level custom metadata and nothing on the Business option. That slot
    is then **the only copy the book has**, so neither writer may treat it as
    stale: dropping it because the key is now a field loses the format
    outright, and filtering it out of the export writes a ledger that no
    longer says what the book was set to.

    Staged without ever naming `date_format` in a ledger, so the option is
    genuinely unset — the previous class stages it on top of a book that
    already had one, which is a different thing and cannot catch this.
    """

    @pytest.fixture
    def legacy(self, tmp_path):
        path = tmp_path / 'legacy.gnucash'
        bare = tmp_path / 'bare.txt'
        bare.write_text(
            Path(LEDGER).read_text(encoding='utf-8')
            .replace('  date_format: "%d %B %Y"\n', ''), encoding='utf-8')
        assert CliRunner().invoke(cli, [
            'import', '--new', str(path), str(bare),
            '--include-business-objects']).exit_code == 0
        _the_state_an_older_version_left(path, {'date_format': '%Y-%m-%d'})
        return path

    def test_the_export_still_states_it(self, legacy, tmp_path):
        """It is the only copy, and an export is the only copy a rebuild
        gets."""
        out = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(legacy), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        text = out.read_text(encoding='utf-8')
        assert 'date_format: "%Y-%m-%d"' in text, text
        assert text.count('date_format:') == 1, text

    def test_an_import_that_does_not_name_it_keeps_it(self, legacy, tmp_path):
        """An absent key is not an instruction — and here it would have been
        a deletion of the book's only copy."""
        other = tmp_path / 'other.txt'
        other.write_text('company\n  name: "Renamed Co."\n', encoding='utf-8')
        assert CliRunner().invoke(cli, [
            'import', str(legacy), str(other),
            '--include-business-objects']).exit_code == 0

        out = tmp_path / 'inv.html'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(legacy), 'INV-DATE-001', '--format', 'html',
            '--output', str(out)]).exit_code == 0
        assert '2026-03-09' in out.read_text(encoding='utf-8')

    def test_and_the_old_copy_becomes_the_option_gnucash_reads(self, legacy,
                                                               tmp_path):
        """Which is the migration: the value was in a place nothing printing
        looks at, so a book carrying it printed dates it had not asked for."""
        other = tmp_path / 'other.txt'
        other.write_text('company\n  name: "Renamed Co."\n', encoding='utf-8')
        assert CliRunner().invoke(cli, [
            'import', str(legacy), str(other),
            '--include-business-objects']).exit_code == 0

        repo = GnuCashRepository(str(legacy))
        repo.open(SessionMode.READ_ONLY)
        try:
            option = get_book_string_option(repo.book, 'Business',
                                            'Fancy Date Format/custom')
            held = get_book_custom_metadata(repo.book) or {}
        finally:
            repo.close()

        assert option == '%Y-%m-%d', option
        assert 'date_format' not in held, held


class TestABookHoldingItInBothPlaces:
    """A legacy slot copy beside an option written in GnuCash.

    While the slot kept its copy, clearing the option in the GUI was undone
    by the next import that said nothing about the key: the migration saw an
    empty option, found the stale value still in the slot, and wrote it back.
    The option is the book's answer once it has one, so a slot copy beside it
    is stale whatever it says, and goes on the next import either way.
    """

    @pytest.fixture
    def both(self, book):
        _the_state_an_older_version_left(book, {'date_format': '%Y-%m-%d'})
        return book

    def test_the_stale_copy_leaves_on_an_import_that_says_nothing(
            self, both, tmp_path):
        other = tmp_path / 'other.txt'
        other.write_text('company\n  name: "Renamed Co."\n', encoding='utf-8')
        assert CliRunner().invoke(cli, [
            'import', str(both), str(other),
            '--include-business-objects']).exit_code == 0

        repo = GnuCashRepository(str(both))
        repo.open(SessionMode.READ_ONLY)
        try:
            held = get_book_custom_metadata(repo.book) or {}
            option = get_book_string_option(repo.book, 'Business',
                                            'Fancy Date Format/custom')
        finally:
            repo.close()

        assert 'date_format' not in held, held
        assert option == '%d %B %Y', option

    def test_so_clearing_the_option_afterwards_stays_cleared(self, both,
                                                             tmp_path):
        """The failure this closes: the reader clears the format in GnuCash
        and the next import puts the old one back."""
        other = tmp_path / 'other.txt'
        other.write_text('company\n  name: "Renamed Co."\n', encoding='utf-8')
        assert CliRunner().invoke(cli, [
            'import', str(both), str(other),
            '--include-business-objects']).exit_code == 0

        repo = GnuCashRepository(str(both))
        repo.open(SessionMode.NORMAL)
        try:
            set_book_string_option(repo.book, 'Business',
                                   'Fancy Date Format/custom', '')
            repo.save()
        finally:
            repo.close()

        assert CliRunner().invoke(cli, [
            'import', str(both), str(other),
            '--include-business-objects']).exit_code == 0

        repo = GnuCashRepository(str(both))
        repo.open(SessionMode.READ_ONLY)
        try:
            option = get_book_string_option(repo.book, 'Business',
                                            'Fancy Date Format/custom')
        finally:
            repo.close()
        assert not option, option


class TestAnotherKeyThatBecameAField:
    """The rule is the set's, not one key's.

    `phone` has been a Business field all along, but a book written by an
    older version has it in the blob just the same — so the same two writers
    see it, and the same two mistakes were available: invisible to the export,
    deleted by the next company import that did not name it.
    """

    def test_a_copy_beside_a_filled_option_is_dropped_and_said_out_loud(
            self, tmp_path):
        """The arm that ends a value, on a name that was ordinary until now.

        `name` was a custom book key anyone could set, so a book may hold one
        for something of its own beside GnuCash's Company Name. It is a second
        answer to a question the option already answers — and left there it
        was written back over the option the next time that field was cleared
        in GnuCash — so it goes. What it must not do is go quietly: the
        writers prefer the option, so the value is not in the reader's last
        export either, and the summary says only `updated`.
        """
        path = tmp_path / 'codename.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(path), str(FIXTURES / 'q019_accounts.txt')
        ]).exit_code == 0
        named = tmp_path / 'named.txt'
        named.write_text('company\n  name: "Acme Plaintext Co."\n',
                         encoding='utf-8')
        assert CliRunner().invoke(cli, [
            'import', str(path), str(named),
            '--include-business-objects']).exit_code == 0
        _the_state_an_older_version_left(path, {'name': 'internal-codename'})

        other = tmp_path / 'other.txt'
        other.write_text('company\n  phone: "+1-555-0100"\n',
                         encoding='utf-8')
        result = CliRunner().invoke(cli, [
            'import', str(path), str(other), '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'internal-codename' in result.output, result.output
        assert "'name'" in result.output, result.output

        repo = GnuCashRepository(str(path))
        repo.open(SessionMode.READ_ONLY)
        try:
            held = get_book_custom_metadata(repo.book) or {}
            option = get_book_string_option(repo.book, 'Business',
                                            'Company Name')
        finally:
            repo.close()
        assert 'name' not in held, held
        assert option == 'Acme Plaintext Co.', option

    def test_it_is_exported_and_not_dropped_unasked(self, tmp_path):
        path = tmp_path / 'phone.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(path), str(FIXTURES / 'q019_accounts.txt')
        ]).exit_code == 0
        _the_state_an_older_version_left(path, {'phone': '+1-555-0100'})

        out = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(path), '--output', str(out),
            '--include-business-objects']).exit_code == 0
        text = out.read_text(encoding='utf-8')
        assert 'phone: "+1-555-0100"' in text, text
        assert text.count('phone:') == 1, text

    def test_an_address_line_is_not_dropped_unasked(self, tmp_path):
        """The address keys are in the same set and have no option of their
        own — they are the lines of `Company Address` — so nothing rewrites
        them elsewhere. Dropped from the slot because they are "known", the
        line is simply gone.
        """
        path = tmp_path / 'addr.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(path), str(FIXTURES / 'q019_accounts.txt')
        ]).exit_code == 0
        _the_state_an_older_version_left(path, {'addr1': '42 Example Street'})

        other = tmp_path / 'other.txt'
        other.write_text('company\n  name: "Renamed Co."\n', encoding='utf-8')
        assert CliRunner().invoke(cli, [
            'import', str(path), str(other),
            '--include-business-objects']).exit_code == 0

        out = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(path), '--output', str(out),
            '--include-business-objects']).exit_code == 0
        assert '42 Example Street' in out.read_text(encoding='utf-8'), \
            out.read_text(encoding='utf-8')


class TestChangingItAndClearingIt:
    """The rule every other key on this directive follows."""

    def test_a_later_import_changes_it(self, book, tmp_path):
        change = tmp_path / 'change.txt'
        change.write_text('company\n  date_format: "%Y/%m/%d"\n',
                          encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(change),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        out = tmp_path / 'inv.html'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-DATE-001', '--format', 'html',
            '--output', str(out)]).exit_code == 0
        assert '2026/03/09' in out.read_text(encoding='utf-8')

    def test_naming_it_empty_clears_it(self, book, tmp_path):
        """`key: ""` removes, as README's "what leaving it out says" has it —
        and the book then falls back to the machine's preference again."""
        clear = tmp_path / 'clear.txt'
        clear.write_text('company\n  date_format: ""\n', encoding='utf-8')
        result = CliRunner().invoke(cli, ['import', str(book), str(clear),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output

        out = tmp_path / 'inv.html'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-DATE-001', '--format', 'html',
            '--output', str(out)]).exit_code == 0
        page = out.read_text(encoding='utf-8')
        assert '09 March 2026' not in page
        # Positively, and not only by the format's absence: cleared has to
        # mean *dated by the machine again*, which is what the release note
        # promises. A page whose dates came out empty would satisfy the line
        # above just as well, and that is a different — worse — outcome.
        assert '03/09/26' in page, page[:3000]

    def test_a_directive_that_does_not_name_it_leaves_it(self, book,
                                                         tmp_path):
        """An absent key is not an instruction — CLAUDE.md finding 11."""
        other = tmp_path / 'other.txt'
        other.write_text('company\n  name: "Renamed Co."\n', encoding='utf-8')
        assert CliRunner().invoke(
            cli, ['import', str(book), str(other),
                  '--include-business-objects']).exit_code == 0

        out = tmp_path / 'inv.html'
        assert CliRunner().invoke(cli, [
            'print-invoice', str(book), 'INV-DATE-001', '--format', 'html',
            '--output', str(out)]).exit_code == 0
        assert '09 March 2026' in out.read_text(encoding='utf-8')
