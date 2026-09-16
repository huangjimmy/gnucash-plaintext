"""A corrected payment memo reaches the bank split on a bill posted to a plain liability.

A payment's memo is written on the split that settles the record, and the bank
split follows it where it still reads the same. Measured on 5.10, with a wire
worded "Wire out" on both sides and its block's memo corrected to "Paid by
wire": on a bill posted to `Liabilities:Accounts Payable USD` both splits took
the correction, and on the same bill posted to `Liabilities:Other Payables`, a
plain `type: Liability` account, only the settlement did. The bank split kept
"Wire out", so the one memo `ApplyPayment` writes on both sides was broken in
half. What settles a bill is the split in its lot, whatever type its account
is.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
RATES = FIXTURES / 'fx_rates_usd_dated.yaml'
BILL_BOOK = FIXTURES / 'fx_usd_bill_cad_expense.txt'
PAID = FIXTURES / 'a_bill_on_a_plain_liability_paid_by_a_wire_on_that_liability.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _done(*args):
    result = _run(*args)
    assert result.exit_code == 0, result.output
    return result


def _memo_of(text, guid):
    found = re.search(r'guid: "' + guid + r'"\n\t\tmemo: ?"([^"]*)"', text)
    assert found, text
    return found.group(1)


def test_the_bank_split_takes_the_corrected_memo_with_the_settlement(tmp_path):
    book = tmp_path / 'book.gnucash'
    _done('import', '--new', book, BILL_BOOK, '--include-business-objects', '--fx-rates', RATES)
    _done('import', book, PAID, '--include-business-objects', '--fx-rates', RATES)
    text = PAID.read_text()
    block_memo = '\t\tmemo: "Wire out"\n'
    at = text.rindex(block_memo)
    corrected = tmp_path / 'corrected.txt'
    corrected.write_text(text[:at] + '\t\tmemo: "Paid by wire"\n' + text[at + len(block_memo):])

    _done('import', book, corrected, '--include-business-objects', '--fx-rates', RATES)

    out = tmp_path / 'out.txt'
    _done('export', book, out)
    exported = out.read_text()
    assert _memo_of(exported, '2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c2c') == 'Paid by wire', exported
    assert _memo_of(exported, '1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b1b') == 'Paid by wire', exported
