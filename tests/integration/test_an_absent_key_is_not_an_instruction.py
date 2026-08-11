"""A key a block does not name says nothing, and must change nothing.

This is the convention the transaction and split paths have always kept: an
importer asks `if 'notes' in metadata` before writing notes, so a block that
does not mention them leaves what the book holds. The owner paths did not —
they wrote `addr.SetAddr1(md.get('addr1', ''))` — so a block naming only what
it was correcting emptied everything it did not name.

Which is most blocks. A person editing a name writes the name; a printed
invoice carries a partial owner block; an export taken before a field existed
has none. `active:` was the same shape one step further, with a default of
true: a block that did not mention it reactivated an owner the book had
retired.

Clearing a field is still possible, and is now said rather than implied:
`addr1: ""` is present and empty, and empties it.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
FULL = str(FIXTURES / 'an_owner_of_each_kind_with_an_address.txt')
NAME_ONLY = str(FIXTURES / 'an_owner_block_naming_only_a_name.txt')
CLEARED = str(FIXTURES / 'an_owner_block_clearing_its_address.txt')


def _owner(book, oid):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        for kind, wrapper in (('gncCustomer', gb.Customer),
                              ('gncVendor', gb.Vendor)):
            query = Query()
            query.search_for(kind)
            query.set_book(repo.book)
            for raw in query.run():
                owner = wrapper(instance=raw)
                if owner.GetID() != oid:
                    continue
                addr = owner.GetAddr()
                found = {
                    'name': owner.GetName(),
                    'address': [addr.GetAddr1(), addr.GetAddr2(),
                                addr.GetAddr3(), addr.GetAddr4()],
                    'email': addr.GetEmail(),
                    'active': bool(owner.GetActive()),
                }
                query.destroy()
                return found
            query.destroy()
        raise AssertionError(f'no owner {oid}')
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), FULL, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


class TestABlockNamingOnlyAName:
    def _renamed(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), NAME_ONLY, '--include-business-objects'])
        assert result.exit_code == 0, result.output
        return result

    @pytest.mark.parametrize('oid,name', [
        ('C-ADDR', 'Acme Supplies Limited'),
        ('V-ADDR', 'Beta Printing Company'),
    ])
    def test_the_name_it_names_is_changed(self, book, oid, name):
        self._renamed(book)

        assert _owner(book, oid)['name'] == name, _owner(book, oid)

    @pytest.mark.parametrize('oid', ['C-ADDR', 'V-ADDR'])
    def test_the_address_it_does_not_name_is_left(self, book, oid):
        before = _owner(book, oid)['address']
        assert any(before), before

        self._renamed(book)

        assert _owner(book, oid)['address'] == before, _owner(book, oid)

    @pytest.mark.parametrize('oid', ['C-ADDR', 'V-ADDR'])
    def test_the_email_it_does_not_name_is_left(self, book, oid):
        before = _owner(book, oid)['email']
        assert before, before

        self._renamed(book)

        assert _owner(book, oid)['email'] == before, _owner(book, oid)


class TestClearingAFieldOnPurpose:
    """Said rather than implied: an empty value is present, and empties."""

    def test_an_empty_address_line_empties_it(self, book):
        result = CliRunner().invoke(cli, [
            'import', str(book), CLEARED, '--include-business-objects'])
        assert result.exit_code == 0, result.output

        owner = _owner(book, 'C-ADDR')
        assert owner['address'][0] == '', owner
        assert owner['address'][1] == '1 Front Street', owner
