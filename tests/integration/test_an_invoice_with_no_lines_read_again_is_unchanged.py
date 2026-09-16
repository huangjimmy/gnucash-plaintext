"""An invoice with no lines, read again, is `unchanged`.

A block giving no line is refused where the book holds lines for that invoice,
because rebuilding from it would destroy them. Where the book holds none either
there is nothing to destroy, and the invoice is what the file says.
"""

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
EMPTY = 'tests/fixtures/an_invoice_with_no_lines.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def test_it_is_unchanged(tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, ACCOUNTS).exit_code == 0
    made = _run('import', book, EMPTY, '--include-business-objects')
    assert made.exit_code == 0, made.output
    assert 'invoice "INV-EMPTY": created' in made.output, made.output

    again = _run('import', book, EMPTY, '--include-business-objects')

    assert again.exit_code == 0, again.output
    assert 'invoice "INV-EMPTY": unchanged' in again.output, again.output
