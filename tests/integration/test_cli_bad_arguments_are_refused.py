"""Arguments the commands refuse, each named for what is wrong with it.

Every one of these refusals is a line the suite never reached (T-009). They
are what a user meets on the way to getting a command right: a key spelled
with a colon, a guid pasted without quotes, two flags that contradict each
other, a new account name that is empty or ends in a separator.
"""

from pathlib import Path

import pytest
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


def _a_file(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


class TestExport:
    def test_a_start_date_that_is_not_a_day_is_refused(self, tmp_path):
        """February has no 30th, so the date is refused rather than read as March."""
        output = tmp_path / 'ledger.txt'
        result = CliRunner().invoke(cli, [
            'export', _book(tmp_path), str(output), '--start-date', '2026-02-30'])

        assert result.exit_code != 0
        assert '2026-02-30 is not a date; give it as YYYY-MM-DD' in result.output
        assert not output.exists()


class TestExportPrices:
    def test_a_book_that_is_not_there_is_refused(self, tmp_path):
        result = CliRunner().invoke(cli, [
            'export-prices', str(tmp_path / 'missing.gnucash'), str(tmp_path / 'prices.txt')])

        assert result.exit_code != 0
        assert 'Input file does not exist' in result.output

    def test_a_file_in_a_directory_that_is_not_there_is_refused(self, tmp_path):
        result = CliRunner().invoke(cli, [
            'export-prices', _book(tmp_path), str(tmp_path / 'missing' / 'prices.txt')])

        assert result.exit_code != 0
        assert 'No such file or directory' in result.output
        assert 'Traceback' not in result.output


class TestAccountBalance:
    def test_a_rates_file_that_is_not_yaml_is_refused(self, tmp_path):
        rates = _a_file(tmp_path, 'rates.yaml', 'USD: [1.35\n')
        result = CliRunner().invoke(cli, [
            'account-balance', _book(tmp_path), '--fx-rates', rates])

        assert result.exit_code != 0
        assert 'is not valid YAML' in result.output
        assert 'Traceback' not in result.output

    def test_a_rate_too_fine_for_a_gnucash_price_is_refused(self, tmp_path):
        """GnuCash holds a price as a fraction of two 64-bit whole numbers, and 1/10**21 is not one."""
        rates = _a_file(tmp_path, 'rates.yaml', 'USD: 1.0e-21\n')
        result = CliRunner().invoke(cli, [
            'account-balance', _book(tmp_path), '--fx-rates', rates])

        assert result.exit_code != 0
        assert ('Failed to update pricedb: the USD rate 1/1000000000000000000000 cannot '
                'be written as a GnuCash price, which holds a rate as a fraction of two '
                '64-bit whole numbers') in result.output
        assert 'gint64' not in result.output


class TestPrintBill:
    def test_a_date_range_holding_no_bill_says_what_was_asked(self, tmp_path):
        result = CliRunner().invoke(cli, [
            'print-bill', _book(tmp_path), '--from', '2099-01-01',
            '-o', str(tmp_path / 'bills')])

        assert result.exit_code != 0
        assert "no bills matched the selection (from='2099-01-01')" in result.output


class TestUnpostInvoices:
    def test_a_guid_that_will_not_parse_is_named(self, tmp_path):
        result = CliRunner().invoke(cli, [
            'unpost-invoices', _book(tmp_path), '--by-guid', 'not-a-guid'])

        assert result.exit_code != 0
        assert 'Invalid GUID format' in result.output
        assert 'not-a-guid' in result.output


class TestDeleteTransactions:
    def test_a_guid_that_will_not_parse_is_named_and_nothing_is_deleted(self, tmp_path):
        """Asked where its undo block goes before anything is deleted, a guid
        that will not parse has no block, and the refusal says which it was."""
        book = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'delete-transactions', book, '--by-guid', 'not-a-guid'])

        assert result.exit_code != 0
        assert 'not-a-guid' in result.output, result.output
        assert 'Traceback' not in result.output, result.output


class TestUnlink:
    def test_a_rates_file_that_is_not_yaml_is_refused(self, tmp_path):
        rates = _a_file(tmp_path, 'rates.yaml', 'USD: [1.35\n')
        result = CliRunner().invoke(cli, [
            'unlink', _book(tmp_path), 'INV-1', '--to', 'Liabilities', '--fx-rates', rates])

        assert result.exit_code != 0
        assert 'Could not read --fx-rates file' in result.output
        assert 'is not valid YAML' in result.output

    @pytest.mark.parametrize('command', ['unlink', 'unapply-payment'])
    @pytest.mark.parametrize('to', ['', 'Root Account'])
    def test_the_root_is_not_an_account_a_payment_can_be_given(self, tmp_path, command, to):
        """The root holds the tree and no commodity, so no split can sit on it."""
        result = CliRunner().invoke(cli, [
            command, _book(tmp_path), 'INV-1', '--to', to])

        assert result.exit_code != 0
        assert f'--to account {to!r} not found in the book' in result.output, result.output
        assert result.exception is None or isinstance(result.exception, SystemExit), (
            result.exception)


class TestValidate:
    def test_a_file_that_is_not_a_book_is_refused(self, tmp_path):
        not_a_book = _a_file(tmp_path, 'ledger.gnucash', 'this is not a book\n')
        result = CliRunner().invoke(cli, ['validate', not_a_book])

        assert result.exit_code != 0
        assert 'That is not a GnuCash book this tool can read' in result.output
        assert 'Traceback' not in result.output
