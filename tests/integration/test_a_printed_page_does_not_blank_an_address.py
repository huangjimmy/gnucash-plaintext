"""Re-importing a printed invoice or bill must not empty the owner's address.

Both renderers emit an owner block so the printed file can be read back —
`print-invoice --format plaintext` is a page a person keeps, and reading
one is how they check it against the book. The block was deliberately minimal,
on the reasoning that the recipient already has the address.

An address key absent from a block does not mean "leave it alone": the
importer sets every field the format knows, and an absent one is the empty
string. So reading a printed page back emptied the owner's address, and
the next `print-invoice` printed a page with nothing where the address had
been.

The block carries the address now, which is also what makes the printed file
self-contained in the way its own docstring claims.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode

LEDGER = str(Path('tests/fixtures/an_owner_of_each_kind_with_an_address.txt'))
INVOICES = str(Path('tests/fixtures/an_invoice_for_each_owner.txt'))


def _address_of(book, oid):
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
                found = [addr.GetAddr1(), addr.GetAddr2(), addr.GetAddr3(),
                         addr.GetAddr4(), addr.GetEmail()]
                query.destroy()
                return found
            query.destroy()
        raise AssertionError(f'no owner {oid}')
    finally:
        repo.close()


def _custom_of(book, oid):
    """The slot beside the owner, where keys the format does not know live."""
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
                found = get_custom_metadata(owner) or {}
                query.destroy()
                return found
            query.destroy()
        raise AssertionError(f'no owner {oid}')
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    for ledger in (LEDGER, INVOICES):
        result = CliRunner().invoke(cli, [
            'import', *([] if ledger == INVOICES else ['--new']), str(path),
            ledger, '--include-business-objects'])
        assert result.exit_code == 0, result.output
    return path


class TestReadingAPrintedPageBack:
    @pytest.mark.parametrize('command,page,oid', [
        ('print-invoice', 'INV-ADDR', 'C-ADDR'),
        ('print-bill', 'BILL-ADDR', 'V-ADDR'),
    ])
    def test_the_owners_address_survives(self, book, tmp_path, command,
                                         page, oid):
        before = _address_of(book, oid)
        assert any(before), before

        printed = tmp_path / f'{page}.txt'
        rendered = CliRunner().invoke(cli, [
            command, str(book), page, '--format', 'plaintext',
            '--output', str(printed)])
        assert rendered.exit_code == 0, rendered.output

        back = CliRunner().invoke(cli, [
            'import', str(book), str(printed), '--include-business-objects'])
        assert back.exit_code == 0, back.output

        assert _address_of(book, oid) == before, (
            _address_of(book, oid), before)

    @pytest.mark.parametrize('command,page,oid,value', [
        ('print-invoice', 'INV-ADDR', 'C-ADDR', 'north'),
        ('print-bill', 'BILL-ADDR', 'V-ADDR', 'south'),
    ])
    def test_a_key_the_format_does_not_know_survives_too(
            self, book, tmp_path, command, page, oid, value):
        """A block that names no such key is not asking for it to be dropped.

        Writing the slot only when the file still had something to put there
        meant a key could never be removed; writing it always makes every
        partial block a delete. What resolves the two is the block carrying
        what it did not set out to change — which is what the export does.
        """
        printed = tmp_path / f'{page}-custom.txt'
        rendered = CliRunner().invoke(cli, [
            command, str(book), page, '--format', 'plaintext',
            '--output', str(printed)])
        assert rendered.exit_code == 0, rendered.output

        back = CliRunner().invoke(cli, [
            'import', str(book), str(printed), '--include-business-objects'])
        assert back.exit_code == 0, back.output

        assert _custom_of(book, oid) == {'department': value}, \
            _custom_of(book, oid)
