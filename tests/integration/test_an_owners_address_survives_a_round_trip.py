"""A vendor has an address, and the book is supposed to keep it.

The customer block has carried `addr1:` through `email:` all along; the vendor
block had the same keys with nothing behind them, so they were filed as custom
metadata — a slot named `addr1` rather than the vendor's address. The export
wrote them back out of that slot, so a round trip looked clean while the
address the book actually holds was never touched.

What that costs is visible: `print-bill` renders the vendor's address, and a
book rebuilt from an export of it renders those lines blank.

The same asymmetry ran through the comparison that decides whether a
re-imported owner needs updating. A customer's address was compared and a
vendor's was not, so editing a vendor's address in a ledger and re-importing
reported `unchanged` and changed nothing.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

LEDGER = str(Path('tests/fixtures/an_owner_of_each_kind_with_an_address.txt'))
EDITED = str(Path('tests/fixtures/an_owner_of_each_kind_after_an_edit.txt'))


def _owner_addresses(book):
    """Each owner's address as the book holds it, by id."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        found = {}
        for kind, wrapper in (('gncCustomer', gb.Customer),
                              ('gncVendor', gb.Vendor)):
            query = Query()
            query.search_for(kind)
            query.set_book(repo.book)
            for raw in query.run():
                owner = wrapper(instance=raw)
                addr = owner.GetAddr()
                found[owner.GetID()] = [
                    addr.GetAddr1(), addr.GetAddr2(), addr.GetAddr3(),
                    addr.GetAddr4(), addr.GetEmail(),
                ]
            query.destroy()
        return found
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), LEDGER, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


class TestImportingOne:
    def test_the_customers_address_is_an_address(self, book):
        assert _owner_addresses(book)['C-ADDR'] == [
            'Acme Supplies Ltd', '1 Front Street', 'Toronto ON', 'M5J 1A1',
            'ap@acme.example',
        ], _owner_addresses(book)

    def test_the_vendors_address_is_one_too(self, book):
        assert _owner_addresses(book)['V-ADDR'] == [
            'Beta Printing Inc', '2 Rear Lane', 'Hamilton ON', 'L8P 1A1',
            'invoices@beta.example',
        ], _owner_addresses(book)


class TestExportingAndReadingBack:
    def _round_trip(self, book, tmp_path):
        out = tmp_path / 'out.txt'
        exported = CliRunner().invoke(cli, [
            'export', str(book), str(out), '--include-business-objects'])
        assert exported.exit_code == 0, exported.output

        second = tmp_path / 'second.gnucash'
        back = CliRunner().invoke(cli, [
            'import', '--new', str(second), str(out),
            '--include-business-objects'])
        assert back.exit_code == 0, back.output
        return second, out

    def test_both_addresses_come_back(self, book, tmp_path):
        second, _ = self._round_trip(book, tmp_path)

        assert _owner_addresses(second) == _owner_addresses(book), (
            _owner_addresses(second), _owner_addresses(book))

    def test_the_export_writes_them_as_address_keys(self, book, tmp_path):
        _second, out = self._round_trip(book, tmp_path)

        text = out.read_text()
        assert 'Beta Printing Inc' in text, text
        assert 'invoices@beta.example' in text, text


class TestReImportingAnEdit:
    """An owner edited in the ledger and imported again has to change."""

    def test_the_edit_lands_on_both(self, book, tmp_path):
        again = CliRunner().invoke(cli, [
            'import', str(book), EDITED, '--include-business-objects'])
        assert again.exit_code == 0, again.output

        addresses = _owner_addresses(book)
        assert addresses['C-ADDR'][1] == '3 Front Street', addresses
        assert addresses['V-ADDR'][1] == '4 Rear Lane', addresses

    def test_it_is_reported_as_an_update(self, book, tmp_path):
        again = CliRunner().invoke(cli, [
            'import', str(book), EDITED, '--include-business-objects'])

        assert 'customer "C-ADDR": updated' in again.output, again.output
        assert 'vendor "V-ADDR": updated' in again.output, again.output

    def test_importing_the_same_file_twice_changes_nothing(self, book):
        again = CliRunner().invoke(cli, [
            'import', str(book), LEDGER, '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'unchanged' in again.output, again.output
