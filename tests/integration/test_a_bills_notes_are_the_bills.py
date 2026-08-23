"""A bill's `notes:` must land on the bill, and settle.

An invoice's notes are read, written and compared. A bill's were read and
compared — `_bill_non_payment_matches` asks `bill.GetNotes()` — but never
written: `notes:` was not a known bill key, so it fell into the slot beside
the object and `GetNotes()` stayed empty.

Two costs, and the second is the serious one. `print-bill` renders
`GetNotes()`, so a bill whose ledger states notes printed with none. And the
comparison could never answer `unchanged`, so every import of an unchanged
ledger took the rebuild path — which for a posted bill means unposting it:
destroying the posting transaction, orphaning its payment splits and marking
them, then reposting and re-applying the payments. Every run, on a ledger
nobody had edited.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')
LEDGER = str(FIXTURES / 'two_bills_to_print.txt')


def _bill(book, bill_id):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        for raw in query.run():
            bill = gb.Bill(instance=raw)
            if bill.GetID() != bill_id:
                continue
            found = {
                'notes': bill.GetNotes() or '',
                'slot': get_custom_metadata(bill) or {},
                'posting': (bill.GetPostedTxn().GetGUID().to_string()
                            if bill.GetPostedTxn() is not None else None),
            }
            query.destroy()
            return found
        query.destroy()
        raise AssertionError(f'no {bill_id}')
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(path), ACCOUNTS])
    assert made.exit_code == 0, made.output
    result = CliRunner().invoke(cli, [
        'import', str(path), LEDGER, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


def _bill_with_notes(book):
    """Whichever bill in the fixture states notes."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncInvoice')
        query.set_book(repo.book)
        ids = sorted(gb.Bill(instance=raw).GetID() for raw in query.run())
        query.destroy()
        return ids
    finally:
        repo.close()


class TestTheNotesLand:
    def test_they_are_the_bills_notes(self, book):
        for bill_id in _bill_with_notes(book):
            held = _bill(book, bill_id)
            if 'notes' in held['slot']:
                raise AssertionError(
                    f'{bill_id} keeps its notes in the slot: {held}')
        assert any(_bill(book, b)['notes'] for b in _bill_with_notes(book)), \
            {b: _bill(book, b) for b in _bill_with_notes(book)}


class TestReImportingAPrintedBill:
    """The same loop through the door a printed bill opens.

    `print-bill --format plaintext` writes the block a reader checks against
    the book, and it names less than the ledger does. With the comparison
    reading an absent key as the empty string, a bill that has notes could
    never match a block that omits them — so every re-import unposted it,
    destroyed the posting, orphaned the payments, and built it again.
    """

    def _printed(self, book, tmp_path, bill_id):
        out = tmp_path / f'{bill_id}.txt'
        rendered = CliRunner().invoke(cli, [
            'print-bill', str(book), bill_id, '--format', 'plaintext',
            '--output', str(out)])
        assert rendered.exit_code == 0, rendered.output
        return out

    def test_it_is_not_reported_as_updated(self, book, tmp_path):
        printed = self._printed(book, tmp_path, 'BILL-PRINT-001')

        again = CliRunner().invoke(cli, [
            'import', str(book), str(printed), '--include-business-objects'])
        assert again.exit_code == 0, again.output

        assert 'bill "BILL-PRINT-001": unchanged' in again.output, again.output

    def test_the_posting_transaction_is_the_same_one(self, book, tmp_path):
        printed = self._printed(book, tmp_path, 'BILL-PRINT-001')
        before = _bill(book, 'BILL-PRINT-001')['posting']

        CliRunner().invoke(cli, [
            'import', str(book), str(printed), '--include-business-objects'])

        assert _bill(book, 'BILL-PRINT-001')['posting'] == before, \
            _bill(book, 'BILL-PRINT-001')

    def test_the_notes_are_still_there(self, book, tmp_path):
        printed = self._printed(book, tmp_path, 'BILL-PRINT-001')

        CliRunner().invoke(cli, [
            'import', str(book), str(printed), '--include-business-objects'])

        assert _bill(book, 'BILL-PRINT-001')['notes'], \
            _bill(book, 'BILL-PRINT-001')


class TestReImportingTheSameLedger:
    def test_nothing_is_reported_as_updated(self, book):
        again = CliRunner().invoke(cli, [
            'import', str(book), LEDGER, '--include-business-objects'])
        assert again.exit_code == 0, again.output

        updated = [line for line in again.output.splitlines()
                   if line.startswith('bill ') and 'updated' in line]
        assert not updated, again.output

    def test_the_posting_transaction_is_the_same_one(self, book):
        """A rebuild unposts: the posting is destroyed and made again."""
        before = {b: _bill(book, b)['posting'] for b in _bill_with_notes(book)}

        CliRunner().invoke(cli, [
            'import', str(book), LEDGER, '--include-business-objects'])

        after = {b: _bill(book, b)['posting'] for b in _bill_with_notes(book)}
        assert after == before, (after, before)


class TestABookThatKeptThemInTheSlot:
    """The version before this one put a bill's notes in the slot.

    `notes` and `billing_id` were not known bill keys then, so `import_bill`
    filed them beside the object and `GetNotes()` stayed empty. Now that they
    are fields, the writers read the field and filter the slot — so a book
    written by the shipped version exports a bill block with no `notes:` line
    at all, and rebuilding from that export loses the note for good.

    The address keys hit this first and the fallback was written for them; the
    bill's own text was twenty lines away in the same file and did not get
    it. The state is built here as the previous version left it, because the
    format no longer has a way to say it.
    """

    @pytest.fixture
    def legacy(self, book):
        repo = GnuCashRepository(str(book))
        repo.open(mode=SessionMode.NORMAL)
        try:
            query = Query()
            query.search_for('gncInvoice')
            query.set_book(repo.book)
            for raw in query.run():
                bill = gb.Bill(instance=raw)
                if bill.GetID() != 'BILL-PRINT-001':
                    continue
                bill.BeginEdit()
                bill.SetNotes('')
                set_custom_metadata(bill, {'notes': 'Two taxes and a payment'})
                bill.CommitEdit()
            query.destroy()

            query = Query()
            query.search_for('gncVendor')
            query.set_book(repo.book)
            for raw in query.run():
                vendor = gb.Vendor(instance=raw)
                if vendor.GetID() != 'V-PRINT-A':
                    continue
                vendor.BeginEdit()
                addr = vendor.GetAddr()
                for setter in (addr.SetAddr1, addr.SetAddr2, addr.SetAddr3,
                               addr.SetAddr4, addr.SetEmail):
                    setter('')
                set_custom_metadata(vendor, {'addr1': 'Alpha Supply Ltd'})
                vendor.CommitEdit()
            query.destroy()
            repo.save()
        finally:
            repo.close()
        return book

    def test_the_export_still_carries_the_notes(self, legacy, tmp_path):
        out = tmp_path / 'out.txt'
        exported = CliRunner().invoke(cli, [
            'export', str(legacy), str(out), '--include-business-objects'])
        assert exported.exit_code == 0, exported.output

        block = out.read_text().split('bill "BILL-PRINT-001"')[1]
        assert 'Two taxes and a payment' in block.split('\n\n')[0], block

    def test_a_rebuild_keeps_them(self, legacy, tmp_path):
        out = tmp_path / 'out.txt'
        CliRunner().invoke(cli, [
            'export', str(legacy), str(out), '--include-business-objects'])

        fresh = tmp_path / 'fresh.gnucash'
        built = CliRunner().invoke(cli, [
            'import', '--new', str(fresh), str(out),
            '--include-business-objects'])
        assert built.exit_code == 0, built.output

        assert _bill(fresh, 'BILL-PRINT-001')['notes'] == \
            'Two taxes and a payment', _bill(fresh, 'BILL-PRINT-001')

    def test_the_rendered_bill_shows_them(self, legacy, tmp_path):
        """The bill a person actually reads, not only the block.

        `print-bill --format html` is the bill itself. Reading the field
        alone, it printed the notes line blank on a book that has them.
        """
        out = tmp_path / 'bill.html'
        rendered = CliRunner().invoke(cli, [
            'print-bill', str(legacy), 'BILL-PRINT-001', '--format', 'html',
            '--output', str(out)])
        assert rendered.exit_code == 0, rendered.output

        assert 'Two taxes and a payment' in out.read_text(), out.read_text()

    def test_the_rendered_bill_shows_the_address(self, legacy, tmp_path):
        """The other half of the same read, and the one a bill is sent with."""
        out = tmp_path / 'bill.html'
        rendered = CliRunner().invoke(cli, [
            'print-bill', str(legacy), 'BILL-PRINT-001', '--format', 'html',
            '--output', str(out)])
        assert rendered.exit_code == 0, rendered.output

        assert 'Alpha Supply Ltd' in out.read_text(), out.read_text()

    def test_the_printed_bill_carries_them_too(self, legacy, tmp_path):
        printed = tmp_path / 'printed.txt'
        rendered = CliRunner().invoke(cli, [
            'print-bill', str(legacy), 'BILL-PRINT-001', '--format',
            'plaintext', '--output', str(printed)])
        assert rendered.exit_code == 0, rendered.output

        assert 'Two taxes and a payment' in printed.read_text(), \
            printed.read_text()
