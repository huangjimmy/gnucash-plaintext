"""What the two beancount commands accept, and what they refuse.

The round-trip is covered elsewhere, through the use cases. What is covered
here is the commands themselves: both spell their arguments two ways, both
refuse a missing or absent file before opening anything, and the import has
three separate exits — a dry run that validates and writes nothing, an import
that reports per-object failures and exits 1, and a file the parser rejects
outright, which is a different message with a different remedy.

Nothing reached either command before this. Sixteen tests exercised the use
cases directly, so the argument handling, every refusal and every summary line
was code the suite never ran (T-009).
"""

from pathlib import Path

from click.testing import CliRunner

from cli.export_beancount_cmd import export_beancount
from cli.import_beancount_cmd import import_beancount

# An ordinary beancount file: valid beancount, and not one this tool wrote.
# Its transaction carries none of the `gnucash-*` metadata an export adds, and
# the parser refuses it on the first of those it looks for — which is the check
# that makes "only beancount files exported from GnuCash can be imported" true.
NOT_FROM_GNUCASH = str(
    Path('tests/fixtures/beancount_not_from_gnucash.beancount'))


def _exported(tmp_path, book) -> Path:
    """The book as beancount, through the command under test."""
    out = tmp_path / 'ledger.beancount'
    result = CliRunner().invoke(export_beancount, [book, str(out)])
    assert result.exit_code == 0, result.output
    return out


class TestExportBeancountCommand:
    def test_positional_arguments_export_the_book(self, temp_gnucash_with_transactions,
                                                  tmp_path):
        out = tmp_path / 'out.beancount'
        result = CliRunner().invoke(
            export_beancount, [temp_gnucash_with_transactions, str(out)])

        assert result.exit_code == 0, result.output
        assert f'Exporting from: {temp_gnucash_with_transactions}' in result.output
        assert f'Exported to: {out}' in result.output
        assert 'Lines:' in result.output
        assert out.exists()
        assert 'open Assets:Bank' in out.read_text()

    def test_flags_name_the_same_two_files(self, temp_gnucash_with_transactions,
                                           tmp_path):
        """`-i`/`-o` are the documented alternative, and take precedence."""
        out = tmp_path / 'flagged.beancount'
        result = CliRunner().invoke(export_beancount, [
            '-i', temp_gnucash_with_transactions, '-o', str(out)])

        assert result.exit_code == 0, result.output
        assert out.exists()

    def test_a_date_range_and_an_account_filter_are_echoed(
            self, temp_gnucash_with_transactions, tmp_path):
        """What was filtered is stated, or a short export reads like a whole one."""
        out = tmp_path / 'filtered.beancount'
        result = CliRunner().invoke(export_beancount, [
            temp_gnucash_with_transactions, str(out),
            '--date-from', '2024-01-01', '--date-to', '2024-01-31',
            '--account', 'Assets:Bank'])

        assert result.exit_code == 0, result.output
        assert 'Date range: 2024-01-01 to 2024-01-31' in result.output
        assert 'Account filter: Assets:Bank' in result.output

    def test_a_date_range_leaves_out_what_falls_outside_it(
            self, temp_gnucash_with_transactions, tmp_path):
        """A range that excludes something, which the echo alone does not prove.

        The book holds three transactions — 15th, 20th and 25th of January.
        A range covering all three exercises the filter without ever taking
        its false side, so the filter and no filter at all look identical.
        """
        out = tmp_path / 'narrow.beancount'
        result = CliRunner().invoke(export_beancount, [
            temp_gnucash_with_transactions, str(out),
            '--date-from', '2024-01-18', '--date-to', '2024-01-22'])

        assert result.exit_code == 0, result.output
        # Read off the descriptions, not the dates: beancount wants every
        # account and commodity declared before it is used, so the export
        # stamps those declarations with a date of its own and the excluded
        # transaction's date goes on appearing in the file without it.
        text = out.read_text()
        assert '"Restaurant"' in text
        assert '"Grocery shopping"' not in text
        assert '"More groceries"' not in text

    def test_an_account_filter_leaves_out_transactions_that_never_touch_it(
            self, temp_gnucash_with_transactions, tmp_path):
        """Every transaction touches the bank, so only a narrower name shows this."""
        out = tmp_path / 'dining.beancount'
        result = CliRunner().invoke(export_beancount, [
            temp_gnucash_with_transactions, str(out),
            '--account', 'Expenses:Dining'])

        assert result.exit_code == 0, result.output
        text = out.read_text()
        assert '"Restaurant"' in text
        assert '"Grocery shopping"' not in text
        assert '"More groceries"' not in text

    def test_one_end_of_a_date_range_names_the_other_end_for_what_it_is(
            self, temp_gnucash_with_transactions, tmp_path):
        out = tmp_path / 'open_ended.beancount'
        result = CliRunner().invoke(export_beancount, [
            temp_gnucash_with_transactions, str(out), '--date-from', '2024-01-20'])

        assert result.exit_code == 0, result.output
        assert 'Date range: 2024-01-20 to end' in result.output

    def test_no_input_file_says_which_argument_is_missing(self):
        result = CliRunner().invoke(export_beancount, [])

        assert result.exit_code != 0
        assert 'Missing input file' in result.output

    def test_no_output_file_says_which_argument_is_missing(
            self, temp_gnucash_with_transactions):
        result = CliRunner().invoke(export_beancount, [temp_gnucash_with_transactions])

        assert result.exit_code != 0
        assert 'Missing output file' in result.output

    def test_an_input_file_that_is_not_there_is_named(self, tmp_path):
        """Checked before the session is opened, so the path is what is reported."""
        missing = tmp_path / 'nowhere.gnucash'
        result = CliRunner().invoke(
            export_beancount, [str(missing), str(tmp_path / 'out.beancount')])

        assert result.exit_code != 0
        assert 'Input file does not exist' in result.output
        assert str(missing) in result.output

    def test_a_file_gnucash_cannot_open_is_reported_rather_than_traced(self, tmp_path):
        """A session that will not open is an error message, not a traceback."""
        not_a_book = tmp_path / 'notes.gnucash'
        not_a_book.write_text('this is not a gnucash file\n')
        result = CliRunner().invoke(
            export_beancount, [str(not_a_book), str(tmp_path / 'out.beancount')])

        assert result.exit_code != 0
        assert 'Error' in result.output
        assert 'Traceback' not in result.output


class TestImportBeancountCommand:
    def test_positional_arguments_rebuild_the_book(self, temp_gnucash_with_transactions,
                                                   tmp_path):
        source = _exported(tmp_path, temp_gnucash_with_transactions)
        rebuilt = tmp_path / 'rebuilt.gnucash'
        result = CliRunner().invoke(import_beancount, [str(rebuilt), str(source)])

        assert result.exit_code == 0, result.output
        assert 'Import Summary:' in result.output
        assert 'Commodities:' in result.output
        assert 'Accounts:' in result.output
        assert 'Transactions: 3' in result.output
        assert f'Import successful - saved to {rebuilt}' in result.output
        assert rebuilt.exists()

    def test_flags_name_the_same_two_files(self, temp_gnucash_with_transactions,
                                           tmp_path):
        source = _exported(tmp_path, temp_gnucash_with_transactions)
        rebuilt = tmp_path / 'flagged.gnucash'
        result = CliRunner().invoke(
            import_beancount, ['-o', str(rebuilt), '-i', str(source)])

        assert result.exit_code == 0, result.output
        assert rebuilt.exists()

    def test_a_dry_run_counts_what_it_found_and_writes_nothing(
            self, temp_gnucash_with_transactions, tmp_path):
        source = _exported(tmp_path, temp_gnucash_with_transactions)
        not_written = tmp_path / 'not_written.gnucash'
        result = CliRunner().invoke(
            import_beancount, [str(not_written), str(source), '--dry-run'])

        assert result.exit_code == 0, result.output
        assert '[DRY RUN]' in result.output
        assert 'Validation Summary:' in result.output
        assert 'Transactions: 3' in result.output
        assert 'valid for GnuCash import' in result.output
        assert not not_written.exists(), 'a dry run created the file'

    def test_a_dry_run_over_an_existing_file_is_allowed(
            self, temp_gnucash_with_transactions, tmp_path):
        """Nothing is written, so the guard on an existing file does not apply."""
        source = _exported(tmp_path, temp_gnucash_with_transactions)
        result = CliRunner().invoke(import_beancount, [
            temp_gnucash_with_transactions, str(source), '--dry-run'])

        assert result.exit_code == 0, result.output
        assert 'Validation Summary:' in result.output

    def test_no_output_file_says_which_argument_is_missing(self):
        result = CliRunner().invoke(import_beancount, [])

        assert result.exit_code != 0
        assert 'Missing output GnuCash file' in result.output

    def test_no_input_file_says_which_argument_is_missing(self, tmp_path):
        result = CliRunner().invoke(import_beancount, [str(tmp_path / 'new.gnucash')])

        assert result.exit_code != 0
        assert 'Missing input beancount file' in result.output

    def test_a_beancount_file_that_is_not_there_is_named(self, tmp_path):
        missing = tmp_path / 'nowhere.beancount'
        result = CliRunner().invoke(
            import_beancount, [str(tmp_path / 'new.gnucash'), str(missing)])

        assert result.exit_code != 0
        assert 'Beancount file does not exist' in result.output
        assert str(missing) in result.output

    def test_an_existing_gnucash_file_is_not_written_over(
            self, temp_gnucash_with_transactions, tmp_path):
        """The command builds a new book, so an existing path is a mistake."""
        source = _exported(tmp_path, temp_gnucash_with_transactions)
        before = Path(temp_gnucash_with_transactions).read_bytes()
        result = CliRunner().invoke(
            import_beancount, [temp_gnucash_with_transactions, str(source)])

        assert result.exit_code != 0
        assert 'already exists' in result.output
        assert Path(temp_gnucash_with_transactions).read_bytes() == before

    def test_a_dry_run_over_a_file_the_parser_rejects_says_what_is_wrong(self, tmp_path):
        """The validation path refuses, and says the metadata is what is missing."""
        result = CliRunner().invoke(
            import_beancount,
            [str(tmp_path / 'new.gnucash'), NOT_FROM_GNUCASH, '--dry-run'])

        assert result.exit_code != 0
        assert 'Validation failed' in result.output
        assert 'gnucash-' in result.output
        assert 'Traceback' not in result.output

    def test_a_refused_dry_run_leaves_an_existing_book_alone(
            self, temp_gnucash_with_transactions):
        """A dry run makes no book, so it must take none away either.

        A failed run now removes the book it created, so that a retry is not
        blocked by a file the reader never made. A dry run creates nothing —
        the path it is given may be somebody's ledger, and the refusal must
        not go looking for it. Pointed at a book that does not exist, the
        removal is indistinguishable from a no-op; this points it at one that
        does.
        """
        before = Path(temp_gnucash_with_transactions).read_bytes()

        result = CliRunner().invoke(
            import_beancount,
            [temp_gnucash_with_transactions, NOT_FROM_GNUCASH, '--dry-run'])

        assert result.exit_code != 0, result.output
        assert Path(temp_gnucash_with_transactions).read_bytes() == before, (
            'a refused dry run touched a book it did not create')

    def test_a_book_that_cannot_be_created_is_reported_rather_than_traced(
            self, temp_gnucash_with_transactions, tmp_path):
        """The other failure: the file is fine and the destination is not."""
        source = _exported(tmp_path, temp_gnucash_with_transactions)
        nowhere = tmp_path / 'no' / 'such' / 'directory' / 'new.gnucash'
        result = CliRunner().invoke(import_beancount, [str(nowhere), str(source)])

        assert result.exit_code != 0
        assert 'Error' in result.output
        assert 'Traceback' not in result.output

    def test_an_import_the_parser_rejects_reports_it_and_exits_1(self, tmp_path):
        """Not the validation message: the parse error arrives as a result error.

        `import_from_file` catches the parser's refusal and returns it in the
        result, so the same file the dry run reports as a validation failure
        comes back here as an ordinary import error, counted with the rest and
        printed under `Errors:`. Both exits are real and neither is the other's
        code path — the dry run calls the parser itself, and only there does
        the refusal reach the command as an exception.
        """
        rebuilt = tmp_path / 'rebuilt.gnucash'
        result = CliRunner().invoke(
            import_beancount, [str(rebuilt), NOT_FROM_GNUCASH])

        assert result.exit_code == 1, result.output
        assert 'Errors:' in result.output
        assert 'missing required gnucash-guid metadata' in result.output
        assert 'Import completed with errors' in result.output
        # Nothing landed, and the summary says so rather than reporting the
        # objects it got through before the file was refused.
        assert 'Transactions: 0' in result.output
