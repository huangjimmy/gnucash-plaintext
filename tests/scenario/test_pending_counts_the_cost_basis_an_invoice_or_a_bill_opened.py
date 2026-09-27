"""`$pending$` counts the cost basis an invoice or a bill opened.

An invoice's posting opens a cost basis on its A/R split, and once the invoice
is collected into a US dollar bank, that cost basis is what the dollars in the
bank cost. A bill's posting opens one on its A/P split, and once the bill is
paid on a US dollar card, that cost basis is what the dollars owed on the card
cost. A disposal of those dollars whose cost basis is not chosen yet is
written `cost_basis_split_guid: $pending$`, and the book counts it pending
against them until an edit states the cost basis.

Each book here keeps one US dollar cost basis, the invoice's or the bill's,
so the disposal has exactly one cost basis to be chosen from.

The invoice's case is the one reported in Q-054, "What was reported": a
user's application imported a sale of dollars an invoice had collected with
`$pending$`, and it was refused as having no cost basis to choose, while the
same sale stating the invoice's guid was accepted. The bill's case is its
mirror.
"""

from click.testing import CliRunner

from tests.conftest import _run

FIXTURES = 'tests/fixtures/'
RATES = FIXTURES + 'usd_at_the_rates_the_statement_lines_records_were_posted_at.yaml'
COLLECTED = FIXTURES + 'usd_collected_off_an_invoice_and_still_held.txt'
A_DOLLAR_SOLD = FIXTURES + 'a_dollar_the_invoice_collected_sold_pending_its_cost_basis.txt'
OWED_ON_THE_CARD = FIXTURES + 'usd_owed_on_a_card_that_paid_a_bill.txt'
PART_REPAID = FIXTURES + 'part_of_the_card_that_paid_a_bill_repaid_pending_its_cost_basis.txt'


def _book(tmp_path, ledger):
    book = tmp_path / 'book.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book), ledger,
                '--include-business-objects', '--fx-rates', RATES)
    assert made.exit_code == 0 and 'Errors:       0' in made.output, made.output
    return book


def _imported(book, ledger):
    done = _run(CliRunner(), 'import', str(book), ledger, '--fx-rates', RATES)
    assert done.exit_code == 0 and 'Errors:       0' in done.output, done.output
    return done


def _consistent(book):
    costs = _run(CliRunner(), 'fx-balances', str(book), '--verify-costs')
    assert costs.exit_code == 0 and 'warning' not in costs.output, costs.output
    integrity = _run(CliRunner(), '--verify-integrity', str(book))
    assert integrity.exit_code == 0, integrity.output
    return costs.output


class TestADollarAnInvoiceCollectedSoldPendingItsCostBasis:
    def test_it_is_imported(self, tmp_path):
        book = _book(tmp_path, COLLECTED)

        done = _imported(book, A_DOLLAR_SOLD)

        assert 'Transactions: 1' in done.output, done.output

    def test_it_is_pending_against_the_invoice_s_cost_basis(self, tmp_path):
        book = _book(tmp_path, COLLECTED)
        _imported(book, A_DOLLAR_SOLD)

        listed = _consistent(book)

        assert 'Invoice INV-USD-1' in listed, listed
        assert '1 disposal(s) pending their cost basis: 1.00 USD.' in listed, listed
        assert 'Total USD held in accounts: 2,719.00 USD' in listed, listed


class TestPartOfACardThatPaidABillRepaidPendingItsCostBasis:
    def test_it_is_imported(self, tmp_path):
        book = _book(tmp_path, OWED_ON_THE_CARD)

        done = _imported(book, PART_REPAID)

        assert 'Transactions: 1' in done.output, done.output

    def test_it_is_pending_against_the_bill_s_cost_basis(self, tmp_path):
        book = _book(tmp_path, OWED_ON_THE_CARD)
        _imported(book, PART_REPAID)

        listed = _consistent(book)

        assert 'Bill BILL-USD-1' in listed, listed
        assert '1 disposal(s) pending their cost basis: 100.00 USD.' in listed, listed
        assert 'Total USD owed on accounts: 900.00 USD' in listed, listed
