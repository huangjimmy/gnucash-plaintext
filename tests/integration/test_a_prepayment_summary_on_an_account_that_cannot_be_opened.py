"""An `open_prepayment:` summary under an account that could not be opened.

The account is refused for its type, and that refusal is the error the run
reports. The summary under it is still compared with the book, which holds no
such account and so no credit on it, and the difference is said as the warning
any hand-edited summary gets, beside the error rather than instead of it.
"""

from click.testing import CliRunner

from cli.main import cli

FIXTURE = 'tests/fixtures/a_prepayment_summary_on_an_account_that_cannot_be_opened.txt'


def test_the_account_is_refused_and_the_summary_is_warned_about(tmp_path):
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, [
        'import', '--new', str(book), FIXTURE, '--include-business-objects'])

    assert result.exit_code != 0, result.output
    assert "Unknown account type 'NotAType' for 'Assets:Owed'" in result.output, result.output
    assert ("warning: open_prepayment on Assets:Owed for customer 'C1' declares 5 "
            "but the book holds 0") in result.output, result.output
    assert 'Traceback' not in result.output
