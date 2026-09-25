"""A disposal giving no cost basis is refused as what its splits show it is.

Each case is a transaction of the book behind the README's balance sheet,
`a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt`, with
its `cost_basis_split_guid:` taken off and nothing else changed. The refusal
lists the splits it read the kind from, each with its account's type and
currency, and says what that kind of transaction is: shares bought with US
dollars, shares sold for US dollars, US dollars sold for Canadian ones, a US
dollar loan repaid out of US dollars held. Said as "spends" whichever it was,
a sale of US dollars read as an expense to the person refused.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run

BOOK = 'tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'


def _refused_without_the_pick(tmp_path, head):
    """The book imported whole, the transaction under `head` giving no cost basis."""
    text = Path(BOOK).read_text()
    block = re.search(rf'{re.escape(head)}\n(?:\t[^\n]*\n)*', text).group(0)
    bare = ''.join(line + '\n' for line in block.splitlines()
                   if 'cost_basis_split_guid' not in line)
    ledger = tmp_path / 'book.txt'
    ledger.write_text(text.replace(block, bare))
    done = _run(CliRunner(), 'import', '--new', str(tmp_path / 'book.gnucash'),
                str(ledger), '--atomic')
    assert done.exit_code != 0, done.output
    return done.output


def test_shares_bought_with_us_dollars_are_refused_as_a_purchase(tmp_path):
    refused = _refused_without_the_pick(tmp_path, '2025-08-15 * "Buy 20 AMZN at 200.00 USD"')

    assert ('this transaction is a purchase of 20.0000 AMZN with 4000.00 USD the book '
            'held: Assets:USD Bank, a Bank account in USD, is credited 4000.00 USD; '
            'Assets:AMZN, a Stock account in AMZN, is debited 20.0000 AMZN. A purchase '
            'requires a consumption of one or more cost bases, but no split says '
            'which.') in refused, refused


def test_shares_sold_for_us_dollars_are_refused_as_a_sale(tmp_path):
    refused = _refused_without_the_pick(tmp_path, '2026-06-30 * "Sell 8 AMZN at 260.00 USD"')

    assert ('this transaction is a sale of 8.0000 AMZN the book held for 2080.00 USD: '
            'Assets:AMZN, a Stock account in AMZN, is credited 8.0000 AMZN; '
            'Assets:USD Bank, a Bank account in USD, is debited 2080.00 USD. A sale '
            'requires') in refused, refused


def test_us_dollars_sold_for_canadian_ones_are_refused_as_a_sale(tmp_path):
    refused = _refused_without_the_pick(tmp_path, '2026-07-15 * "Sell 3,000.00 USD at 1.38"')

    assert ('this transaction is a sale of 3000.00 USD the book held for 4140.00 CAD: '
            'Assets:USD Bank, a Bank account in USD, is credited 3000.00 USD; '
            'Assets:CAD Bank, a Bank account in CAD, is debited 4140.00 CAD. A sale '
            'requires') in refused, refused


def test_a_us_dollar_loan_repaid_out_of_us_dollars_held_is_refused_as_a_repayment(tmp_path):
    refused = _refused_without_the_pick(
        tmp_path, '2026-09-30 * "Repay 1,500.00 USD of the loan with interest"')

    assert ('this transaction is a repayment of USD the book owed with 1600.00 USD the '
            'book held: Assets:USD Bank, a Bank account in USD, is credited 1600.00 USD; '
            'Liabilities:USD Loan, a Liability account in USD, is debited 1500.00 USD, '
            '1500.00 of it repaying what it owed. A repayment requires') in refused, refused
