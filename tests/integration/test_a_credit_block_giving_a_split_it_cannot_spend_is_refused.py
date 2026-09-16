"""A credit block that gives a split the book cannot spend as that credit is refused.

`from_credit: true` spends a split the book already holds, given by
`txn_guid:` and `txn_split_guid:`. The book here holds one: 50.00 left over
from overpaying INV-001. Each test gives the block something else, and the
import refuses the invoice and says what is wrong with what it was given.
"""

from click.testing import CliRunner

from tests.integration.test_credit_payment_block_is_checked import (
    _book_with_a_credit,
    _credit_split,
    _import_fixture,
)

VALID_BLOCK = 'credit_payment_smaller_than_the_invoice.txt'
NO_SUCH_GUID = '0123456789abcdef0123456789abcdef'


def test_a_transaction_the_book_does_not_hold(tmp_path):
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    _txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path, VALID_BLOCK, NO_SUCH_GUID, split_guid)

    assert result.exit_code != 0, result.output
    assert f"txn_guid '{NO_SUCH_GUID}' not found in book" in result.output, result.output


def test_a_split_that_is_not_in_the_transaction(tmp_path):
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, _split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path, VALID_BLOCK, txn_guid, NO_SUCH_GUID)

    assert result.exit_code != 0, result.output
    assert f"txn_split_guid '{NO_SUCH_GUID}' not found on tx" in result.output, \
        result.output


def test_the_bank_split_of_the_credits_transaction(tmp_path):
    """The money arrived in the bank, and the credit is the receivable's split."""
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, bank_split = _credit_split(book, account_name='Assets.Bank',
                                         amount='15000/100')

    result = _import_fixture(runner, book, tmp_path, VALID_BLOCK, txn_guid, bank_split)

    assert result.exit_code != 0, result.output
    assert "the credit split lives on 'Assets:Bank'" in result.output, result.output


def test_a_receivable_split_that_is_a_debit(tmp_path):
    """INV-001's own posting put 100.00 on the receivable. A customer's credit
    is a credit of the receivable, and that split is a debit."""
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, posting_split = _credit_split(book, amount='10000/100')

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_dated_like_the_posting.txt',
                             txn_guid, posting_split)

    assert result.exit_code != 0, result.output
    assert ('carries 100.00, which is not a credit on Assets:Accounts Receivable'
            in result.output), result.output


def test_an_amount_that_is_not_a_number(tmp_path):
    runner = CliRunner()
    book = _book_with_a_credit(runner, tmp_path)
    txn_guid, split_guid = _credit_split(book)

    result = _import_fixture(runner, book, tmp_path,
                             'credit_payment_whose_amount_is_not_a_number.txt',
                             txn_guid, split_guid)

    assert result.exit_code != 0, result.output
    assert "payment amount must be a number, got 'thirty'" in result.output, \
        result.output
