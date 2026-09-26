"""A payment block stating its record's own posting is refused before anything changes.

A posted record's ledger is read back with its payment's `txn_guid:` set to the
record's own posting transaction. A posting pays nothing, and the refusal that
says so ran only when the payment was applied. Measured on 5.10 before this:
the block read as a changed payment, the rebuild unposted the invoice and so
destroyed that very posting, the guid then matched nothing, and the payment the
invoice had was put back. The run reported `updated` with exit 0, a corrected
memo never landed, and every later read did the same under a new posting guid.
"""

import re

import pytest
from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


@pytest.mark.parametrize('fixture, record, word', [
    ('q014_invoice_posted_paid', 'invoice "INV-001"', 'invoice'),
    ('q014_bill_posted_paid', 'bill "BILL-001"', 'bill'),
], ids=['invoice', 'bill'])
def test_it_is_refused_and_the_posting_is_kept(tmp_path, fixture, record, word):
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(ACCOUNTS + '\n' + _fixture(fixture))
    made = _run('import', '--new', book, source, '--include-business-objects')
    assert made.exit_code == 0, made.output
    before = tmp_path / 'before.txt'
    assert _run('export', book, before, '--include-business-objects').exit_code == 0
    ledger = before.read_text()
    block = next(part for part in ledger.split('\n\n') if part.startswith(record))
    payment = block[block.index('\tpayment:'):]
    posting = re.search(r'posted_txn_guid: "([0-9a-f]+)"', block).group(1)
    edited = tmp_path / 'edited.txt'
    edited.write_text(ledger.replace(
        payment, re.sub(r'txn_guid: "[0-9a-f]+"', f'txn_guid: "{posting}"', payment)))

    result = _run('import', book, edited, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert f"this {word}'s own posting transaction" in result.output, result.output
    after = tmp_path / 'after.txt'
    assert _run('export', book, after, '--include-business-objects').exit_code == 0
    assert f'posted_txn_guid: "{posting}"' in after.read_text()


def test_a_new_invoice_stating_another_invoices_posting_is_refused(tmp_path):
    """INV-002 is new, and its payment states INV-001's posting transaction.
    The new invoice has no posting of its own for this to be, so the refusal
    says whose posting it is, and INV-002 is not created."""
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'))
    made = _run('import', '--new', book, source, '--include-business-objects')
    assert made.exit_code == 0, made.output
    before = tmp_path / 'before.txt'
    assert _run('export', book, before, '--include-business-objects').exit_code == 0
    block = next(part for part in before.read_text().split('\n\n')
                 if part.startswith('invoice "INV-001"'))
    posting = re.search(r'posted_txn_guid: "([0-9a-f]+)"', block).group(1)
    new = tmp_path / 'new.txt'
    new.write_text(_fixture('q014_invoice_posted_paid')
                   .replace('INV-001', 'INV-002')
                   .replace('\t\tbank_account: "Assets:Bank"\n',
                            f'\t\tbank_account: "Assets:Bank"\n\t\ttxn_guid: "{posting}"\n'))

    result = _run('import', book, new, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert "the posting transaction of invoice 'INV-001'" in result.output, result.output
    after = tmp_path / 'after.txt'
    assert _run('export', book, after, '--include-business-objects').exit_code == 0
    assert 'invoice "INV-002"' not in after.read_text()
