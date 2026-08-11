"""Books whose metadata slots hold something this tool did not write.

Both readers say so themselves — "written by an external tool or older
version" — and both have a branch for it that nothing reached (T-009). The
slots are ordinary GnuCash KVP: any program with the file open can put a
string there, and GnuCash itself will keep it.

So the state is reached the way it is reached in life — the slot is written
with the same writer the product uses, and the book is then handed to a real
command. What is under test is what `set-book-key`, `import` and `export` do
when they meet it, which is the question a fault injected into the reader
cannot answer.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.kvp import (
    COMPANY_CUSTOM_SECTION,
    COMPANY_CUSTOM_SLOT,
    PT_DATA_SLOT,
    _set_string_slot,
    set_book_string_option,
)
from repositories.gnucash_repository import GnuCashRepository, SessionMode

FIXTURES = Path('tests/fixtures')
ACCOUNTS = str(FIXTURES / 'q019_accounts.txt')

ONE_TRANSACTION = str(FIXTURES / 'one_transaction_for_a_book_slot.txt')


def _book(tmp_path):
    gnc = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert result.exit_code == 0, result.output
    return gnc


def _put_in_the_book_slot(book_path, blob):
    """Write `blob` into the book's custom-metadata slot, verbatim."""
    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.NORMAL)
    try:
        assert set_book_string_option(
            repo.book, COMPANY_CUSTOM_SECTION, COMPANY_CUSTOM_SLOT, blob)
        repo.save()
    finally:
        repo.close()


def _stored_company_blob(book_path):
    """The book's custom-metadata slot, verbatim, as the book holds it."""
    from infrastructure.gnucash.kvp import get_book_string_option

    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        return get_book_string_option(
            repo.book, COMPANY_CUSTOM_SECTION, COMPANY_CUSTOM_SLOT) or ''
    finally:
        repo.close()


def _put_in_a_transaction_slot(book_path, blob):
    """Write `blob` into the one transaction's plaintext-metadata slot."""
    from gnucash import Query, Transaction

    repo = GnuCashRepository(str(book_path))
    repo.open(mode=SessionMode.NORMAL)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        for raw in query.run():
            transaction = Transaction(instance=raw)
            transaction.BeginEdit()
            assert _set_string_slot(transaction, PT_DATA_SLOT, blob)
            transaction.CommitEdit()
            query.destroy()
            repo.save()
            return
        query.destroy()
    finally:
        repo.close()
    raise AssertionError('no transaction in the book')


class TestABookSlotThatIsNotJson:
    def test_set_book_key_still_stores_its_key(self, tmp_path):
        """The blob is unreadable, so it holds no keys — not "no book"."""
        gnc = _book(tmp_path)
        _put_in_the_book_slot(gnc, 'this was not written as JSON')

        result = CliRunner().invoke(cli, [
            'set-book-key', str(gnc), '--key', 'schema_version', '--value', '7'])

        assert result.exit_code == 0, result.output
        read_back = CliRunner().invoke(cli, [
            'set-book-key', str(gnc), '--key', 'schema_version', '--value', '7'])
        assert 'nothing to change' in read_back.output, read_back.output

    def test_a_blob_that_is_json_but_not_an_object_reads_as_no_keys(self, tmp_path):
        """`[1, 2, 3]` parses and is not a mapping, which is a separate branch."""
        gnc = _book(tmp_path)
        _put_in_the_book_slot(gnc, '[1, 2, 3]')

        result = CliRunner().invoke(cli, [
            'set-book-key', str(gnc), '--key', 'province', '--value', 'Ontario'])

        assert result.exit_code == 0, result.output
        again = CliRunner().invoke(cli, [
            'set-book-key', str(gnc), '--key', 'province', '--value', 'Ontario'])
        assert 'nothing to change' in again.output, again.output


class TestReimportingTheSameCompanyBlock:
    def test_the_second_time_leaves_the_stored_blob_untouched(self, tmp_path):
        """The ordinary shape: a ledger re-imported over the book it built.

        The merge decides whether the blob changed, and answering "no" is the
        whole of what makes a re-import idempotent. Read back from the book
        rather than from an export: the exported *text* is the same either
        way, so comparing it would pass whether or not the slot was rewritten
        — which is what this test did before, while its name claimed
        otherwise.
        """
        gnc = _book(tmp_path)
        company = str(FIXTURES / 'company_custom_keys.txt')

        first = CliRunner().invoke(cli, ['import', str(gnc), company,
                                         '--include-business-objects'])
        assert first.exit_code == 0, first.output
        after_first = _stored_company_blob(gnc)
        assert 'British Columbia' in after_first

        second = CliRunner().invoke(cli, ['import', str(gnc), company,
                                          '--include-business-objects'])
        assert second.exit_code == 0, second.output

        assert _stored_company_blob(gnc) == after_first


class TestASplitSlotThatIsNotJson:
    def _book_with_a_transaction(self, tmp_path):
        gnc = _book(tmp_path)
        result = CliRunner().invoke(cli, ['import', str(gnc), ONE_TRANSACTION])
        assert result.exit_code == 0, result.output
        return gnc

    def test_exporting_reads_past_it_rather_than_failing(self, tmp_path):
        """One unreadable slot must not take the whole export down."""
        gnc = self._book_with_a_transaction(tmp_path)
        _put_in_a_transaction_slot(gnc, 'not json at all')

        out = tmp_path / 'out.txt'
        result = CliRunner().invoke(cli, ['export', str(gnc), str(out)])

        assert result.exit_code == 0, result.output
        assert 'Coffee' in out.read_text()

    def test_json_that_is_not_an_object_reads_as_no_metadata(self, tmp_path):
        gnc = self._book_with_a_transaction(tmp_path)
        _put_in_a_transaction_slot(gnc, '"a bare string"')

        out = tmp_path / 'out.txt'
        result = CliRunner().invoke(cli, ['export', str(gnc), str(out)])

        assert result.exit_code == 0, result.output
        assert 'Coffee' in out.read_text()

    def test_a_key_with_a_colon_is_dropped_on_the_way_out(self, tmp_path):
        """The format cannot express it, so it is dropped rather than written.

        Emitted, `tax:category: x` would read back as the key `tax` with the
        value `category: x` — a file this tool refuses on the way in.
        """
        gnc = self._book_with_a_transaction(tmp_path)
        _put_in_a_transaction_slot(gnc, '{"tax:category": "x", "keeper": "y"}')

        out = tmp_path / 'out.txt'
        result = CliRunner().invoke(cli, ['export', str(gnc), str(out)])

        assert result.exit_code == 0, result.output
        text = out.read_text()
        assert 'keeper: "y"' in text
        assert 'tax:category' not in text
