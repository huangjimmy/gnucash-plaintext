"""Two payment blocks giving the same split are refused, whatever their memos say.

One split is one settlement, stated once. A paid record is imported and
exported, and its block is read back with the `payment:` block given twice,
both copies giving the same `txn_guid:` and `txn_split_guid:`. Measured on
5.10 before this:

- with the same memo, the second copy read as a payment being added and
  changed nothing, and the run reported `updated` and saved the book, on every
  read of the file;
- with another memo on the second copy, the run reported `updated` and that
  memo replaced the first.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _the_block(text, record):
    return next(part for part in text.split('\n\n') if part.startswith(record))


@pytest.mark.parametrize('fixture, record, memo, second_memo', [
    ('q014_invoice_posted_paid', 'invoice "INV-001"', 'Payment INV-001', 'Payment INV-001'),
    ('q014_invoice_posted_paid', 'invoice "INV-001"', 'Payment INV-001', 'Paid again'),
    ('q014_bill_posted_paid', 'bill "BILL-001"', 'Payment BILL-001', 'Payment BILL-001'),
], ids=['invoice-same-memo', 'invoice-another-memo', 'bill-same-memo'])
def test_it_is_refused_and_the_book_is_left_as_it_was(tmp_path, fixture, record, memo,
                                                      second_memo):
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(ACCOUNTS + '\n' + _fixture(fixture))
    made = _run('import', '--new', book, source, '--include-business-objects')
    assert made.exit_code == 0, made.output
    before = tmp_path / 'before.txt'
    assert _run('export', book, before, '--include-business-objects').exit_code == 0
    block = _the_block(before.read_text(), record)
    payment = block[block.index('\tpayment:'):]
    split_guid = next(line.split(':', 1)[1].strip().strip('"')
                      for line in payment.splitlines()
                      if line.strip().startswith('txn_split_guid:'))
    twice = tmp_path / 'twice.txt'
    twice.write_text(block + '\n'
                     + payment.replace(f'memo: "{memo}"', f'memo: "{second_memo}"') + '\n')

    result = _run('import', book, twice, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert split_guid in result.output, result.output
    after = tmp_path / 'after.txt'
    assert _run('export', book, after, '--include-business-objects').exit_code == 0
    assert _the_block(after.read_text(), record) == block


def test_the_same_transaction_given_twice_without_its_split_owes_nothing_for_the_second(
        tmp_path):
    """The second copy gives `txn_guid:` alone, so no split is given twice. The
    transaction's split is already the invoice's, and the invoice owes nothing
    for the second copy to settle, so it is refused for that. Measured on 5.10."""
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'))
    assert _run('import', '--new', book, source, '--include-business-objects').exit_code == 0
    before = tmp_path / 'before.txt'
    assert _run('export', book, before, '--include-business-objects').exit_code == 0
    block = _the_block(before.read_text(), 'invoice "INV-001"')
    payment = block[block.index('\tpayment:'):]
    bare = ''.join(line + '\n' for line in payment.splitlines()
                   if not line.strip().startswith('txn_split_guid:'))
    twice = tmp_path / 'twice.txt'
    twice.write_text(block + '\n' + bare)

    result = _run('import', book, twice, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert 'owes nothing for this payment to settle' in result.output, result.output
