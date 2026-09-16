"""`close-books` on a book with nothing to close, and `--force --dry-run` over a year already closed.

A book holding no income or expense balance reads as closed already, since
every such balance is zero, so the run is refused without `--force`. With it
there is still nothing to move to equity, and the run says so rather than
reporting that it closed. A preview of re-closing a
year already closed shows what the re-close would do and changes nothing: the
closing entries it would delete first are still there afterwards.
"""

from click.testing import CliRunner

from cli.main import cli


def _book(tmp_path, fixture):
    book = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(book), fixture])
    assert result.exit_code == 0, result.output
    return str(book)


def test_a_book_with_no_income_or_expense_balance_has_nothing_to_close(tmp_path):
    book = _book(tmp_path, 'tests/fixtures/q019_accounts.txt')

    result = CliRunner().invoke(cli, [
        'close-books', book, '--closing-date', '2026-12-31', '--force'])

    assert result.exit_code == 0, result.output
    assert 'No Income/Expense balances found — nothing to close' in result.output, result.output


def test_a_preview_of_closing_a_closed_year_again_leaves_it_closed(tmp_path):
    book = _book(tmp_path, 'tests/fixtures/balance_sheet_book.txt')
    runner = CliRunner()
    closed = runner.invoke(cli, ['close-books', book, '--closing-date', '2025-12-31'])
    assert closed.exit_code == 0, closed.output

    preview = runner.invoke(cli, [
        'close-books', book, '--closing-date', '2025-12-31', '--force', '--dry-run'])

    assert preview.exit_code == 0, preview.output
    assert 'DRY RUN - Books would be closed as of 2025-12-31' in preview.output, preview.output
    assert 'Currencies closed: CAD' in preview.output, preview.output
    status = runner.invoke(cli, ['close-books', book, '--closing-date', '2025-12-31', '--status'])
    assert 'Books are CLOSED as of 2025-12-31' in status.output, status.output
