"""A payment block's figure that is not a number is refused, before the invoice is compared.

`amount:`, `prepayment:`, `settled_amount:` and `share_price:` are numbers
written with a point. INV-001 is posted and paid 100.00 CAD, and its export is
read back with one figure mistyped. A block that gives its transaction is
matched by guid, so nothing read the figure: `1OO` for `100` was answered
`unchanged` and the mistyped line stayed in the file with nothing said. A
decimal comma is the same mistake (`docs/multi-currency.md`, `60,00` for
`60.00`). On a new book `amount: 100,00` was refused with nothing but
`[<class 'decimal.ConversionSyntax'>]`, and `prepayment: 50,00` on a block
giving no transaction was read as 50.00.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture

AMOUNT = '\t\tamount: 100.00\n'


def _import(book, text, tmp_path, *new):
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(text)
    return CliRunner().invoke(cli, ['import', *new, str(book), str(ledger),
                                    '--include-business-objects'])


def _exported(book, tmp_path):
    out = tmp_path / 'out.txt'
    result = CliRunner().invoke(cli, ['export', str(book), str(out),
                                      '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out.read_text()


def _invoice(exported):
    block = exported[exported.index('invoice "INV-001"'):]
    return block[:block.index('\n\n')] if '\n\n' in block else block


@pytest.mark.parametrize('new, refusal', [
    ('\t\tamount: 1OO\n', "payment amount must be a number, got '1OO'"),
    ('\t\tamount: 100,00\n', "payment amount must be a number, got '100,00'"),
    (AMOUNT + '\t\tprepayment: x\n', "prepayment field must be a number, got 'x'"),
    (AMOUNT + '\t\tprepayment: 0,00\n', "prepayment field must be a number, got '0,00'"),
    (AMOUNT + '\t\tsettled_amount: x\n', "payment settled_amount 'x' is not a number"),
    (AMOUNT + '\t\tshare_price: x\n', "payment share_price 'x' is not a number"),
], ids=['amount', 'amount-with-a-comma', 'prepayment', 'prepayment-with-a-comma',
        'settled-amount', 'share-price'])
def test_the_export_read_back_with_one_mistyped_is_refused(tmp_path, new, refusal):
    book = tmp_path / 'book.gnucash'
    made = _import(book, ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'),
                   tmp_path, '--new')
    assert made.exit_code == 0, made.output
    exported = _exported(book, tmp_path)
    assert AMOUNT in exported, exported

    result = _import(book, exported.replace(AMOUNT, new), tmp_path)

    assert result.exit_code != 0, result.output
    assert refusal in result.output, result.output
    assert 'is now orphaned' not in result.output, result.output
    assert _invoice(_exported(book, tmp_path)) == _invoice(exported)


@pytest.mark.parametrize('key', ['prepayment', 'settled_amount', 'share_price'])
def test_an_empty_figure_states_nothing(tmp_path, key):
    """`key: ""` states no figure, as leaving the key out states none."""
    book = tmp_path / 'book.gnucash'
    made = _import(book, ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'),
                   tmp_path, '--new')
    assert made.exit_code == 0, made.output
    exported = _exported(book, tmp_path)

    result = _import(book, exported.replace(AMOUNT, AMOUNT + f'\t\t{key}: ""\n'), tmp_path)

    assert result.exit_code == 0, result.output
    assert _invoice(_exported(book, tmp_path)) == _invoice(exported)


def test_an_empty_amount_on_a_new_book_is_refused_as_no_amount(tmp_path):
    text = ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid')
    assert '\t\tamount: 100\n' in text, text

    result = _import(tmp_path / 'book.gnucash', text.replace('\t\tamount: 100\n', '\t\tamount: ""\n'),
                     tmp_path, '--new')

    assert result.exit_code != 0, result.output
    assert 'amount' in result.output, result.output
    assert 'Invalid literal' not in result.output, result.output


@pytest.mark.parametrize('old, new, refusal', [
    ('\t\tamount: 100\n', '\t\tamount: 100,00\n',
     "payment amount must be a number, got '100,00'"),
    ('\t\tamount: 100\n', '\t\tamount: 150\n\t\tprepayment: 50,00\n',
     "prepayment field must be a number, got '50,00'"),
], ids=['amount-with-a-comma', 'prepayment-with-a-comma'])
def test_a_new_book_is_refused_it_too(tmp_path, old, new, refusal):
    text = ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid')
    assert old in text, text

    result = _import(tmp_path / 'book.gnucash', text.replace(old, new), tmp_path, '--new')

    assert result.exit_code != 0, result.output
    assert refusal in result.output, result.output
    assert 'ConversionSyntax' not in result.output, result.output
