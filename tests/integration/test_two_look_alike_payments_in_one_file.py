"""One file's own payments must not refuse each other.

The duplicate-payment refusal asks whether the book already holds the movement
a block describes. "Already" has to mean before this run: a payment the same
import created moments ago is not money the book had, it is money this file is
entering.

Two installments of the same size on the same day, stating no memo, are one
invoice's ordinary shape — and read into a book that never held their guids,
which is the case the whole branch exists for, the second block found the
payment the first had just minted and the run was refused. The message then
named a transaction created seconds earlier, appearing in no file, and told
the reader to correct a guid to it.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = """\
2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Income
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Income:Sales
\ttype: Income
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Accounts Receivable
\ttype: Accounts Receivable
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"

customer "C-TWICE"
\tname: "Two Installments"
\tcurrency: CAD

invoice "INV-TWICE"
\tcustomer_id: "C-TWICE"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "A line"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 200
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "Invoice INV-TWICE"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-01-15
\t\tamount: 100
\t\taccount: "Assets:Bank"
\t\tmemo: "Installment"
\t\ttxn_guid: "aaaabbbbccccddddeeeeffff00001111"
\tpayment:
\t\tdate: 2026-01-15
\t\tamount: 100
\t\taccount: "Assets:Bank"
\t\tmemo: "Installment"
\t\ttxn_guid: "aaaabbbbccccddddeeeeffff00002222"
"""


def _transaction_count(book):
    from gnucash import Query

    from repositories.gnucash_repository import GnuCashRepository, SessionMode
    repo = GnuCashRepository(str(book))
    repo.open(mode=SessionMode.READ_ONLY)
    try:
        query = Query()
        query.search_for('Trans')
        query.set_book(repo.book)
        count = len(list(query.run()))
        query.destroy()
        return count
    finally:
        repo.close()


@pytest.fixture
def result_and_book(tmp_path):
    book = tmp_path / 'book.gnucash'
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(LEDGER)
    result = CliRunner().invoke(cli, [
        'import', '--new', str(book), str(ledger), '--include-business-objects'])
    return result, book


class TestTwoInstallmentsThatLookAlike:
    def test_the_file_is_read(self, result_and_book):
        """Neither guid resolves, so both are recorded from their blocks."""
        result, _book = result_and_book

        assert result.exit_code == 0, result.output

    def test_both_payments_land(self, result_and_book):
        """Two blocks, two movements — not one refused as a copy of the other."""
        result, book = result_and_book
        assert result.exit_code == 0, result.output

        # The posting plus two payments.
        assert _transaction_count(book) == 3, _transaction_count(book)
