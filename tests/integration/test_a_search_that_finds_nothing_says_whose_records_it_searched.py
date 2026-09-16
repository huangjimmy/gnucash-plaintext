"""A search that finds nothing says whose records it searched.

`find-orphan-payments` and `find-prepayments` both take `--customer` and
`--vendor`, and an empty answer repeats the one given, so "none for vendor
V001" is not read as "none in the book".
"""

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert result.exit_code == 0, result.output
    return str(book)


def test_no_orphan_payment_for_a_vendor(tmp_path):
    result = CliRunner().invoke(cli, [
        'find-orphan-payments', _book(tmp_path), '--vendor', 'V001'])

    assert result.exit_code == 0, result.output
    assert 'No orphan bank-side payment transactions found for vendor V001.' in result.output


def test_no_credit_for_a_customer(tmp_path):
    result = CliRunner().invoke(cli, [
        'find-prepayments', _book(tmp_path), '--customer', 'C001'])

    assert result.exit_code == 0, result.output
    assert 'No pre-payment credits found for customer C001.' in result.output


def test_no_credit_for_a_vendor(tmp_path):
    result = CliRunner().invoke(cli, [
        'find-prepayments', _book(tmp_path), '--vendor', 'V001'])

    assert result.exit_code == 0, result.output
    assert 'No pre-payment credits found for vendor V001.' in result.output
