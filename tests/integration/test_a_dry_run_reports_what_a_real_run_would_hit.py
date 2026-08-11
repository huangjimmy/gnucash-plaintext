"""`--dry-run` exits on the errors it found, the same as the run it stands in for.

A dry run exists to answer "would this file import", and the exit code is how a
script asks. Reporting `Errors: 1` and exiting 0 answered yes to a file that
imports partly at best — so `import --dry-run && import` ran the real import
over exactly the file the dry run had objected to.

Pinned as its own behaviour rather than left to follow from the exit-code rule,
because a dry run writes nothing and it would be reasonable to read "nothing
went wrong" from that.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = 'tests/fixtures/import_new_invalid_account_type.txt'


@pytest.fixture
def book(tmp_path):
    gnc = tmp_path / 'book.gnucash'
    assert CliRunner().invoke(cli, [
        'import', '--new', str(gnc),
        'tests/fixtures/payment_roundtrip_accounts.txt']).exit_code == 0
    return gnc


class TestAFileWithPerObjectErrors:
    def test_the_dry_run_does_not_report_success(self, book):
        result = CliRunner().invoke(cli, ['import', str(book), LEDGER,
                                          '--dry-run'])

        assert result.exit_code != 0, result.output
        assert 'Unknown account type' in result.output, result.output

    def test_it_still_writes_nothing(self, book):
        """Refusing and saving are separate: a dry run reports and stops."""
        before = book.read_bytes()

        CliRunner().invoke(cli, ['import', str(book), LEDGER, '--dry-run'])

        assert book.read_bytes() == before


class TestAFileThatWouldPartlyLand:
    """Nine transactions would import and one would not.

    "Nothing to import" and "nothing could be imported" are different answers,
    and the non-dry arm was written to keep them apart. The dry-run arm said
    `nothing would be imported` for any run with an error at all — four lines
    under a count saying nine, and it is the sentence a reader consults
    *before* committing to the real run, which saves those nine.
    """

    PARTIAL = 'tests/fixtures/nine_good_transactions_and_one_bad.txt'

    @pytest.fixture
    def result(self, book):
        return CliRunner().invoke(cli, ['import', str(book), self.PARTIAL,
                                        '--dry-run'])

    def test_it_does_not_say_nothing_would_be_imported(self, result):
        assert 'nothing would be imported' not in result.output, result.output

    def test_it_says_what_would_land_and_what_would_not(self, result):
        assert 'Transactions: 9' in result.output, result.output
        assert 'Errors:       1' in result.output, result.output

    def test_it_still_reports_failure(self, result):
        assert result.exit_code != 0, result.output


class TestAFileWithNothingWrongWithIt:
    def test_the_dry_run_reports_success(self, book):
        """The other half: a clean file's dry run still exits 0."""
        result = CliRunner().invoke(cli, [
            'import', str(book), 'tests/fixtures/a_plain_transaction_to_edit.txt',
            '--dry-run'])

        assert result.exit_code == 0, result.output
