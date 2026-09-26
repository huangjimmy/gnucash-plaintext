"""A `prepayment:` beside a split the block states, with no `amount:`, is weighed when the payment is applied.

The check made before an invoice is compared weighs a block's residue only where
the block states an `amount:`. A block that states its transaction need not state
one, so its residue is weighed where the settlement is placed, against the
receivable splits of the wire the block does not state. Measured on 5.10: 60.00
declared against 50.00 left over is refused there, and the run imports nothing.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
WIRE = 'tests/fixtures/a_wire_settling_c004_with_a_residue_stated_by_split.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _read_into_a_new_book(tmp_path, ledger):
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, ACCOUNTS).exit_code == 0
    return book, _run('import', book, ledger, '--include-business-objects')


def test_a_residue_that_is_not_what_is_left_over_is_refused(tmp_path):
    book, result = _read_into_a_new_book(tmp_path, WIRE)

    assert result.exit_code != 0, result.output
    assert ("declared `prepayment: 60.00` does not match the residual AR/AP splits "
            "on tx 'd4d4d4d4d4d4d4d4d4d4d4d4d4d4d4d4' (sum of loose siblings = 50.00)"
            in result.output), result.output
    assert 'No pre-payment credits found.' in _run('find-prepayments', book).output


def test_the_residue_that_is_left_over_is_the_customers_credit(tmp_path):
    text = Path(WIRE).read_text()
    assert '\t\tprepayment: 60.00\n' in text, text
    ledger = tmp_path / 'right.txt'
    ledger.write_text(text.replace('\t\tprepayment: 60.00\n', '\t\tprepayment: 50.00\n'))

    book, result = _read_into_a_new_book(tmp_path, ledger)

    assert result.exit_code == 0, result.output
    listed = _run('find-prepayments', book).output
    assert 'customer C004 (Delta Co)  CAD 50.00' in listed, listed
