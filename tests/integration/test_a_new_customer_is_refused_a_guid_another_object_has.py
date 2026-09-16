"""A new customer asking for a guid a vendor or a tax table already has is refused.

A block may give the guid a new object is to have, which is how a ledger
rebuilds a book with the guids it came from. GnuCash keeps one guid to one
object whatever kind it is, so forcing a guid the book already gives a vendor
or a tax table would leave two objects answering to it. The import refuses the
customer and says which kind of object has the guid.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.gnucash_importer import _iter_taxtables, _taxtable_guid_str

HOLDERS = 'tests/fixtures/a_vendor_and_a_tax_table_whose_guids_a_customer_asks_for.txt'
CUSTOMER = 'tests/fixtures/a_customer_asking_for_a_guid.txt'


def _the_guid_of(book, kind):
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        if kind == 'vendor':
            return repo.book.VendorLookupByID('V-TAKEN').GetGUID().to_string()
        table, = _iter_taxtables(repo.book)
        return _taxtable_guid_str(table)
    finally:
        repo.close()


@pytest.mark.parametrize('kind', ['vendor', 'taxtable'])
def test_the_customer_is_refused_and_the_kind_holding_the_guid_is_said(tmp_path, kind):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), HOLDERS,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    guid = _the_guid_of(book, kind)
    customer = tmp_path / 'customer.txt'
    customer.write_text(Path(CUSTOMER).read_text().replace('{guid}', guid))

    result = CliRunner().invoke(cli, ['import', str(book), str(customer),
                                      '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert f'guid {guid} is already used by an existing {kind}' in result.output, \
        result.output
