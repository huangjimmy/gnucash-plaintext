"""Every column an invoice or bill row has survives export and re-import.

A `GncEntry` carries more than the eight fields this format used to write.
GnuCash's invoice window has a discount — a figure, and the two choices that
say what the figure means — and both windows have a note per line. A bill
window has two columns an invoice has not: whether the line is billable to a
customer, and whether it was paid in cash or on a card. Every one of them
survives a save, measured on 5.10.

None of that reached the ledger. An export wrote eight fields, so a book with
a discounted line exported as a line with no discount, and re-importing that
export took the discount out of the book — quietly, since the comparison that
decides `unchanged` did not look at the missing fields either.

**A bill's `action:` was the sharpest**, because the code said it could not
exist: "GnuCash's Entry object stores action on the invoice side only … Bills
do not expose or persist an action field through the GnuCash API." An entry
given `Material`, saved and reopened, reads back `Material`. One field, shown
in the Action column of both windows.

Read back through the *book*, not the file: what a writer wrote proves only
what it wrote, and the question here is what GnuCash holds afterwards.
"""

import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query

from cli.main import cli
from infrastructure.gnucash.engine import load_gnc_engine
from infrastructure.gnucash.entry_fields import billable_to
from infrastructure.gnucash.utils import numeric_to_fraction
from repositories.gnucash_repository import GnuCashRepository, SessionMode

LEDGER = str(Path('tests/fixtures') / 'entries_with_every_field.txt')


def _taxable(book_path, description):
    """Whether the book holds that line as taxable, read from the bill."""
    from gnucash.gnucash_business import Entry

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.READ_ONLY)
    try:
        q = Query()
        q.search_for('gncEntry')
        q.set_book(repo.book)
        for raw in q.run():
            entry = Entry(instance=raw)
            if entry.GetDescription() == description:
                answer = bool(entry.GetBillTaxable())
                q.destroy()
                return answer
        q.destroy()
        raise AssertionError(f'no entry named {description!r}')
    finally:
        repo.close()


def _book(tmp_path, name='book.gnucash'):
    path = tmp_path / name
    made = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    return path


def _entries(book_path):
    """Every entry in the book, wrapped, by the document it belongs to."""
    from gnucash import Query
    from gnucash.gnucash_business import Entry

    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.READ_ONLY)
    try:
        q = Query()
        q.search_for('gncEntry')
        q.set_book(repo.book)
        found = {}
        for raw in q.run():
            entry = Entry(instance=raw)
            found[entry.GetDescription()] = {
                'action': entry.GetAction(),
                'notes': entry.GetNotes(),
                # A Fraction, not `num() / denom()`: money in this repo is
                # never compared through a float.
                'discount': numeric_to_fraction(entry.GetInvDiscount()),
                'discount_type': entry.GetInvDiscountType(),
                'discount_how': entry.GetInvDiscountHow(),
                'billable': bool(entry.GetBillable()),
                # Through ctypes: SWIG's `GetBillTo` wraps whatever the
                # engine hands back as a `Customer`, and an entry billed to
                # nobody raises out of that constructor rather than
                # answering.
                'billable_to': billable_to(load_gnc_engine(),
                                           int(entry.instance))[0],
                'payment': entry.GetBillPayment(),
            }
        q.destroy()
        return found
    finally:
        repo.close()


@pytest.fixture
def imported(tmp_path):
    return _entries(_book(tmp_path))


class TestWhatTheImportPutsInTheBook:
    def test_the_invoice_line_keeps_its_note(self, imported):
        """Quotes and all: the note in the ledger is written `\\"` and the
        book holds the quote itself, which is what GnuCash's window shows."""
        line = imported['Consulting, February']

        assert line['notes'] == \
            'Agreed rate for the first quarter, per "Schedule A"'

    def test_and_its_discount_with_both_choices(self, imported):
        """A figure alone is ambiguous: 10 off and 10 per cent off are
        different documents, and the same 10 per cent lands differently on
        either side of tax."""
        from infrastructure.gnucash.entry_fields import (
            DISCOUNT_HOWS,
            DISCOUNT_TYPES,
        )

        line = imported['Consulting, February']

        assert line['discount'] == 10
        assert line['discount_type'] == DISCOUNT_TYPES['percent']
        assert line['discount_how'] == DISCOUNT_HOWS['pretax']

    def test_the_bill_line_keeps_its_action(self, imported):
        """The field the code said bills do not have."""
        assert imported['Parts for the Henderson job']['action'] == 'Material'

    def test_and_its_note_billable_flag_and_payment(self, imported):
        from infrastructure.gnucash.entry_fields import PAYMENT_TYPES

        line = imported['Parts for the Henderson job']

        assert line['notes'] == 'Re-bill to the customer at cost'
        assert line['billable'] is True
        assert line['payment'] == PAYMENT_TYPES['card']

    def test_and_the_customer_the_line_is_re_billed_to(self, imported):
        """Which is what makes `billable:` worth carrying — a line billable
        to nobody is one GnuCash cannot offer when that customer's invoice is
        raised."""
        assert imported['Parts for the Henderson job'][
            'billable_to'] == 'C-EVERY'

    def test_and_a_line_billed_to_nobody_says_so(self, imported):
        """An invoice line has no chargeback owner, and GnuCash initialises
        the field as a customer owner with no customer behind it — so the id
        is what says there is none, not the owner's type."""
        assert imported['Consulting, February']['billable_to'] == ''


class TestALedgerThatNamesNoneOfThem:
    """The ordinary ledger: eight keys per entry, as every book has today.

    Importing one must not require the new keys — an unstated key is not an
    instruction — and exporting the result must state what the book holds,
    defaults included. Which means the export of a file that named none of
    them carries all of them, at the values GnuCash gives an untouched entry:
    measured on 5.10, an empty note, a discount of 0 `percent` `pretax`, not
    billable, paid `cash`.

    The fixture is the one every other business-object test uses, so this is
    the shape of a real ledger rather than one written to pass.
    """

    ORDINARY = 'tests/fixtures/business_objects.txt'

    @pytest.fixture
    def exported(self, tmp_path):
        book = tmp_path / 'ordinary.gnucash'
        made = CliRunner().invoke(cli, ['import', '--new', str(book),
                                        self.ORDINARY,
                                        '--include-business-objects'])
        assert made.exit_code == 0, made.output

        out = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects']).exit_code == 0
        return out.read_text(encoding='utf-8')

    def test_it_imports_without_the_new_keys(self, exported):
        """The fixture names none of them and the import is clean — the
        assertion is the fixture reaching the export at all."""
        assert 'invoice "INV-2026-001"' in exported

    def test_and_the_export_states_the_defaults(self, exported):
        for expected in ('notes: ""',
                         'discount: 0',
                         'discount_type: percent',
                         'discount_how: pretax',
                         'billable: #False',
                         'billable_to: ""',
                         'payment_type: cash'):
            assert expected in exported, (expected, exported[:1500])

    def test_and_the_export_reimports_unchanged(self, tmp_path, exported):
        """The defaults have to read back as the defaults, or a book would be
        rewritten on every run by the very lines that describe it."""
        ledger = tmp_path / 'again.txt'
        ledger.write_text(exported, encoding='utf-8')
        book = tmp_path / 'again.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(book), str(ledger),
            '--include-business-objects']).exit_code == 0

        again = CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "INV-2026-001": unchanged' in again.output, \
            again.output


class TestTheyAreFieldsAndNotMetadata:
    """Each value is on the GnuCash field, and nowhere else.

    A round-trip cannot tell the difference: the same writer and reader would
    agree about a value kept in a slot of this project's own, and the ledger
    would look right while GnuCash's own windows showed nothing. So the field
    is read through GnuCash's accessor — done by every test above — and the
    entry's custom metadata is read here to show the value is not *also*
    sitting there, which is what a key that never became reserved would do.
    """

    def test_the_note_is_the_entrys_own_field(self, tmp_path):
        from infrastructure.gnucash.kvp import get_custom_metadata

        book = _book(tmp_path)
        from gnucash import Query
        from gnucash.gnucash_business import Entry

        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.READ_ONLY)
        try:
            q = Query()
            q.search_for('gncEntry')
            q.set_book(repo.book)
            for raw in q.run():
                entry = Entry(instance=raw)
                held = get_custom_metadata(entry) or {}
                # Nothing of the format's own on the entry: the note is the
                # engine's `notes` field, the discount its discount fields.
                assert 'notes' not in held, held
                assert 'discount' not in held, held
                assert 'billable' not in held, held
                assert 'payment_type' not in held, held
            q.destroy()
        finally:
            repo.close()

    def test_gnucash_reads_them_back_without_this_project(self, tmp_path):
        """Read with GnuCash's own bindings, not with anything here.

        The importer could satisfy every test above by writing a slot this
        project alone knows how to read. What a customer sees is GnuCash's
        window, so the check that matters is GnuCash's own accessor on a book
        opened by GnuCash's own session.
        """
        book = _book(tmp_path)

        from gnucash import Query, Session
        from gnucash.gnucash_business import Entry

        # `SessionOpenMode` arrived in GnuCash 4.0; on 3.8 a session is opened
        # read-only by taking no lock. Both spellings are GnuCash's own, which
        # is what this test is for.
        try:
            from gnucash import SessionOpenMode
            session = Session(f'xml://{book}',
                              SessionOpenMode.SESSION_READ_ONLY)
        except ImportError:
            session = Session(f'xml://{book}', ignore_lock=True)
        try:
            q = Query()
            q.search_for('gncEntry')
            q.set_book(session.book)
            notes = {Entry(instance=raw).GetDescription():
                     Entry(instance=raw).GetNotes() for raw in q.run()}
            q.destroy()
        finally:
            session.end()
            session.destroy()

        assert notes['Consulting, February'] == \
            'Agreed rate for the first quarter, per "Schedule A"'
        assert notes['Parts for the Henderson job'] == \
            'Re-bill to the customer at cost'


class TestAnEntryBlockDescribesTheWholeLine:
    """An unnamed key means GnuCash's default, not "leave it alone".

    An entry is never patched: a document being re-imported has every entry
    destroyed and rebuilt from its block, so there is nothing left to leave
    alone. `action:` has always worked this way, and README says so.

    Read with `in`, the five new keys did neither one thing nor the other. A
    block naming `price` and no note kept the note while nothing else
    differed, and dropped it the moment the price made the document rebuild —
    one keystroke deciding whether the note survived, and the run saying
    `updated` without saying what had gone.
    """

    ORDINARY = 'tests/fixtures/business_objects.txt'

    def _ledger_with(self, tmp_path, name, replacement):
        ledger = tmp_path / name
        source, wanted = replacement
        text = Path(LEDGER).read_text(encoding='utf-8')
        assert source in text, source
        ledger.write_text(text.replace(source, wanted), encoding='utf-8')
        return ledger

    def test_changing_one_field_reports_the_unnamed_ones_as_a_difference(
            self, tmp_path):
        """The note is gone after the rebuild — and the run says `updated`
        rather than reporting a document it left alone."""
        book = _book(tmp_path)
        edited = self._ledger_with(
            tmp_path, 'edited.txt',
            ('\t\tnotes: "Agreed rate for the first quarter, '
             'per \\"Schedule A\\""\n', ''))

        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'invoice "INV-EVERY-001": updated' in result.output, \
            result.output
        assert _entries(book)['Consulting, February']['notes'] == ''

    def test_a_ledger_naming_none_of_them_is_unchanged_on_re_import(
            self, tmp_path):
        """The other half, and the one a book pays for daily: the defaults
        the comparison reads have to be the defaults the import writes, or
        every ordinary ledger would rebuild its documents on every run."""
        book = tmp_path / 'ordinary.gnucash'
        made = CliRunner().invoke(cli, ['import', '--new', str(book),
                                        self.ORDINARY,
                                        '--include-business-objects'])
        assert made.exit_code == 0, made.output

        again = CliRunner().invoke(cli, ['import', str(book), self.ORDINARY,
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "INV-2026-001": unchanged' in again.output, \
            again.output
        assert 'bill "BILL-2026-001": unchanged' in again.output, again.output


class TestEditingOneOfThemInTheLedger:
    """Each field edited on its own reports `updated` and lands in the book.

    The comparison that decides `unchanged` has to read every field the
    writer writes, and every test above exercises the matching direction —
    an untouched ledger re-imported. That passes just as well with a field
    missing from the comparison, which is the state this commit found: an
    edited discount imported as `unchanged` and the book kept the old figure.
    """

    def _after_editing(self, tmp_path, source, wanted):
        book = _book(tmp_path)
        edited = tmp_path / 'edited.txt'
        text = Path(LEDGER).read_text(encoding='utf-8')
        assert source in text, source
        edited.write_text(text.replace(source, wanted, 1), encoding='utf-8')

        result = CliRunner().invoke(cli, ['import', str(book), str(edited),
                                          '--include-business-objects'])
        assert result.exit_code == 0, result.output
        return result.output, _entries(book)

    def test_a_changed_discount_figure(self, tmp_path):
        output, entries = self._after_editing(
            tmp_path, '\t\tdiscount: 10', '\t\tdiscount: 20')

        assert 'invoice "INV-EVERY-001": updated' in output, output
        assert entries['Consulting, February']['discount'] == 20

    def test_a_changed_discount_type(self, tmp_path):
        from infrastructure.gnucash.entry_fields import DISCOUNT_TYPES

        output, entries = self._after_editing(
            tmp_path, 'discount_type: percent', 'discount_type: value')

        assert 'invoice "INV-EVERY-001": updated' in output, output
        assert entries['Consulting, February']['discount_type'] == \
            DISCOUNT_TYPES['value']

    def test_a_changed_discount_how(self, tmp_path):
        from infrastructure.gnucash.entry_fields import DISCOUNT_HOWS

        output, entries = self._after_editing(
            tmp_path, 'discount_how: pretax', 'discount_how: posttax')

        assert 'invoice "INV-EVERY-001": updated' in output, output
        assert entries['Consulting, February']['discount_how'] == \
            DISCOUNT_HOWS['posttax']

    def test_a_billable_flag_turned_off(self, tmp_path):
        output, entries = self._after_editing(
            tmp_path, 'billable: true', 'billable: false')

        assert 'bill "BILL-EVERY-001": updated' in output, output
        assert entries['Parts for the Henderson job']['billable'] is False

    def test_a_changed_payment_type(self, tmp_path):
        from infrastructure.gnucash.entry_fields import PAYMENT_TYPES

        output, entries = self._after_editing(
            tmp_path, 'payment_type: card', 'payment_type: cash')

        assert 'bill "BILL-EVERY-001": updated' in output, output
        assert entries['Parts for the Henderson job']['payment'] == \
            PAYMENT_TYPES['cash']

    def test_a_changed_note_on_a_bill_line(self, tmp_path):
        output, entries = self._after_editing(
            tmp_path, 'notes: "Re-bill to the customer at cost"',
            'notes: "Re-bill at cost plus ten"')

        assert 'bill "BILL-EVERY-001": updated' in output, output
        assert entries['Parts for the Henderson job']['notes'] == \
            'Re-bill at cost plus ten'

    def test_a_changed_action_on_a_bill_line(self, tmp_path):
        output, entries = self._after_editing(
            tmp_path, 'action: "Material"', 'action: "Labour"')

        assert 'bill "BILL-EVERY-001": updated' in output, output
        assert entries['Parts for the Henderson job']['action'] == 'Labour'

    def test_a_chargeback_customer_taken_off_the_line(self, tmp_path):
        """The direction that costs: a line still billable, to nobody. Left
        out of the comparison the book would have kept the old customer and
        the run would have said `unchanged`."""
        output, entries = self._after_editing(
            tmp_path, 'billable_to: "C-EVERY"', 'billable_to: ""')

        assert 'bill "BILL-EVERY-001": updated' in output, output
        line = entries['Parts for the Henderson job']
        assert line['billable_to'] == ''
        assert line['billable'] is True


class TestAKeyOfTheOtherDocument:
    """`discount:` on a bill, `billable:` on an invoice: refused by name.

    Each side's setter reads only its own keys, so one of these would be read
    by nothing — the import exits 0, the book stores nothing, the export
    writes no such line, and every later run reports `unchanged`. That is the
    silence this commit exists to end, and sharper here than for an invented
    key: a reader has just been told these are real keys of this format.
    """

    def _refused(self, tmp_path, source, wanted):
        ledger = tmp_path / 'wrong-side.txt'
        text = Path(LEDGER).read_text(encoding='utf-8')
        assert source in text, source
        ledger.write_text(text.replace(source, wanted, 1), encoding='utf-8')

        book = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                          str(ledger),
                                          '--include-business-objects'])
        assert result.exit_code != 0, result.output
        return result.output

    def test_a_discount_on_a_bill_entry(self, tmp_path):
        output = self._refused(tmp_path, '\t\tbillable: true',
                               '\t\tbillable: true\n\t\tdiscount: 10')

        assert 'discount' in output, output
        assert 'bill window has no such column' in output, output

    def test_two_of_them_at_once_are_named_together(self, tmp_path):
        output = self._refused(
            tmp_path, '\t\tbillable: true',
            '\t\tbillable: true\n\t\tdiscount: 10\n\t\tdiscount_type: percent')

        assert 'discount, discount_type' in output, output
        assert 'are keys' in output, output

    def test_a_billable_flag_on_an_invoice_entry(self, tmp_path):
        output = self._refused(tmp_path, '\t\tdiscount: 10',
                               '\t\tdiscount: 10\n\t\tbillable: true')

        assert 'billable' in output, output
        assert 'invoice window has no such column' in output, output

    def test_a_chargeback_customer_on_an_invoice_entry(self, tmp_path):
        output = self._refused(
            tmp_path, '\t\tdiscount: 10',
            '\t\tdiscount: 10\n\t\tbillable_to: "C-EVERY"')

        assert 'billable_to' in output, output
        assert 'invoice window has no such column' in output, output


class TestALineBilledToAJob:
    """GnuCash's other chargeback target, and one this format cannot state.

    A `GncEntry`'s billto is a `GncOwner`, and GnuCash's Bill window offers a
    customer or one of that customer's jobs. A job has no spelling here, and
    writing the customer behind it would come back as a customer chargeback —
    a different book, with nothing saying so. So it is refused by name, as a
    credit note is.

    Set here through ctypes because this tool has no way to make one: the
    point is a book GnuCash can hand over, not one it wrote.
    """

    def _billed_to_a_job(self, tmp_path):
        import ctypes

        from gnucash import Query
        from gnucash.gnucash_business import Entry, Job

        book_path = _book(tmp_path, 'job.gnucash')
        repo = GnuCashRepository(str(book_path))
        repo.open(SessionMode.NORMAL)
        try:
            lib = load_gnc_engine()
            lib.gncOwnerInitJob.restype = None
            lib.gncOwnerInitJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

            customer = repo.book.CustomerLookupByID('C-EVERY')
            job = Job(repo.book, 'J-EVERY', customer)
            job.SetName('The Henderson job')

            q = Query()
            q.search_for('gncEntry')
            q.set_book(repo.book)
            for raw in q.run():
                entry = Entry(instance=raw)
                if entry.GetDescription() == 'Parts for the Henderson job':
                    owner = lib.gncOwnerNew()
                    try:
                        lib.gncOwnerInitJob(owner, int(job.instance))
                        lib.gncEntrySetBillTo(int(entry.instance), owner)
                    finally:
                        lib.gncOwnerFree(owner)
            q.destroy()
            time.sleep(1.1)   # two saves in one second collide on the backup
            repo.save()
        finally:
            repo.close()
        return book_path

    def test_the_export_refuses_it_by_name(self, tmp_path):
        book = self._billed_to_a_job(tmp_path)
        ledger = tmp_path / 'out.txt'

        result = CliRunner().invoke(cli, [
            'export', str(book), '--output', str(ledger),
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        # An export is the whole book, so a sentence about "a line" with
        # nothing to find it by is not an answer. The document, the line and
        # the job it names, all three.
        assert 'bill "BILL-EVERY-001"' in result.output, result.output
        assert 'Parts for the Henderson job' in result.output, result.output
        assert 'J-EVERY' in result.output, result.output
        assert not ledger.exists(), 'a refusal wrote a file'

    def test_and_so_does_the_printed_page(self, tmp_path):
        """`print-bill --format plaintext` writes the same block through the
        same builder, so it answers the same way rather than printing a page
        whose chargeback is not the book's."""
        book = self._billed_to_a_job(tmp_path)
        page = tmp_path / 'page.txt'

        result = CliRunner().invoke(cli, [
            'print-bill', str(book), 'BILL-EVERY-001',
            '--format', 'plaintext', '--output', str(page)])

        assert result.exit_code != 0, result.output
        assert 'Parts for the Henderson job' in result.output, result.output
        assert 'J-EVERY' in result.output, result.output

    def test_the_rest_of_the_book_is_still_refused_as_one(self, tmp_path):
        """One document's refusal withholds the export, as any other does —
        the file a book is rebuilt from is all of it or none."""
        book = self._billed_to_a_job(tmp_path)
        ledger = tmp_path / 'out.txt'
        CliRunner().invoke(cli, ['export', str(book), '--output', str(ledger),
                                 '--include-business-objects'])

        assert not ledger.exists(), 'a refusal wrote a partial ledger'

    def test_but_a_ledger_can_still_put_it_right(self, tmp_path):
        """The writer refuses; the *import* answers. A comparison's question
        is whether the entry matches the file, and a job matches neither a
        stated customer nor nobody — so the document rebuilds and the ledger
        replaces the chargeback. Refused there too, such a book could be
        neither exported nor re-imported, and the GUI was the only way out."""
        book = self._billed_to_a_job(tmp_path)

        result = CliRunner().invoke(cli, ['import', str(book), LEDGER,
                                          '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'bill "BILL-EVERY-001": updated' in result.output, result.output
        assert _entries(book)['Parts for the Henderson job'][
            'billable_to'] == 'C-EVERY'

    def test_and_then_it_exports(self, tmp_path):
        """Which is the point of the round trip above: the book is writable
        again once the ledger has put the chargeback back to a customer."""
        book = self._billed_to_a_job(tmp_path)
        assert CliRunner().invoke(cli, ['import', str(book), LEDGER,
                                        '--include-business-objects']
                                  ).exit_code == 0
        ledger = tmp_path / 'after.txt'

        result = CliRunner().invoke(cli, [
            'export', str(book), '--output', str(ledger),
            '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'billable_to: "C-EVERY"' in ledger.read_text(encoding='utf-8')


class TestACustomerTheBookHasNotGot:
    """`billable_to:` names a customer, so a name the book has not got is
    refused — with the entry not yet made, as an unknown account is."""

    def test_the_id_is_named_and_nothing_is_written(self, tmp_path):
        ledger = tmp_path / 'unknown-customer.txt'
        text = Path(LEDGER).read_text(encoding='utf-8')
        ledger.write_text(
            text.replace('billable_to: "C-EVERY"', 'billable_to: "C-NOBODY"'),
            encoding='utf-8')

        book = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                          str(ledger),
                                          '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'billable_to' in result.output, result.output
        assert 'C-NOBODY' in result.output, result.output
        assert 'no customer in this book' in result.output, result.output


class TestAValueWrittenAsANumber:
    """`billable: 0`, `payment_type: 1` — a bare number, not a word.

    A number in a file arrives as an `int`, not a string, and the lookups
    raised `'int' object has no attribute 'strip'`. The run then reported
    that, with nothing about the key or the words it takes — and `0` is a
    spelling this format accepts for false everywhere else.
    """

    def _imported(self, tmp_path, source, wanted):
        ledger = tmp_path / 'numbers.txt'
        text = Path(LEDGER).read_text(encoding='utf-8')
        assert source in text, source
        ledger.write_text(text.replace(source, wanted), encoding='utf-8')

        book = tmp_path / 'book.gnucash'
        return CliRunner().invoke(cli, ['import', '--new', str(book),
                                        str(ledger),
                                        '--include-business-objects']), book

    def test_billable_zero_is_false(self, tmp_path):
        result, book = self._imported(tmp_path, 'billable: true',
                                      'billable: 0')

        assert result.exit_code == 0, result.output
        assert _entries(book)['Parts for the Henderson job'][
            'billable'] is False

    def test_a_mistyped_taxable_is_refused_rather_than_read_as_false(
            self, tmp_path):
        """The costlier direction, and the costliest key: read as
        `== 'true'`, `taxable: treu` imported as **not taxable**, and the
        flag decides the line's tax, every `breakdown:` block and the
        document's totals — so a page printed afterwards agreed with itself
        and re-imported `unchanged` against a book that had dropped the
        tax."""
        result, _ = self._imported(tmp_path, 'taxable: false',
                                   'taxable: treu')

        assert result.exit_code != 0, result.output
        assert 'taxable' in result.output, result.output
        assert 'neither true nor false' in result.output, result.output

    def test_and_a_mistyped_tax_included_likewise(self, tmp_path):
        result, _ = self._imported(tmp_path, 'tax_included: false',
                                   'tax_included: treu')

        assert result.exit_code != 0, result.output
        assert 'tax_included' in result.output, result.output

    def test_a_word_that_is_neither_true_nor_false_is_refused(self, tmp_path):
        """`billable: treu` used to import as **true** — read as "not
        false", a typo became the costly answer, and the line was re-billed
        to a customer nobody named."""
        result, _ = self._imported(tmp_path, 'billable: true',
                                   'billable: treu')

        assert result.exit_code != 0, result.output
        assert 'billable' in result.output, result.output
        assert 'neither true nor false' in result.output, result.output

    def test_taxable_written_as_a_capital_true_is_taxable(self, tmp_path):
        """`True` decodes to a boolean and `1` to an integer, and the flag
        used to be compared against the string `true` — so both read as
        **not taxable**, on a key that decides the line's tax and every
        figure the document states."""
        result, book = self._imported(tmp_path, 'taxable: false',
                                      'taxable: True')

        assert result.exit_code == 0, result.output
        assert _taxable(book, 'Parts for the Henderson job') is True

    @pytest.mark.parametrize('spelling', ['taxable: 1', 'taxable: yes'])
    def test_and_written_as_one_or_yes(self, tmp_path, spelling):
        result, book = self._imported(tmp_path, 'taxable: false', spelling)

        assert result.exit_code == 0, result.output
        assert _taxable(book, 'Parts for the Henderson job') is True

    def test_a_payment_type_written_as_a_number_is_refused_by_name(
            self, tmp_path):
        """Refused, not taken as the engine value it happens to equal: the
        file is naming a number where the format takes a word, and 1 meaning
        `cash` is an implementation detail no ledger states."""
        result, _ = self._imported(tmp_path, 'payment_type: card',
                                   'payment_type: 1')

        assert result.exit_code != 0, result.output
        assert 'payment_type' in result.output, result.output
        assert 'cash' in result.output and 'card' in result.output, \
            result.output


class TestANoteWithAQuoteInIt:
    """The quote survives the trip out and back, and the re-import is quiet.

    The reader unescapes every quoted value, so a note written raw came back
    a character shorter — and the comparison that decides `unchanged` reads
    that same note. A posted document was therefore unposted, its entries
    destroyed and rebuilt and the document posted again under a new
    transaction, on every import, for as long as the note held a quote.
    """

    def test_the_export_escapes_it_and_the_book_keeps_the_quote(
            self, tmp_path):
        book = _book(tmp_path)
        out = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        assert 'per \\"Schedule A\\"' in out.read_text(encoding='utf-8')
        assert _entries(book)['Consulting, February']['notes'] == \
            'Agreed rate for the first quarter, per "Schedule A"'

    def test_and_the_export_re_imports_unchanged(self, tmp_path):
        book = _book(tmp_path)
        ledger = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(ledger),
            '--include-business-objects']).exit_code == 0

        again = CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "INV-EVERY-001": unchanged' in again.output, \
            again.output

    def test_and_a_rebuilt_book_holds_the_same_note(self, tmp_path):
        first = _book(tmp_path, 'first.gnucash')
        ledger = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(first), '--output', str(ledger),
            '--include-business-objects']).exit_code == 0

        second = tmp_path / 'second.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(second), str(ledger),
            '--include-business-objects']).exit_code == 0

        assert _entries(second)['Consulting, February']['notes'] == \
            _entries(first)['Consulting, February']['notes']


class TestANoteTypedOnTwoLines:
    """A note with a newline in it — which only GnuCash's own window can put
    there, a ledger being one line per key.

    Written raw it ended the value mid-word and offered the rest of the note
    to the parser as a key of its own, so the block the export wrote was not
    a block. Written `\\n` the note stays on one line, and the reader turns
    it back into a newline: the book that comes back holds the note the book
    that went out held.
    """

    NOTE = 'First line\nSecond line, and a path: C:\\name'

    def _book_with_the_note(self, tmp_path, name='two-lines.gnucash'):
        book = _book(tmp_path, name)

        from gnucash.gnucash_business import Entry

        # Put there with a setter, since no ledger can state a newline —
        # which is the whole point of the case. Opened through the
        # repository, which is what knows that GnuCash 3.8 takes different
        # arguments for it.
        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.NORMAL)
        try:
            q = Query()
            q.search_for('gncEntry')
            q.set_book(repo.book)
            for raw in q.run():
                entry = Entry(instance=raw)
                if entry.GetDescription() == 'Consulting, February':
                    entry.BeginEdit()
                    entry.SetNotes(self.NOTE)
                    entry.CommitEdit()
            q.destroy()
            time.sleep(1.1)   # two saves in one second collide on the backup
            repo.save()
        finally:
            repo.close()
        return book

    def _exported(self, book, tmp_path, name='exported.txt'):
        out = tmp_path / name
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects']).exit_code == 0
        return out

    def test_the_note_is_written_on_one_line(self, tmp_path):
        book = self._book_with_the_note(tmp_path)

        exported = self._exported(book, tmp_path).read_text(encoding='utf-8')

        assert 'notes: "First line\\nSecond line, and a path: C:\\\\name"' \
            in exported
        # And the block is still a block: no line of the export is the tail
        # of that note standing on its own.
        assert not [line for line in exported.splitlines()
                    if line.strip().startswith('Second line')]

    def test_and_a_book_rebuilt_from_it_holds_the_same_note(self, tmp_path):
        first = self._book_with_the_note(tmp_path, 'first.gnucash')
        ledger = self._exported(first, tmp_path)

        second = tmp_path / 'second.gnucash'
        assert CliRunner().invoke(cli, [
            'import', '--new', str(second), str(ledger),
            '--include-business-objects']).exit_code == 0

        assert _entries(second)['Consulting, February']['notes'] == self.NOTE

    def test_and_re_importing_it_changes_nothing(self, tmp_path):
        """The comparison reads the note too, so a note that came back
        changed would rebuild the document on every run — unposting it,
        destroying its entries and posting it again."""
        book = self._book_with_the_note(tmp_path)
        ledger = self._exported(book, tmp_path)

        again = CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "INV-EVERY-001": unchanged' in again.output, \
            again.output


class TestARefusedLineLeavesTheBookAsItWas:
    """A refusal lands before the entry exists, and the book keeps what it had.

    Every other way an entry line can be refused — an account the book has
    not got, a tax table it has not got — is resolved before `Entry(book)`,
    so a refused line leaves no half-built entry in an open edit attached to
    nothing. The three words and the discount figure are resolved there too.

    The document being re-imported has had its entries destroyed by then, so
    what makes this safe is that nothing is saved: the refusal reaches the
    command, which writes no file.
    """

    def test_the_document_still_holds_every_field(self, tmp_path):
        book = _book(tmp_path)
        before = _entries(book)

        ledger = tmp_path / 'refused.txt'
        ledger.write_text(
            Path(LEDGER).read_text(encoding='utf-8')
            .replace('payment_type: card', 'payment_type: visa'),
            encoding='utf-8')

        result = CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                          '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert _entries(book) == before


class TestAKeyThatUsedToBeIgnored:
    """These keys were unknown on an entry block until now.

    An unknown key there was neither stored nor reported — an entry carries
    no custom metadata — so a ledger using `discount:` for a sentence of its
    own imported cleanly and lost it. Reserved now, the same file has to be
    told what happened, in a sentence rather than as `decimal.ConversionSyntax`
    out of the decimal module.
    """

    def test_a_discount_that_is_not_a_number_is_named(self, tmp_path):
        ledger = tmp_path / 'old-shape.txt'
        ledger.write_text(
            Path(LEDGER).read_text(encoding='utf-8')
            .replace('discount: 10', 'discount: "agreed in January"'),
            encoding='utf-8')

        book = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                          str(ledger),
                                          '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'is not a number' in result.output, result.output
        assert 'discount_type' in result.output, result.output

    def test_a_word_gnucash_does_not_know_is_refused(self, tmp_path):
        """`payment_type: visa` is not one of GnuCash's two. Taken as a
        number it would have been written as an integer the engine warns
        about on every read and rewrites on save — a different payment from
        the one asked for."""
        ledger = tmp_path / 'unknown-word.txt'
        ledger.write_text(
            Path(LEDGER).read_text(encoding='utf-8')
            .replace('payment_type: card', 'payment_type: visa'),
            encoding='utf-8')

        book = tmp_path / 'book.gnucash'
        result = CliRunner().invoke(cli, ['import', '--new', str(book),
                                          str(ledger),
                                          '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'cash' in result.output and 'card' in result.output, \
            result.output


class TestWhatTheExportWrites:
    def test_every_field_is_in_the_ledger(self, tmp_path):
        book = _book(tmp_path)
        out = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        exported = out.read_text(encoding='utf-8')

        for expected in ('notes: "Agreed rate for the first quarter, '
                         'per \\"Schedule A\\""',
                         'discount: 10',
                         'discount_type: percent',
                         'discount_how: pretax',
                         'action: "Material"',
                         'notes: "Re-bill to the customer at cost"',
                         'billable: #True',
                         'payment_type: card'):
            assert expected in exported, (expected, exported)


class TestWhatThePrintersWrite:
    """`print-invoice` and `print-bill --format plaintext` write the same
    entry lines `export` writes.

    Three commands write an `entry:` block, and each one used to assemble it
    itself. A field added to one and forgotten in the other two is how a
    printed document came to say less than the ledger about the same line, so
    the three share `services/plaintext_blocks.py` and this asks each printer
    for the document the export test above reads.
    """

    def _printed(self, tmp_path, command, document):
        book = _book(tmp_path)
        out = tmp_path / f'{document}.txt'
        result = CliRunner().invoke(cli, [
            command, str(book), document, '--format', 'plaintext',
            '--output', str(out)])
        assert result.exit_code == 0, result.output
        return out.read_text(encoding='utf-8')

    def test_a_printed_invoice_carries_the_note_and_the_discount(
            self, tmp_path):
        printed = self._printed(tmp_path, 'print-invoice', 'INV-EVERY-001')

        for expected in ('notes: "Agreed rate for the first quarter, '
                         'per \\"Schedule A\\""',
                         'discount: 10',
                         'discount_type: percent',
                         'discount_how: pretax'):
            assert expected in printed, (expected, printed)

    def test_a_printed_bill_carries_the_action_flag_and_payment_type(
            self, tmp_path):
        printed = self._printed(tmp_path, 'print-bill', 'BILL-EVERY-001')

        for expected in ('action: "Material"',
                         'notes: "Re-bill to the customer at cost"',
                         'billable: #True',
                         'payment_type: card'):
            assert expected in printed, (expected, printed)

    def test_a_printed_document_reads_back_into_a_book_unchanged(
            self, tmp_path):
        """A printed document is a file a person imports, so the lines it
        carries have to be the lines the importer already agrees with."""
        book = _book(tmp_path)
        out = tmp_path / 'printed.txt'
        assert CliRunner().invoke(cli, [
            'print-bill', str(book), 'BILL-EVERY-001', '--format', 'plaintext',
            '--output', str(out)]).exit_code == 0

        again = CliRunner().invoke(cli, ['import', str(book), str(out),
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'bill "BILL-EVERY-001": unchanged' in again.output, again.output


class TestTheRoundTrip:
    def test_a_book_rebuilt_from_the_export_holds_the_same_entries(
            self, tmp_path):
        """The whole point: export, import into a fresh book, and every
        field is still there. Dropped by the writer, the second book is
        missing what the first held and nothing says so."""
        first = _book(tmp_path, 'first.gnucash')
        ledger = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(first), '--output', str(ledger),
            '--include-business-objects']).exit_code == 0

        second = tmp_path / 'second.gnucash'
        again = CliRunner().invoke(cli, ['import', '--new', str(second),
                                         str(ledger),
                                         '--include-business-objects'])
        assert again.exit_code == 0, again.output

        assert _entries(second) == _entries(first)

    def test_and_importing_the_export_again_changes_nothing(self, tmp_path):
        """`unchanged`, not `updated`. The comparison that decides has to
        read the same fields the writer writes, or a book is rewritten on
        every run — and a changed discount is missed on every run too."""
        book = _book(tmp_path)
        ledger = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(ledger),
            '--include-business-objects']).exit_code == 0

        again = CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        # By the line each document prints, not by the word "updated": the
        # summary carries an `Updated:` label whatever happens, so searching
        # the whole output for it fails on a run where nothing changed.
        assert 'invoice "INV-EVERY-001": unchanged' in again.output, \
            again.output
        assert 'bill "BILL-EVERY-001": unchanged' in again.output, \
            again.output


