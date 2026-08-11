"""What `import` refuses, and what it warns about, before it reads a book.

These are the checks a user meets when a path is wrong or two flags disagree,
and none of them had run (T-009): the suite always passes `import` a file that
exists, a rates file that parses and a `--output-new` directory that is there.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = str(Path('tests/fixtures/q019_accounts.txt'))


def _book(tmp_path):
    gnc = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(gnc), ACCOUNTS])
    assert result.exit_code == 0, result.output
    return str(gnc)


class TestPathsThatAreNotThere:
    def test_a_plaintext_file_that_is_missing_is_named(self, tmp_path):
        missing = tmp_path / 'nowhere.txt'
        result = CliRunner().invoke(
            cli, ['import', _book(tmp_path), str(missing)])

        assert result.exit_code != 0
        assert 'Plaintext file does not exist' in result.output
        assert str(missing) in result.output

    def test_an_output_new_directory_that_is_missing_is_named(self, tmp_path):
        """The file is written at the end, so the directory is checked first."""
        out = tmp_path / 'no' / 'such' / 'dir' / 'new.txt'
        result = CliRunner().invoke(cli, [
            'import', _book(tmp_path), ACCOUNTS, '--output-new', str(out)])

        assert result.exit_code != 0
        assert '--output-new directory does not exist' in result.output

    def test_a_rates_file_that_will_not_read_is_named(self, tmp_path):
        rates = tmp_path / 'rates.yaml'
        rates.write_text('this: [is not: yaml\n')
        result = CliRunner().invoke(cli, [
            'import', _book(tmp_path), ACCOUNTS, '--fx-rates', str(rates)])

        assert result.exit_code != 0
        assert 'Could not read --fx-rates file' in result.output


class TestFlagsThatDisagree:
    def test_output_new_in_a_dry_run_is_warned_about(self, tmp_path):
        """Nothing is saved, so nothing would be written to it."""
        out = tmp_path / 'new.txt'
        result = CliRunner().invoke(cli, [
            'import', _book(tmp_path), ACCOUNTS,
            '--dry-run', '--output-new', str(out)])

        assert result.exit_code == 0, result.output
        assert '--output-new is ignored in dry-run mode' in result.output
        assert not out.exists()
