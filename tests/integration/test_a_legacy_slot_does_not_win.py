"""A field that used to live in the slot must not outvote the real one.

Before vendors had address setters, `addr1:`…`email:` on a vendor block were
kept in the slot beside the object, because that is where anything the format
had no setter for went. Books written then still hold them there.

Now those keys are the vendor's address, and nothing was moving them: the
export wrote the address line from the address *and* again from the slot, and
the parser keeps the last value for a repeated key — so the stale copy, coming
second, won. Change the address in GnuCash, export, re-import, and the address
reverts to what it was before, with the run reporting `unchanged`.

The state is built here the way an earlier version left it — the slot written
directly — because the format no longer has a way to say it.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode

LEDGER = str(Path('tests/fixtures/an_owner_of_each_kind_with_an_address.txt'))


def _vendor(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('gncVendor')
        query.set_book(repo.book)
        for raw in query.run():
            vendor = gb.Vendor(instance=raw)
            if vendor.GetID() != 'V-ADDR':
                continue
            found = {
                'addr1': vendor.GetAddr().GetAddr1(),
                'slot': get_custom_metadata(vendor) or {},
            }
            query.destroy()
            return found
        query.destroy()
        raise AssertionError('no V-ADDR')
    finally:
        repo.close()


@pytest.fixture
def legacy(tmp_path):
    """A book as the version before vendor addresses left it."""
    path = tmp_path / 'legacy.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), LEDGER, '--include-business-objects'])
    assert result.exit_code == 0, result.output

    repo = GnuCashRepository(str(path))
    repo.open(mode=SessionMode.NORMAL)
    try:
        query = Query()
        query.search_for('gncVendor')
        query.set_book(repo.book)
        for raw in query.run():
            vendor = gb.Vendor(instance=raw)
            if vendor.GetID() != 'V-ADDR':
                continue
            # As the previous version left it: the address keys went to the
            # slot because nothing set them on the vendor, so the real
            # address is empty and the slot holds it.
            vendor.BeginEdit()
            addr = vendor.GetAddr()
            for setter in (addr.SetAddr1, addr.SetAddr2, addr.SetAddr3,
                           addr.SetAddr4, addr.SetEmail):
                setter('')
            set_custom_metadata(vendor, {'addr1': 'Beta Printing Inc',
                                         'department': 'south'})
            vendor.CommitEdit()
        query.destroy()
        repo.save()
    finally:
        repo.close()
    return path


def _export(book, tmp_path, name='out.txt'):
    out = tmp_path / name
    result = CliRunner().invoke(cli, [
        'export', str(book), str(out), '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out


class TestExportingSuchABook:
    def test_the_address_is_still_written(self, legacy, tmp_path):
        """It is the only copy the book has: dropping it loses the address."""
        text = _export(legacy, tmp_path).read_text()

        vendor_block = text.split('vendor "V-ADDR"')[1].split('\n\n')[0]
        assert 'Beta Printing Inc' in vendor_block, vendor_block

    def test_the_address_line_is_written_once(self, legacy, tmp_path):
        text = _export(legacy, tmp_path).read_text()

        vendor_block = text.split('vendor "V-ADDR"')[1].split('\n\n')[0]
        assert vendor_block.count('addr1:') == 1, vendor_block

    def test_a_key_that_is_still_the_slot_is_kept(self, legacy, tmp_path):
        """Only the keys that became real fields leave the slot."""
        text = _export(legacy, tmp_path).read_text()

        vendor_block = text.split('vendor "V-ADDR"')[1].split('\n\n')[0]
        assert 'department: "south"' in vendor_block, vendor_block


class TestDeletingTheLine:
    """Taking the line out of an export means "no address", not "restore it".

    The fallback fills the field from the slot precisely when the block is
    silent — so on a book whose address still lives in the slot, deleting the
    line a reader had just been given wrote the old address back. An absent
    key causing a write is the inversion of the rule the rest of this follows.
    """

    def _without_the_line(self, legacy, tmp_path):
        text = _export(legacy, tmp_path, 'full.txt').read_text()
        cut = tmp_path / 'cut.txt'
        cut.write_text('\n'.join(line for line in text.splitlines()
                                  if 'Beta Printing Inc' not in line) + '\n')
        return cut

    def test_nothing_is_written_onto_the_vendor(self, legacy, tmp_path):
        """An absent key says nothing, so it cannot cause a write either."""
        cut = self._without_the_line(legacy, tmp_path)

        back = CliRunner().invoke(cli, [
            'import', str(legacy), str(cut), '--include-business-objects'])
        assert back.exit_code == 0, back.output

        assert _vendor(legacy)['addr1'] == '', _vendor(legacy)

    def test_the_only_copy_is_not_dropped_either(self, legacy, tmp_path):
        """Silence is not an instruction in either direction.

        The slot holds the only copy this book has, so dropping it on a block
        that says nothing about the key would lose the address outright.
        Clearing it is said with `addr1: ""`, as everywhere else.
        """
        cut = self._without_the_line(legacy, tmp_path)

        CliRunner().invoke(cli, [
            'import', str(legacy), str(cut), '--include-business-objects'])

        assert _vendor(legacy)['slot'].get('addr1') == 'Beta Printing Inc', \
            _vendor(legacy)


class TestReadingItBack:
    def test_the_address_moves_onto_the_vendor(self, legacy, tmp_path):
        """The slot was the only copy; the import must not just drop it."""
        first = _export(legacy, tmp_path, 'first.txt')
        back = CliRunner().invoke(cli, [
            'import', str(legacy), str(first), '--include-business-objects'])
        assert back.exit_code == 0, back.output

        assert _vendor(legacy)['addr1'] == 'Beta Printing Inc', _vendor(legacy)

    def test_a_rebuild_of_such_a_book_keeps_the_address(self, legacy,
                                                        tmp_path):
        """Export, import into a fresh book — the documented rebuild."""
        first = _export(legacy, tmp_path, 'first.txt')
        fresh = tmp_path / 'fresh.gnucash'
        built = CliRunner().invoke(cli, [
            'import', '--new', str(fresh), str(first),
            '--include-business-objects'])
        assert built.exit_code == 0, built.output

        assert _vendor(fresh)['addr1'] == 'Beta Printing Inc', _vendor(fresh)

    def test_the_stale_copy_does_not_revert_the_address(self, legacy,
                                                        tmp_path):
        """The failure: the address reverts and the run says `unchanged`."""
        first = _export(legacy, tmp_path, 'first.txt')
        back = CliRunner().invoke(cli, [
            'import', str(legacy), str(first), '--include-business-objects'])
        assert back.exit_code == 0, back.output

        assert _vendor(legacy)['addr1'] == 'Beta Printing Inc', _vendor(legacy)

    def test_the_slot_no_longer_holds_the_address(self, legacy, tmp_path):
        first = _export(legacy, tmp_path, 'first.txt')
        CliRunner().invoke(cli, [
            'import', str(legacy), str(first), '--include-business-objects'])

        assert 'addr1' not in _vendor(legacy)['slot'], _vendor(legacy)
        assert _vendor(legacy)['slot'] == {'department': 'south'}, \
            _vendor(legacy)
