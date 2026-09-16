"""A payment block giving a split or an account that cannot settle its record is refused.

Each record here already matches its block on `txn_guid:`, so no payment is
applied, and the refusals the payment path makes were never asked. What the
import did write was the block's memo, onto whatever split the block gave.
Measured on 5.10 before this, every case below reported `unchanged`, exit 0:

- **another invoice's split.** One 200.00 deposit settles INV-A and INV-B, a
  receivable split each. INV-A's block, read on its own giving INV-B's split
  and a new memo, wrote that memo onto INV-B's settlement.
- **the payment's own bank split** given in `txn_split_guid:`. The memo was
  written onto the bank split, and the split settling the invoice kept its
  own.
- **the invoice's own receivable** given as `bank_account:`. The memo was
  written onto the receivable split, and the bank split did not follow.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from infrastructure.gnucash.utils import get_account_full_name
from repositories.gnucash_repository import GnuCashRepository, SessionMode
from services.foreign_currency import iter_splits
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture

TWO_INVOICES = 'tests/fixtures/one_deposit_settling_inv_a_and_inv_b.txt'
SPLIT_B = '8192a3b4c5d6e7f80912233445566778'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _the_block(text, record):
    return next(part for part in text.split('\n\n') if part.startswith(record))


def _memos(book):
    repo = GnuCashRepository(str(book))
    repo.open(SessionMode.READ_ONLY)
    try:
        return sorted((get_account_full_name(split.GetAccount()), split.GetMemo())
                      for split in iter_splits(repo.book)
                      if split.GetParent().GetDate().strftime('%Y-%m-%d') == '2026-01-15')
    finally:
        repo.close()


def _paid_and_exported(tmp_path, source_text):
    book = tmp_path / 'book.gnucash'
    source = tmp_path / 'in.txt'
    source.write_text(source_text)
    made = _run('import', '--new', book, source, '--include-business-objects')
    assert made.exit_code == 0, made.output
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0
    return book, out.read_text()


def _read_back(tmp_path, book, text):
    edited = tmp_path / 'edited.txt'
    edited.write_text(text)
    return _run('import', book, edited, '--include-business-objects')


def test_another_invoices_split_is_refused(tmp_path):
    book, ledger = _paid_and_exported(
        tmp_path, ACCOUNTS + '\n' + Path(TWO_INVOICES).read_text())
    before = _memos(book)
    customer = _the_block(ledger, 'customer "C001"')
    block_a = _the_block(ledger, 'invoice "INV-A"')
    edited_a = re.sub(r'txn_split_guid: "[0-9a-f]+"', f'txn_split_guid: "{SPLIT_B}"',
                      block_a).replace('memo: "For A"', 'memo: "Corrected"')

    result = _read_back(tmp_path, book, customer + '\n\n' + edited_a + '\n')

    assert result.exit_code != 0, result.output
    assert SPLIT_B in result.output, result.output
    assert "another invoice's or bill's lot" in result.output, result.output
    assert _memos(book) == before


def test_the_payments_own_bank_split_is_refused(tmp_path):
    book, ledger = _paid_and_exported(
        tmp_path, ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'))
    before = _memos(book)
    block = _the_block(ledger, 'invoice "INV-001"')
    payment = block[block.index('\tpayment:'):]
    txn = re.search(r'txn_guid: "([0-9a-f]+)"', payment).group(1)
    section = ledger[ledger.index(f'guid: "{txn}"'):]
    bank_split = re.search(r'\tAssets:Bank 100\.00 CAD\n\t\tguid: "([0-9a-f]+)"',
                           section).group(1)
    edited = re.sub(r'txn_split_guid: "[0-9a-f]+"', f'txn_split_guid: "{bank_split}"',
                    payment).replace('memo: "Payment INV-001"', 'memo: "Corrected"')

    result = _read_back(tmp_path, book, ledger.replace(payment, edited))

    assert result.exit_code != 0, result.output
    assert bank_split in result.output, result.output
    assert 'Every split a payment applies' in result.output, result.output
    assert _memos(book) == before


def test_the_invoices_own_receivable_as_the_account_is_refused(tmp_path):
    book, ledger = _paid_and_exported(
        tmp_path, ACCOUNTS + '\n' + _fixture('q014_invoice_posted_paid'))
    before = _memos(book)
    block = _the_block(ledger, 'invoice "INV-001"')
    payment = block[block.index('\tpayment:'):]
    edited = payment.replace(
        'bank_account: "Assets:Bank"', 'bank_account: "Assets:Accounts Receivable"'
    ).replace('memo: "Payment INV-001"', 'memo: "Corrected"')

    result = _read_back(tmp_path, book, ledger.replace(payment, edited))

    assert result.exit_code != 0, result.output
    assert 'the account this invoice posts to' in result.output, result.output
    assert _memos(book) == before
