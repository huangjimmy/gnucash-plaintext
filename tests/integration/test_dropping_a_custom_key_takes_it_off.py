"""Removing a key from a ledger has to remove it from the book — when it says so.

Anything the format has no setter for is kept in a slot beside the object and
written back out on export, so a ledger can carry a field this tool does not
understand and not lose it. Taking that field off is then an edit like any
other, and it has to land.

It could not: the writer set the slot only when the file still had something
to put in it, so the last key could never be removed. The object differed from
the file for good, and every import from then on reported `updated` and saved
the book again — an unchanged re-import writing the book.

Writing the slot wholesale instead would have made every *partial* block a
delete, and most blocks are partial: a person names what they are changing, a
printed invoice carries less than that. So the rule is the one the address
lines follow — a key the block does not name says nothing, and a key named
empty is removed.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
WITH_KEY = str(FIXTURES / 'an_owner_with_a_custom_key.txt')
WITHOUT = str(FIXTURES / 'an_owner_after_dropping_a_custom_key.txt')
CHANGED = str(FIXTURES / 'an_owner_after_changing_a_custom_key.txt')
SILENT = str(FIXTURES / 'an_owner_block_naming_only_a_name.txt')


def _custom(book):
    """Each owner's custom-metadata slot, by id."""
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
                found[owner.GetID()] = get_custom_metadata(owner) or {}
            query.destroy()
        return found
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), WITH_KEY, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


class TestTheKeyIsThereFirst:
    def test_both_owners_carry_it(self, book):
        assert _custom(book) == {
            'C-KEY': {'department': 'north'},
            'V-KEY': {'department': 'south'},
        }, _custom(book)


class TestChangingItsValue:
    """The sharper half: a slot written outside an edit never reaches disk.

    Measured — a customer's `plaintext_metadata` set after `CommitEdit` read
    back as its old value after a save. So no change to a custom key on an
    owner the book already had ever landed, and, the slot never changing, the
    owner differed from the file for good and reported `updated` every run.
    """

    def _changed(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), CHANGED, '--include-business-objects'])
        assert result.exit_code == 0, result.output
        return result

    def test_the_new_value_is_in_the_book(self, book):
        self._changed(book)

        assert _custom(book) == {
            'C-KEY': {'department': 'east'},
            'V-KEY': {'department': 'west'},
        }, _custom(book)

    def test_the_next_run_has_nothing_left_to_do(self, book):
        self._changed(book)

        again = CliRunner().invoke(cli, [
            'import', str(book), CHANGED, '--include-business-objects'])

        assert 'customer "C-KEY": unchanged' in again.output, again.output
        assert 'vendor "V-KEY": unchanged' in again.output, again.output


class TestDroppingIt:
    def _dropped(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), WITHOUT, '--include-business-objects'])
        assert result.exit_code == 0, result.output
        return result

    def test_it_is_gone_from_both(self, book):
        self._dropped(book)

        assert _custom(book) == {'C-KEY': {}, 'V-KEY': {}}, _custom(book)

    def test_a_block_that_does_not_name_it_leaves_it(self, book):
        """Most blocks name only what they are changing.

        The file imported here describes two other owners, so it is a partial
        ledger as well as a partial block — which is the ordinary case.
        """
        silent = CliRunner().invoke(cli, [
            'import', str(book), SILENT, '--include-business-objects'])
        assert silent.exit_code == 0, silent.output

        held = _custom(book)
        assert held['C-KEY'] == {'department': 'north'}, held
        assert held['V-KEY'] == {'department': 'south'}, held

    def test_the_run_says_it_updated_them(self, book):
        result = self._dropped(book)

        assert 'customer "C-KEY": updated' in result.output, result.output
        assert 'vendor "V-KEY": updated' in result.output, result.output

    def test_the_next_run_has_nothing_left_to_do(self, book):
        """What `updated` forever costs: the book is written every run."""
        self._dropped(book)

        again = CliRunner().invoke(cli, [
            'import', str(book), WITHOUT, '--include-business-objects'])

        assert 'customer "C-KEY": unchanged' in again.output, again.output
        assert 'vendor "V-KEY": unchanged' in again.output, again.output

    def test_the_export_no_longer_carries_it(self, book, tmp_path):
        self._dropped(book)

        out = tmp_path / 'out.txt'
        exported = CliRunner().invoke(cli, [
            'export', str(book), str(out), '--include-business-objects'])
        assert exported.exit_code == 0, exported.output
        assert 'department' not in out.read_text(), out.read_text()
