"""A paid invoice's block read into another book, and then read into it again edited.

INV-001 is imported paid into book A and exported. Its block, with the
customer, is read into a fresh book B, where its `txn_guid:` states a
transaction of A's that B does not hold, so the payment is recorded from the
block. The same block is then read into B again, edited. Measured on 5.10:

- **with `amount: ""`,** the block no longer describes a payment, so its
  `txn_guid:` is only a reference, and it matches nothing B holds. It is refused.
- **with `bank_account:` set to another bank,** the block describes another
  movement: it is recorded, and the payment B held is left orphaned, which the
  import warns of once the book is saved.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.integration.test_find_orphan_payments import ACCOUNTS, _fixture

SAVINGS = '''2026-01-01 open Assets:Savings
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
'''


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _read_into_another_book(tmp_path):
    """Book B, and the page it was made from."""
    a = tmp_path / 'a.gnucash'
    source = tmp_path / 'a.txt'
    source.write_text(ACCOUNTS + SAVINGS + '\n' + _fixture('q014_invoice_posted_paid'))
    assert _run('import', '--new', a, source, '--include-business-objects').exit_code == 0
    out = tmp_path / 'a-out.txt'
    assert _run('export', a, out, '--include-business-objects').exit_code == 0
    parts = out.read_text().split('\n\n')
    customer = next(part for part in parts if part.startswith('customer "C001"'))
    block = next(part for part in parts if part.startswith('invoice "INV-001"'))
    page = ACCOUNTS + SAVINGS + '\n' + customer + '\n\n' + block + '\n'
    b = tmp_path / 'b.gnucash'
    first = tmp_path / 'b.txt'
    first.write_text(page)
    made = _run('import', '--new', b, first, '--include-business-objects')
    assert made.exit_code == 0, made.output
    assert 'recording the payment from the block' in made.output, made.output
    return b, page


def test_with_an_empty_amount_its_guid_is_refused_as_one_the_book_lacks(tmp_path):
    b, page = _read_into_another_book(tmp_path)
    assert 'amount: 100.00' in page
    edited = tmp_path / 'edited.txt'
    edited.write_text(page.replace('amount: 100.00', 'amount: ""'))

    result = _run('import', b, edited, '--include-business-objects')

    assert result.exit_code != 0, result.output
    assert 'not found in book' in result.output, result.output


def test_with_another_bank_it_is_recorded_and_the_old_payment_warned_of(tmp_path):
    b, page = _read_into_another_book(tmp_path)
    assert 'bank_account: "Assets:Bank"' in page
    edited = tmp_path / 'edited.txt'
    edited.write_text(page.replace('bank_account: "Assets:Bank"',
                                   'bank_account: "Assets:Savings"'))

    result = _run('import', b, edited, '--include-business-objects')

    assert result.exit_code == 0, result.output
    assert 'invoice "INV-001": updated' in result.output, result.output
    assert 'is now orphaned' in result.output, result.output
    listed = _run('find-orphan-payments', b)
    assert 'Found 1 orphan bank-side payment transaction' in listed.output, listed.output
