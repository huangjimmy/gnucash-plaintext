"""Somebody else's payment of the same size on the same day is not this one.

A payment block whose `txn_guid:` resolves to nothing is refused when the book
already holds the money it describes — that is what stops a mistyped guid
entering a movement twice. What "describes" means has to be narrow enough to
be about *this* payment: two customers each paying 100.00 into the same
account on the same day is ordinary bookkeeping, and a date and an amount do
not tell them apart.

Read that loosely, rebuilding one invoice from a printed file into a book
that happens to hold the other customer's deposit is refused outright — and
the remedy offered is to hand-edit a file this tool generated.

The memo is what a payment block carries to say which movement it is, so it is
part of the question.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')

# Two customers, each paying 100.00 into Assets:Bank on 2026-01-15. The second
# invoice's payment names a guid this book does not hold, so it is recorded
# from the block — and the first customer's deposit must not be mistaken for
# it.
LEDGER = (FIXTURES / 'a_payment_named_with_account.txt').read_text()

SECOND = """
customer "C-OTHER"
\tname: "Other Customer"
\tcurrency: CAD

invoice "INV-OTHER"
\tcustomer_id: "C-OTHER"
\tcurrency: CAD
\tdate_opened: 2026-01-01
\tentry:
\t\tdate: 2026-01-01
\t\tdescription: "A line"
\t\taccount: "Income:Sales"
\t\tquantity: 1
\t\tprice: 100
\t\ttaxable: false
\t\ttax_included: false
\tposted:
\t\tdate: 2026-01-01
\t\tdue: 2026-01-31
\t\tar_account: "Assets:Accounts Receivable"
\t\tmemo: "Invoice INV-OTHER"
\t\taccumulate: true
\tpayment:
\t\tdate: 2026-01-15
\t\tamount: 100
\t\taccount: "Assets:Bank"
\t\tmemo: "Paid by the other customer"
\t\ttxn_guid: "beefdeadbeefdeadbeefdeadbeefdead"
"""


@pytest.fixture
def book(tmp_path):
    """A book already holding the first customer's 100.00 on 2026-01-15."""
    path = tmp_path / 'book.gnucash'
    first = tmp_path / 'first.txt'
    first.write_text(LEDGER)
    result = CliRunner().invoke(cli, [
        'import', '--new', str(path), str(first), '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return path


class TestASecondCustomerPayingTheSameAmountThatDay:
    def test_it_is_not_refused_as_a_duplicate(self, book, tmp_path):
        """Same date, same amount, same account — a different payment."""
        ledger = tmp_path / 'second.txt'
        ledger.write_text(LEDGER + SECOND)

        result = CliRunner().invoke(cli, [
            'import', str(book), str(ledger), '--include-business-objects'])

        assert result.exit_code == 0, result.output

    def test_both_payments_are_in_the_book(self, book, tmp_path):
        ledger = tmp_path / 'second.txt'
        ledger.write_text(LEDGER + SECOND)
        CliRunner().invoke(cli, [
            'import', str(book), str(ledger), '--include-business-objects'])

        out = tmp_path / 'out.txt'
        assert CliRunner().invoke(cli, [
            'export', str(book), str(out),
            '--include-business-objects']).exit_code == 0
        text = out.read_text()
        assert 'Paid' in text, text
        assert 'Paid by the other customer' in text, text
