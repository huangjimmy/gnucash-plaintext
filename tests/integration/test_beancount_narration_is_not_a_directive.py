"""A description is text, not a directive, whatever words it contains.

The parser decided what each line was by looking for `' commodity '` and
`' open '` anywhere in it — a substring test over the whole line, payee and
narration included, and both were asked before the anchored test for a
transaction. So an ordinary ledger entry described as "Bought a commodity for
resale" was read as a commodity declaration, failed to parse as one, and took
the whole file down with it: `import-beancount` refused every transaction in
the ledger over the wording of one description.

Found while covering `import_beancount`'s per-object error handling (T-009) —
a fixture written to fail in one place failed in another, for a reason that
had nothing to do with the object it was testing.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
LEDGER = str(FIXTURES / 'beancount_narration_naming_a_directive.beancount')


class TestWordsThatNameADirective:
    def test_a_narration_saying_commodity_still_imports(self, tmp_path):
        book = tmp_path / 'rebuilt.gnucash'
        result = CliRunner().invoke(cli, ['import-beancount', str(book), LEDGER])

        assert result.exit_code == 0, result.output
        assert 'Transactions: 2' in result.output

    def test_both_descriptions_survive_into_the_book(self, tmp_path):
        book = tmp_path / 'rebuilt.gnucash'
        assert CliRunner().invoke(
            cli, ['import-beancount', str(book), LEDGER]).exit_code == 0

        out = tmp_path / 'check.txt'
        exported = CliRunner().invoke(cli, ['export', str(book), str(out)])
        assert exported.exit_code == 0, exported.output
        text = out.read_text()
        assert 'Bought a commodity for resale' in text
        assert 'Left the open box at reception' in text

    def test_a_dry_run_calls_the_file_valid(self, tmp_path):
        """The validation the command offers has to agree with the import."""
        result = CliRunner().invoke(cli, [
            'import-beancount', str(tmp_path / 'unused.gnucash'), LEDGER,
            '--dry-run'])

        assert result.exit_code == 0, result.output
        assert 'Transactions: 2' in result.output
        assert 'Commodities:  1' in result.output
