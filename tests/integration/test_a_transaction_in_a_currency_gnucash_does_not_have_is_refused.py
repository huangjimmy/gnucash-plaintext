"""A transaction quoted in a currency GnuCash does not have is refused.

`currency.mnemonic:` gives the currency a transaction is quoted in. Where
GnuCash has no such currency there is nothing to quote it in, so the import
refuses the transaction, whether the file creates it or restates one the book
already holds.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
IN_CAD = 'tests/fixtures/a_bank_purchase_with_its_guid.txt'
IN_XYZ = 'tests/fixtures/the_same_bank_purchase_in_a_currency_gnucash_does_not_have.txt'


def _book(tmp_path):
    book = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(book), ACCOUNTS])
    assert made.exit_code == 0, made.output
    return book


def _exported(book, tmp_path):
    out = tmp_path / 'out.txt'
    assert CliRunner().invoke(cli, ['export', str(book), str(out)]).exit_code == 0
    return out.read_text()


def test_creating_it_is_refused(tmp_path):
    book = _book(tmp_path)

    result = CliRunner().invoke(cli, ['import', str(book), IN_XYZ])

    assert 'Cannot find commodity (CURRENCY, XYZ)' in result.output, result.output
    assert 'Paper' not in _exported(book, tmp_path)


def test_restating_it_is_refused_and_the_book_keeps_its_quote(tmp_path):
    book = _book(tmp_path)
    created = CliRunner().invoke(cli, ['import', str(book), IN_CAD])
    assert created.exit_code == 0, created.output

    result = CliRunner().invoke(cli, ['import', str(book), IN_XYZ,
                                      '--strategy', 'update'])

    assert 'Cannot find commodity (CURRENCY, XYZ)' in result.output, result.output
    # Still in the book, and still quoted in CAD: the export writes no
    # `currency.mnemonic:` for the book's own currency, so XYZ appearing
    # anywhere would be the refused line having reached the book.
    exported = _exported(book, tmp_path)
    assert '"Paper"' in exported, exported
    assert 'XYZ' not in exported, exported
