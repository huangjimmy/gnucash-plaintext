"""A vendor whose slot still holds an address line is updated, once.

Vendors had no address setters in earlier releases, so a vendor block's
`addr1` was stored as custom metadata: a slot named `addr1` rather than the
address. A book written then still holds that slot. Read again with a block
giving `addr1`, the vendor is out of date whatever the file says, because the
slot holds a key that has since become a field: the run says `updated`, and the
next one `unchanged`, with the key gone from the slot.
"""

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import get_custom_metadata, set_custom_metadata
from repositories.gnucash_repository import GnuCashRepository, SessionMode

VENDOR = 'tests/fixtures/a_vendor_written_with_the_old_address_keys.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _slot_of(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return dict(get_custom_metadata(repo.book.VendorLookupByID('V-OLD')))
    finally:
        repo.close()


def _the_slot_an_earlier_release_wrote(book):
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.NORMAL)
    try:
        vendor = repo.book.VendorLookupByID('V-OLD')
        vendor.BeginEdit()
        set_custom_metadata(vendor, {**get_custom_metadata(vendor), 'addr1': 'Beta Printing Inc'})
        vendor.CommitEdit()
        repo.save()
    finally:
        repo.close()


def test_it_is_updated_once_and_the_slot_loses_the_key(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = _run('import', '--new', book, VENDOR, '--include-business-objects')
    assert made.exit_code == 0, made.output
    _the_slot_an_earlier_release_wrote(book)
    assert 'addr1' in _slot_of(book)

    first = _run('import', book, VENDOR, '--include-business-objects')
    second = _run('import', book, VENDOR, '--include-business-objects')

    assert 'vendor "V-OLD": updated' in first.output, first.output
    assert 'vendor "V-OLD": unchanged' in second.output, second.output
    assert 'addr1' not in _slot_of(book)
