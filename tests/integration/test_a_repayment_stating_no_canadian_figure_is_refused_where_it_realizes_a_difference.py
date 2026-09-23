"""A foreign loan repaid in a transaction stating no Canadian figure, where the two sides cost different amounts.

Repaying the loan draws a cost basis down on each side: the dollars leave the
bank and the debt they pay off goes. When the debt cost 1.35 a dollar and the
dollars paying it cost 1.30, the difference is realized — 75.00 CAD on 1,500.00
USD — and `$residual$` is the split that states it. A transaction written wholly
in US dollars has no split in the book's own currency, so nothing in it can
state that figure.

Imported, it left the balance sheet unbalanced from that transaction on, by
exactly what it realized, and only `--verify-integrity` said so afterwards. So it
is refused as it lands, and the reader is told how to write it.

`tests/fixtures/a_us_loan_repaid_in_a_transaction_stating_no_canadian_figure.txt`
writes the refused repayment, then the same repayment in Canadian dollars, which
is imported and realizes the 75.00, then a second loan whose two sides both cost
1.30, repaid wholly in US dollars — imported, because nothing is realized.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run
from tests.integration.text_report_pages import key_of

LEDGER = 'tests/fixtures/a_us_loan_repaid_in_a_transaction_stating_no_canadian_figure.txt'


def _imported(tmp_path):
    book = tmp_path / 'book.gnucash'
    done = CliRunner().invoke(cli, ['import', '--new', str(book), LEDGER])
    return book, done


def test_the_repayment_written_wholly_in_us_dollars_is_refused(tmp_path):
    _, done = _imported(tmp_path)

    assert 'Errors:       1' in done.output, done.output
    assert ('error: Repay the loan, written wholly in US dollars: this '
            'transaction pays off 1500.00 USD owed, which cost 1.35 CAD/USD, '
            'with 1500.00 USD held, which cost 1.3 CAD/USD, so it realizes a '
            'difference of 75.00 CAD. It is written wholly in USD, so no split '
            'in it can state that figure.') in done.output, done.output


def test_it_says_how_to_write_it(tmp_path):
    _, done = _imported(tmp_path)

    assert ('Write it in CAD, each USD split valued at what its cost basis '
            'cost, and give the difference to a `$residual$` split.') \
        in done.output, done.output


def test_the_page_balances_with_the_repayment_written_in_canadian_dollars(tmp_path):
    """75.00 realized by the second repayment, and nothing by the third."""
    book, _ = _imported(tmp_path)
    drawn = _run(CliRunner(), 'balance-sheet', str(book),
                 '--as-of', '2030-12-31', '--no-itemize')
    assert drawn.exit_code == 0, drawn.output

    assert key_of(drawn.output, 'realized_gains_fx') == '75.00 CAD'
    assert key_of(drawn.output, 'total_assets') == '10300.00 CAD'
    assert key_of(drawn.output, 'total_liabilities_and_equity') == '10300.00 CAD'


def test_the_cost_bases_agree_with_the_accounts(tmp_path):
    """3,000.00 USD held and nothing owed, on both counts."""
    book, _ = _imported(tmp_path)
    listing = CliRunner().invoke(cli, ['fx-balances', str(book)]).output

    assert 'Total USD cost basis balance: 3,000.00 USD' in listing, listing
    assert 'Total USD held in accounts: 3,000.00 USD' in listing, listing
