"""An ID two customers in the book have is refused, not guessed at.

GnuCash does not keep a customer's ID unique, so a book made in GnuCash can
hold two customers with one ID. A block that states only that ID cannot say
which of them it means: a customer block would update one of the two, and an
invoice would be booked to one of the two. So the import refuses both and says
how many records have the ID.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


@pytest.fixture
def book(tmp_path):
    """Two customers with the ID C-TWICE, as GnuCash's own dialog allows."""
    from gnucash.gnucash_business import Customer

    path = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(path), ACCOUNTS])
    assert made.exit_code == 0, made.output
    repo = GnuCashRepository(str(path))
    repo.open(SessionMode.NORMAL)
    try:
        cad = repo.book.get_table().lookup('CURRENCY', 'CAD')
        Customer(repo.book, 'C-TWICE', cad, 'Acme')
        Customer(repo.book, 'C-TWICE', cad, 'Acme Holdings')
        repo.save()
    finally:
        repo.close()
    return path


@pytest.mark.parametrize('fixture, said', [
    ('tests/fixtures/a_customer_whose_id_two_customers_have.txt',
     'customer "C-TWICE": book already has 2 records with this id'),
    ('tests/fixtures/an_invoice_for_a_customer_id_two_customers_have.txt',
     "customer_id 'C-TWICE' matches 2 records"),
], ids=['customer', 'invoice'])
def test_the_block_is_refused(book, fixture, said):
    result = CliRunner().invoke(cli, ['import', str(book), fixture,
                                      '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert said in result.output, result.output
