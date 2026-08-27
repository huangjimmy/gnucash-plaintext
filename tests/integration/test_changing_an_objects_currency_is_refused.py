"""An object's currency cannot be changed by editing the ledger.

`currency:` is required on a customer, a vendor, an invoice and a bill, and
every export writes it back, so it reads as a field like any other. On an
object the book already holds it was neither compared nor applied: the edit
reported `unchanged`, the book kept the currency the object was created with,
and the next export wrote that currency back over the edit. The ledger and the
book then disagreed for good, with the ledger losing and nothing said.

Applying it is not a small edit. An owner's currency is what their invoices
and bills are created in, and a posted invoice's is what its receivable splits
are denominated in — changing either means creating them again, which is a
decision rather than a field. So the file is refused, and says which two
currencies it is between, in the words that fit the kind it is refusing.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner
from gnucash import Query
from gnucash import gnucash_business as gb

from cli.main import cli
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
IN_CAD = str(FIXTURES / 'owners_and_an_invoice_in_cad.txt')
# One object moved per file, because the import stops at the first it refuses.
MOVED = {
    'C-CCY': str(FIXTURES / 'owners_with_the_customer_in_usd.txt'),
    'V-CCY': str(FIXTURES / 'owners_with_the_vendor_in_usd.txt'),
    'INV-CCY': str(FIXTURES / 'owners_with_the_invoice_in_usd.txt'),
    'BILL-CCY': str(FIXTURES / 'owners_with_the_bill_in_usd.txt'),
}
ALL_CAD = {'C-CCY': 'CAD', 'V-CCY': 'CAD',
           'INV-CCY': 'CAD', 'BILL-CCY': 'CAD'}


def _currencies(book):
    """Each object's currency, by id."""
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        found = {}
        for kind, wrapper in (('gncCustomer', gb.Customer),
                              ('gncVendor', gb.Vendor),
                              ('gncInvoice', gb.Invoice)):
            query = Query()
            query.search_for(kind)
            query.set_book(repo.book)
            for raw in query.run():
                obj = wrapper(instance=raw)
                found[obj.GetID()] = obj.GetCurrency().get_mnemonic()
            query.destroy()
        return found
    finally:
        repo.close()


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), IN_CAD, '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


class TestTheBookIsInCadFirst:
    def test_all_four_are(self, book):
        assert _currencies(book) == ALL_CAD, _currencies(book)


class TestEditingItToUsd:
    def _again(self, book, oid):
        return CliRunner().invoke(cli, [
            'import', str(book), MOVED[oid], '--include-business-objects'])

    @pytest.mark.parametrize('oid', list(MOVED))
    def test_the_run_refuses(self, book, oid):
        result = self._again(book, oid)

        assert result.exit_code != 0, result.output

    @pytest.mark.parametrize('oid', list(MOVED))
    def test_it_is_refused_by_name_and_names_both_currencies(self, book, oid):
        """The assertion that separates refusing from skipping in silence.

        Asked only whether the id appears in the output, an earlier version of
        this passed while two of the three were being skipped: every directive
        prints a line of its own, so `customer "C-CCY": unchanged` satisfied
        it.
        """
        result = self._again(book, oid)

        refusals = [line for line in result.output.splitlines()
                    if oid in line and 'CAD' in line and 'USD' in line]
        assert refusals, result.output

    @pytest.mark.parametrize('oid,says,remedy', [
        ('C-CCY', "a customer's invoices and bills are created in",
         'create the new ones under a customer in USD'),
        ('V-CCY', "a vendor's invoices and bills are created in",
         'create the new ones under a vendor in USD'),
        ('INV-CCY', "this invoice's lines and its posting are denominated",
         'create a new invoice in USD'),
        ('BILL-CCY', "this bill's lines and its posting are denominated",
         'create a new bill in USD'),
    ])
    def test_it_says_what_that_kinds_currency_is(self, book, oid, says,
                                                 remedy):
        """The sentence has to fit the kind it is refusing, both halves of it.

        One sentence served all four kinds by naming what they hold
        generically, and a rename of that word left the owner sentence
        addressed to a record: *"A currency is what an invoice's invoices and
        bills are created in … create the new ones under an invoice."* Every
        other assertion here reads the two currency codes, which that text
        still carried, so the run stayed green while the sentence stopped
        meaning anything.

        The guard added then read the `what` clause alone, which left the
        remedy — the half a reader actually acts on — free to be renamed into
        nonsense by the next pass. It is read here too, for all four kinds.
        """
        result = self._again(book, oid)

        assert says in result.output, result.output
        assert remedy in result.output, result.output

    @pytest.mark.parametrize('oid', list(MOVED))
    def test_it_does_not_report_itself_unchanged(self, book, oid):
        result = self._again(book, oid)

        unchanged = [line for line in result.output.splitlines()
                     if oid in line and 'unchanged' in line]
        assert not unchanged, result.output

    @pytest.mark.parametrize('oid', list(MOVED))
    def test_the_book_is_left_as_it_was(self, book, oid):
        self._again(book, oid)

        assert _currencies(book) == ALL_CAD, _currencies(book)

    def test_the_same_currency_is_not_a_change(self, book):
        """The ordinary re-import still reports unchanged."""
        again = CliRunner().invoke(cli, [
            'import', str(book), IN_CAD, '--include-business-objects'])

        assert again.exit_code == 0, again.output
        assert 'unchanged' in again.output, again.output
