"""A credit note is an invoice this format carries, by one key on the block.

GnuCash's Business → New Credit Note makes a `gncInvoice` with a flag, and
stores its lines negated. Measured on 5.10, against a credit note built the
way that window builds one — flag set, quantity stored negative:

    invoice          stored qty   its own total   what it posts
    invoice                   +2         +200.00   A/R +200, Sales -200
    credit note               -2         +200.00   Sales +200, A/R -200

So the quantities a ledger states are the ones the book holds either way, its
totals read positive either way, and `credit_note: true` is the whole of the
difference. It is written before anything else about the invoice because it
is what the rest of the invoice means: the same lines and the same accounts
post the other way round.

What this replaces is a refusal. Written as an ordinary block — nothing
naming the flag — a credit note rebuilt in a fresh book as an ordinary
invoice and posted against the receivable the wrong way round, which is real
and is what these tests hold shut. Refusing to export the invoice stopped
that, and cost more than it saved: `export --include-business-objects` is the
whole book, so one credit note made the book unexportable.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query

from cli.main import cli
from infrastructure.gnucash.utils import (
    numeric_to_fraction,
    wrap_invoice_or_bill,
)
from repositories.gnucash_repository import GnuCashRepository, SessionMode

LEDGER = str(Path('tests/fixtures') /
             'a_credit_note_and_the_invoice_it_reverses.txt')


def _book(tmp_path, name='book.gnucash'):
    path = tmp_path / name
    made = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    return path


def _invoices(book_path):
    """`{id: {'credit_note': bool, 'total': Fraction, 'splits': {...}}}`."""
    repo = GnuCashRepository(str(book_path))
    repo.open(SessionMode.READ_ONLY)
    try:
        q = Query()
        q.search_for('gncInvoice')
        q.set_book(repo.book)
        found = {}
        for raw in q.run():
            record = wrap_invoice_or_bill(raw)
            posted = record.GetPostedTxn()
            splits = {}
            for split in (posted.GetSplitList() if posted else []):
                name = split.GetAccount().GetName()
                splits[name] = splits.get(name, 0) + numeric_to_fraction(
                    split.GetAmount())
            found[record.GetID()] = {
                'credit_note': bool(record.GetIsCreditNote()),
                'splits': splits,
            }
        q.destroy()
        return found
    finally:
        repo.close()


@pytest.fixture
def imported(tmp_path):
    return _invoices(_book(tmp_path))


class TestWhatTheImportPutsInTheBook:
    """The four invoices post the way GnuCash posts them.

    With tax and discounted on both sides, because a credit note reversing
    an invoice with tax is the ordinary case and it is the only thing that asks
    `gncEntryGetDocTaxValue` and `gncEntryGetDocTaxValues` what a credit
    note's line is worth. Measured on 5.10: 2 × 100.00 less 10 per cent,
    taxed at 10 per cent, posts A/R 198.00 against Sales −180.00 and tax
    −18.00 — and its credit note posts the exact mirror, so GnuCash negates
    a line's tax the same way it negates the line.
    """

    def test_the_invoice_posts_the_way_an_invoice_does(self, imported):
        assert imported['INV-CN-001']['credit_note'] is False
        assert imported['INV-CN-001']['splits'] == {
            'Accounts Receivable': 198, 'Sales': -180, 'Sales Tax': -18}

    def test_and_the_credit_note_posts_the_other_way(self, imported):
        """The whole point of the key: same accounts, same figures, opposite
        direction — the tax among them. Without it this invoice rebuilt as
        an ordinary invoice and added 198.00 to what the customer owed
        instead of taking it off."""
        assert imported['CN-001']['credit_note'] is True
        assert imported['CN-001']['splits'] == {
            'Accounts Receivable': -198, 'Sales': 180, 'Sales Tax': 18}

    def test_the_bill_and_its_credit_note_likewise(self, imported):
        assert imported['BILL-CN-001']['splits'] == {
            'Accounts Payable': -110, 'Supplies': 100, 'Sales Tax': 10}
        assert imported['VCN-001']['credit_note'] is True
        assert imported['VCN-001']['splits'] == {
            'Accounts Payable': 55, 'Supplies': -50, 'Sales Tax': -5}


class TestWhatTheExportWrites:
    @pytest.fixture
    def exported(self, tmp_path):
        book = _book(tmp_path)
        out = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects']).exit_code == 0
        return out.read_text(encoding='utf-8')

    def test_the_flag_is_in_the_ledger(self, exported):
        assert 'credit_note: #True' in exported, exported[:2000]

    def test_and_only_on_the_invoices_that_carry_it(self, exported):
        """Two of the four. `credit_note: false` on every ordinary invoice
        is a line saying nothing about the overwhelming majority of them, and
        its absence already means what a fresh invoice holds."""
        assert exported.count('credit_note: #True') == 2, exported

    def test_the_quantities_are_the_ones_the_book_holds(self, exported):
        """Negated, as GnuCash stores them — so nothing has to be
        reinterpreted on the way back in."""
        assert 'quantity: -2' in exported, exported


class TestTheRoundTrip:
    def test_a_book_rebuilt_from_the_export_posts_the_same_way(self, tmp_path):
        """The failure this replaces: rebuilt from a ledger with no flag, the
        credit note posted as an ordinary invoice and nothing said so."""
        source = _book(tmp_path, 'source.gnucash')
        ledger = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(source), '--output', str(ledger),
            '--include-business-objects']).exit_code == 0

        rebuilt = tmp_path / 'rebuilt.gnucash'
        again = CliRunner().invoke(cli, ['import', '--new', str(rebuilt),
                                         str(ledger),
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert _invoices(rebuilt) == _invoices(source)

    def test_and_importing_the_export_again_changes_nothing(self, tmp_path):
        book = _book(tmp_path)
        ledger = tmp_path / 'exported.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(ledger),
            '--include-business-objects']).exit_code == 0

        again = CliRunner().invoke(cli, ['import', str(book), str(ledger),
                                         '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'invoice "CN-001": unchanged' in again.output, again.output
        assert 'bill "VCN-001": unchanged' in again.output, again.output


class TestEditingTheFlagInTheLedger:
    def _with_the_flag_off(self, tmp_path):
        edited = tmp_path / 'edited.txt'
        text = Path(LEDGER).read_text(encoding='utf-8')
        edited.write_text(
            text.replace('\tcredit_note: true\n\tentry:\n\t\tdate: 2026-03-05',
                         '\tentry:\n\t\tdate: 2026-03-05'),
            encoding='utf-8')
        return edited

    def test_it_is_refused_while_the_invoice_is_posted(self, tmp_path):
        """The flag decides which way the invoice posts, so changing it
        under a posting means re-booking it the other way round — the
        loudest reason there is to ask for the unpost out loud.

        Left out of the comparison that decides `unchanged`, such a ledger
        imported as `unchanged` and the book went on posting the invoice
        the other way; read but rebuilt through, it destroyed the posting
        and re-booked it, reported as `updated`.
        """
        book = _book(tmp_path)

        result = CliRunner().invoke(cli, [
            'import', str(book), str(self._with_the_flag_off(tmp_path)),
            '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'unpost-invoices' in result.output, result.output
        assert _invoices(book)['CN-001']['credit_note'] is True

    def test_and_turning_it_off_reports_it_once_unposted(self, tmp_path):
        book = _book(tmp_path)
        edited = self._with_the_flag_off(tmp_path)
        runner = CliRunner()
        assert runner.invoke(cli, ['unpost-invoices', str(book),
                                   'CN-001']).exit_code == 0

        result = runner.invoke(cli, ['import', str(book), str(edited),
                                     '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'invoice "CN-001": updated' in result.output, result.output
        after = _invoices(book)['CN-001']
        assert after['credit_note'] is False
        # The lines are still stored negative — the ledger changed the flag
        # and nothing else — so an ordinary invoice of −2 posts exactly what
        # the credit note posted. Which is the point: the flag is the only
        # thing that decides the direction, and getting it wrong is silent.
        assert after['splits'] == {
            'Accounts Receivable': -198, 'Sales': 180, 'Sales Tax': 18}


class TestUnpostingItAndChangingTheFlagAtOnce:
    """The fast path that unposts without rebuilding has to read the flag too.

    `posted: none` on an invoice that is posted, with everything else
    matching, takes a path that unposts and returns — it exists to keep the
    entry guids, so it deliberately does not destroy and rebuild. A field it
    does not compare is therefore a field it never writes, and this one was
    missing: a file saying "unpost this, and it is an ordinary invoice" was
    answered `updated` with the book still holding a credit note. Nothing
    said so, the next export contradicted the file just imported, and
    re-posting the invoice put it back the wrong way round.
    """

    def _unposted_as_an_invoice(self, tmp_path):
        book = _book(tmp_path)
        text = Path(LEDGER).read_text(encoding='utf-8')
        # Drop CN-001's flag and its whole `posted:` block: an ordinary
        # invoice, unposted, otherwise identical.
        start = text.index('invoice "CN-001"')
        end = text.index('bill "BILL-CN-001"')
        block = text[start:end]
        edited = block.replace('\tcredit_note: true\n', '')
        edited = edited[:edited.index('\tposted:')] + '\tposted: none\n\n'

        ledger = tmp_path / 'unpost.txt'
        ledger.write_text(text[:start] + edited + text[end:],
                          encoding='utf-8')
        return book, CliRunner().invoke(cli, [
            'import', str(book), str(ledger), '--include-business-objects'])

    def test_the_book_stops_holding_a_credit_note(self, tmp_path):
        book, result = self._unposted_as_an_invoice(tmp_path)

        assert result.exit_code == 0, result.output
        assert _invoices(book)['CN-001']['credit_note'] is False

    def test_and_the_export_agrees_with_the_file_that_was_imported(
            self, tmp_path):
        """The visible cost of missing it: a ledger imported clean, and the
        very next export saying the opposite of it."""
        book, result = self._unposted_as_an_invoice(tmp_path)
        assert result.exit_code == 0, result.output
        out = tmp_path / 'after.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), '--output', str(out),
            '--include-business-objects']).exit_code == 0

        exported = out.read_text(encoding='utf-8')
        cn_block = exported[exported.index('invoice "CN-001"'):]
        cn_block = cn_block[:cn_block.index('\n\n')]
        assert 'credit_note' not in cn_block, cn_block


class TestWhatThePrinterWrites:
    """A printed page states figures, and they have to be the invoice's.

    A credit note's totals read positive and its lines are stored negative,
    so a page that read the lines without the flag would state a column that
    added to the negative of its own total — and the import, recomputing it
    the same way, would have agreed.
    """

    def _printed(self, tmp_path, command, invoice):
        book = _book(tmp_path, f'{invoice}.gnucash')
        page = tmp_path / f'{invoice}.txt'
        result = CliRunner().invoke(cli, [
            command, str(book), invoice,
            '--format', 'plaintext', '--output', str(page)])
        assert result.exit_code == 0, result.output
        return book, page.read_text(encoding='utf-8')

    def test_a_printed_credit_note_states_its_own_total(self, tmp_path):
        """Positive, and the same figures its own posting carries — the net
        after the discount, the tax on it, and a `breakdown:` block naming
        the account the tax reached. Read without the flag, every one of
        these would be the negative of what the invoice states."""
        _book_path, page = self._printed(tmp_path, 'print-invoice', 'CN-001')

        assert 'credit_note: #True' in page, page
        assert 'entry_amount: 180.00' in page, page
        assert 'entry_tax: 18.00' in page, page
        assert 'invoice_subtotal: 180.00' in page, page
        assert 'invoice_tax_total: 18.00' in page, page
        assert 'invoice_total: 198.00' in page, page
        assert 'amount: 18.00' in page, page          # its breakdown block

    def test_and_a_vendors_likewise(self, tmp_path):
        _book_path, page = self._printed(tmp_path, 'print-bill', 'VCN-001')

        assert 'credit_note: #True' in page, page
        assert 'entry_amount: 50.00' in page, page
        assert 'entry_tax: 5.00' in page, page
        assert 'bill_total: 55.00' in page, page

    def test_the_printed_page_re_imports_unchanged(self, tmp_path):
        """Which is the check that the figures on it are the book's: the
        import works them out again and compares every one exactly."""
        book, page = self._printed(tmp_path, 'print-invoice', 'CN-001')
        written = tmp_path / 'page.txt'
        written.write_text(page, encoding='utf-8')

        result = CliRunner().invoke(cli, ['import', str(book), str(written),
                                          '--include-business-objects'])

        assert result.exit_code == 0, result.output
        assert 'invoice "CN-001": unchanged' in result.output, result.output

    def test_and_gnucashs_own_page_draws_one_too(self, tmp_path):
        """`--format html` is GnuCash's own report, which has always known
        the flag — it was only this project's plaintext writer that did
        not."""
        book = _book(tmp_path, 'drawn.gnucash')
        out = tmp_path / 'credit-note.html'

        result = CliRunner().invoke(cli, [
            'print-invoice', str(book), 'CN-001',
            '--format', 'html', '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert 'CN-001' in out.read_text(encoding='utf-8')


class TestAMistypedFlag:
    def test_it_is_refused_by_name(self, tmp_path):
        """As every other flag in a ledger is — read as "not false", a typo
        would have turned an ordinary invoice into a credit note and posted
        it backwards."""
        ledger = tmp_path / 'mistyped.txt'
        text = Path(LEDGER).read_text(encoding='utf-8')
        # Tab-anchored: the key, not the sentence about it in the fixture's
        # own header comment.
        ledger.write_text(text.replace('\tcredit_note: true',
                                       '\tcredit_note: treu', 1),
                          encoding='utf-8')

        result = CliRunner().invoke(cli, ['import', '--new',
                                          str(tmp_path / 'book.gnucash'),
                                          str(ledger),
                                          '--include-business-objects'])

        assert result.exit_code != 0, result.output
        assert 'credit_note' in result.output, result.output
        assert 'neither true nor false' in result.output, result.output
