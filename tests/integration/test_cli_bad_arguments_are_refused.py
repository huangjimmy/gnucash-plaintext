"""Arguments the commands refuse, each named for what is wrong with it.

Every one of these refusals is a line the suite never reached (T-009). They
are what a user meets on the way to getting a command right: a key spelled
with a colon, a guid pasted without quotes, two flags that contradict each
other, a new account name that is empty or ends in a separator.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = str(Path('tests/fixtures/q019_accounts.txt'))


def _book(tmp_path, name='book.gnucash'):
    gnc = tmp_path / name
    result = CliRunner().invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert result.exit_code == 0, result.output
    return str(gnc)


class TestSetBookKey:
    def test_a_key_with_a_colon_is_refused(self, tmp_path):
        """A colon separates key from value, so a key cannot contain one."""
        result = CliRunner().invoke(cli, [
            'set-book-key', _book(tmp_path), '--key', 'tax:year', '--value', '2026'])

        assert result.exit_code != 0
        assert 'invalid book key' in result.output
        assert 'Traceback' not in result.output

    def test_the_book_is_required(self, tmp_path):
        """Outside a batch there is no open book to write to."""
        result = CliRunner().invoke(cli, [
            'set-book-key', '--key', 'schema_version', '--value', '1'])

        assert result.exit_code != 0
        assert 'missing book' in result.output


class TestUnapplyPayment:
    def test_txn_and_all_are_mutually_exclusive(self, tmp_path):
        result = CliRunner().invoke(cli, [
            'unapply-payment', _book(tmp_path), 'INV-1', '--to', 'Liabilities',
            '--txn', '0123456789abcdef0123456789abcdef', '--all'])

        assert result.exit_code != 0
        assert 'mutually exclusive' in result.output

    def test_a_guid_that_will_not_parse_is_named(self, tmp_path):
        result = CliRunner().invoke(cli, [
            'unapply-payment', _book(tmp_path), 'INV-1', '--to', 'Liabilities',
            '--txn', 'not-a-guid'])

        assert result.exit_code != 0
        # The value is quoted back, which is the whole of what makes this
        # message useful when several `--txn` flags were given.
        assert 'Invalid GUID format' in result.output
        assert 'not-a-guid' in result.output


class TestRenameAccount:
    """The account is named by guid and the new name by `--to`."""

    def _bank_guid(self, book):
        from gnucash import Query

        from infrastructure.gnucash.utils import find_account
        from repositories.gnucash_repository import GnuCashRepository, SessionMode

        repo = GnuCashRepository(book)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            account = find_account(repo.book.get_root_account(), 'Assets:Bank')
            assert account is not None
            return account.GetGUID().to_string()
        finally:
            repo.close()

    def test_an_empty_new_name_is_refused(self, tmp_path):
        book = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'rename-account', book, '--guid', self._bank_guid(book), '--to', '   '])

        assert result.exit_code != 0
        assert 'invalid --to value' in result.output
        assert 'cannot be empty or start/end with ":"' in result.output
        assert 'Traceback' not in result.output

    def test_a_name_ending_in_a_separator_is_refused(self, tmp_path):
        book = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'rename-account', book, '--guid', self._bank_guid(book),
            '--to', 'Chequing:'])

        assert result.exit_code != 0
        assert 'invalid --to value' in result.output
        assert 'cannot be empty or start/end with ":"' in result.output

    def test_the_book_is_required(self, tmp_path):
        book = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'rename-account', '--guid', self._bank_guid(book), '--to', 'Chequing'])

        assert result.exit_code != 0
        assert 'missing book' in result.output
