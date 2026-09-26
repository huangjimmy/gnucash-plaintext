"""A refused import warns of no orphaned payment.

Reading a file can unpost a paid invoice to rebuild it, and the import printed
"1 bank-side payment transaction is now orphaned in the book" at the unpost.
A refusal later in the same run saves nothing, so no payment was orphaned.

Measured on 5.10: INV-USD-001, paid by two splits of one transaction, read
back with one `PaymentSplit` stating a guid the book does not hold, printed the
warning and was then refused.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
BOOK = FIXTURES / 'fx_usd_invoice_cad_income.txt'
RATES = FIXTURES / 'fx_rates_usd_dated.yaml'
TWO_SPLITS = FIXTURES / 'money_arriving_as_two_receivable_splits.txt'
NAMES_TWO_SPLITS = FIXTURES / 'a_payment_stating_two_settling_splits.txt'
SECOND_SPLIT = '8192a3b4c5d6e7f80912233445566778'
UNKNOWN = 'feedfacefeedfacefeedfacefeedface'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output


def test_a_paymentsplit_the_book_lacks_is_refused_with_no_orphan_warned_of(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, BOOK, '--include-business-objects', '--fx-rates', RATES)
    _done('import', book, TWO_SPLITS)
    _done('import', book, NAMES_TWO_SPLITS, '--include-business-objects')
    edited = tmp_path / 'edited.txt'
    edited.write_text(NAMES_TWO_SPLITS.read_text().replace(SECOND_SPLIT, UNKNOWN))

    result = _run('import', book, edited, '--include-business-objects', '--fx-rates', RATES)

    assert result.exit_code != 0, result.output
    assert f"PaymentSplit '{UNKNOWN}' is not a split of tx" in result.output, result.output
    assert 'orphan' not in result.output.lower(), result.output
    again = _run('find-orphan-payments', book)
    assert 'No orphan bank-side payment transactions found.' in again.output, again.output


def test_with_a_memo_the_block_is_refused_the_same_way(tmp_path):
    """The block states a memo, so its memo is weighed before anything is
    applied, and the `PaymentSplit` the book lacks is passed over there. It is
    refused when the payment is applied, as without the memo. Measured on 5.10."""
    with_memo = NAMES_TWO_SPLITS.read_text().replace(
        '    account: "Assets:Bank:USD"\n',
        '    account: "Assets:Bank:USD"\n    memo: "Two lines"\n')
    assert 'memo: "Two lines"' in with_memo
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, BOOK, '--include-business-objects', '--fx-rates', RATES)
    _done('import', book, TWO_SPLITS)
    first = tmp_path / 'first.txt'
    first.write_text(with_memo)
    _done('import', book, first, '--include-business-objects', '--fx-rates', RATES)
    edited = tmp_path / 'edited.txt'
    edited.write_text(with_memo.replace(SECOND_SPLIT, UNKNOWN).replace('"Two lines"',
                                                                        '"Corrected"'))

    result = _run('import', book, edited, '--include-business-objects', '--fx-rates', RATES)

    assert result.exit_code != 0, result.output
    assert f"PaymentSplit '{UNKNOWN}' is not a split of tx" in result.output, result.output
    assert 'orphan' not in result.output.lower(), result.output
