"""`unpost-invoices` acts on the record its argument names, or on none.

Unposting destroys a posting transaction and orphans whatever paid it, so the
one thing the command must not do is guess which record was meant. Two ways an
argument can fail to name exactly one, and both are answered rather than
assumed:

- a `--by-guid` argument that is a well-formed guid and names nothing in this
  book — a record deleted since the guid was copied, or a guid from another
  book;
- an id that two records share. The importer has enforced id uniqueness since
  Q-008, so this is legacy data or a hand-edited file, and there is no rule
  that picks between them: the answer is to say so and name `--by-guid` as the
  way to be specific.

The delete side of the same pair is `test_delete_invoice_bill.py`.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_delete_invoice_bill import _create_duplicate_invoice
from tests.integration.test_unpost_invoice_bill import (
    _fixture,
    _setup_book_with,
)

# Well-formed and belongs to nothing: 32 hex digits, so it is past the parser
# and into the lookup, which is the code under test here.
A_GUID_NAMING_NOTHING = 'deadbeefdeadbeefdeadbeefdeadbeef'


@pytest.fixture
def book(tmp_path):
    return _setup_book_with(CliRunner(), tmp_path, _fixture('q010_invoice_posted'))


class TestAGuidNamingNothing:
    def test_it_is_reported_as_not_found(self, book):
        result = CliRunner().invoke(cli, [
            'unpost-invoices', str(book), '--by-guid', A_GUID_NAMING_NOTHING])

        assert result.exit_code == 1, result.output
        assert 'not found' in result.output, result.output

    def test_the_guid_asked_for_is_the_one_reported(self, book):
        """Or the reader cannot tell which of a batch was the miss."""
        result = CliRunner().invoke(cli, [
            'unpost-invoices', str(book), '--by-guid', A_GUID_NAMING_NOTHING])

        assert A_GUID_NAMING_NOTHING in result.output.replace('-', ''), result.output

    def test_the_posted_invoice_is_left_alone(self, book):
        """A miss is not a reason to act on the book's other records."""
        CliRunner().invoke(cli, [
            'unpost-invoices', str(book), '--by-guid', A_GUID_NAMING_NOTHING])
        after = CliRunner().invoke(cli, ['unpost-invoices', str(book), 'INV-001'])

        assert after.exit_code == 0, after.output
        assert 'unposted' in after.output, after.output


class TestAnIdTwoRecordsShare:
    @pytest.fixture
    def shared(self, book):
        """The same book with a second invoice created under the same id.

        Bypassing the importer, which refuses it — the state exists in books
        written before Q-008 and in hand-edited files, and this is how it is
        reproduced. Documented on `_create_duplicate_invoice`.
        """
        _create_duplicate_invoice(book, dup_id='INV-001', customer_id='C001',
                                  currency_code='CAD')
        return book

    def test_it_is_refused(self, shared):
        result = CliRunner().invoke(cli, ['unpost-invoices', str(shared), 'INV-001'])

        assert result.exit_code == 1, result.output
        assert 'multiple records share this id' in result.output, result.output

    def test_the_reader_is_told_how_to_be_specific(self, shared):
        result = CliRunner().invoke(cli, ['unpost-invoices', str(shared), 'INV-001'])

        assert '--by-guid' in result.output, result.output

    def test_neither_record_is_unposted(self, shared):
        """Refusing means acting on neither, not on the first one found."""
        result = CliRunner().invoke(cli, ['unpost-invoices', str(shared), 'INV-001'])

        assert ': unposted' not in result.output, result.output
