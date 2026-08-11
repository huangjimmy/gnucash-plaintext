"""Every command turns a bad argument or an unreadable book into a message.

Each of these wraps its work in a handler whose whole job is to keep a
traceback off the user's screen, and none of them had ever run (T-009): the
suite drove every command over books that open and dates that parse.

Both shapes are ordinary. A date typed the European way round is the first
thing a new user does, and a file that is not a GnuCash book is what happens
when the argument order is wrong or a path points at last week's export.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = str(Path('tests/fixtures/q019_accounts.txt'))


def _not_a_book(tmp_path):
    path = tmp_path / 'notes.gnucash'
    path.write_text('this is not a gnucash book\n')
    return str(path)


def _book(tmp_path):
    gnc = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert result.exit_code == 0, result.output
    return str(gnc)


class TestADateThatIsNotADate:
    def test_close_books_says_the_format(self, tmp_path):
        result = CliRunner().invoke(cli, [
            'close-books', _book(tmp_path), '--closing-date', '31/12/2026'])

        assert result.exit_code != 0
        assert 'YYYY-MM-DD' in result.output
        assert '31/12/2026' in result.output
        assert 'Traceback' not in result.output


class TestABookThatWillNotOpen:
    def test_export_reports_it(self, tmp_path):
        result = CliRunner().invoke(cli, [
            'export', _not_a_book(tmp_path), str(tmp_path / 'out.txt')])

        assert result.exit_code != 0
        assert 'Traceback' not in result.output
        assert 'Error' in result.output

    def test_export_accounts_reports_it(self, tmp_path):
        result = CliRunner().invoke(cli, [
            'export-accounts', _not_a_book(tmp_path), str(tmp_path / 'out.txt')])

        assert result.exit_code != 0
        assert 'Traceback' not in result.output
        assert 'Error' in result.output

    def test_export_transaction_reports_it(self, tmp_path):
        result = CliRunner().invoke(cli, [
            'export-transaction', _not_a_book(tmp_path),
            '--guid', '0123456789abcdef0123456789abcdef'])

        assert result.exit_code != 0
        assert 'Traceback' not in result.output
        assert 'Error' in result.output


class TestATransactionThatIsNotThere:
    def test_export_transaction_says_so(self, tmp_path):
        """A guid nothing matches is the other way this command fails."""
        result = CliRunner().invoke(cli, [
            'export-transaction', _book(tmp_path),
            '--guid', '0123456789abcdef0123456789abcdef'])

        assert result.exit_code != 0
        # The guid is echoed, so a reader can see which one was looked for.
        # Asserting only that no traceback appears would pass on a crash:
        # an unhandled exception goes to `result.exception` and leaves the
        # output empty, and `'Traceback' not in ''` is true.
        assert 'No transaction found with GUID' in result.output
        assert '0123456789abcdef0123456789abcdef' in result.output
