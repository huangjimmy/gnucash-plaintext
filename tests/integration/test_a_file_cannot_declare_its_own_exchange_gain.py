"""Stating `took_the_residual` in a file does not make a split an exchange gain.

`realized_gains_fx` is the sum of the splits a `$residual$` resolved to, and
the book records which split that was in a `took_the_residual` KVP as the
transaction is imported. The importer writes it only where the transaction
disposes of foreign currency against a cost basis, is stated in the book's own
currency, and the split is one a difference can land on.

But the key is an ordinary custom slot, so a file can state it on any split it
likes, and the export writes it back out — measured, so it cannot be refused on
sight without breaking the round trip of every book that has a real one.
Believed on its own word it let a file put any split into the figure: stated on
a Canadian rent line it booked an 800.00 CAD exchange loss on a book holding no
foreign currency at all.

So the ledger is asked as well, the same way a stored cost is only consulted
where the transaction states none. Three things must hold, and each is covered
here by a file that fails that one while satisfying the others, so no case
passes if its own rule is dropped:

- **the transaction disposes against a cost basis** — the rent line fails this;
- **the split is on an income or expense account** — the bank line of a real
  disposal fails this, a residual balancing onto a bank having moved money
  rather than measured anything;
- **the transaction is in the book's own currency** — the US dollar bank fee
  fails this, and counted it would add US dollars into a Canadian total.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import key_of

A_CAD_BOOK = 'tests/fixtures/a_cad_book_using_residual_on_an_ordinary_expense.txt'
A_BOOK_HOLDING_US_DOLLARS = 'tests/fixtures/a_cad_book_that_bought_a_thousand_usd.txt'
STATED_ON_THE_RENT = ('tests/fixtures/'
                      'a_file_stating_the_residual_key_on_a_rent_line.txt')
STATED_IN_US_DOLLARS = ('tests/fixtures/'
                        'a_file_stating_the_residual_key_in_a_us_dollar_transaction.txt')
STATED_ON_A_BANK_SPLIT = ('tests/fixtures/'
                          'a_file_stating_the_residual_key_on_a_bank_split.txt')
AS_OF = '2026-12-31'


def _filled(runner, book, fixture):
    """The fixture's text, with the cost basis guid filled in where it asks.

    A guid is minted fresh on each import, so a fixture that gives one carries
    a placeholder, and the guid is read from `fx-balances` here — the way every
    other disposal fixture in this suite is applied.
    """
    text = Path(fixture).read_text(encoding='utf-8')
    if '{usd_basis}' not in text:
        return text
    listing = _run(runner, 'fx-balances', str(book))
    assert listing.exit_code == 0, listing.output
    found = re.search(r'\b([0-9a-f]{32})\b', listing.output)
    assert found, listing.output
    return text.replace('{usd_basis}', found.group(1))


def _page(tmp_path, extra=None, book=A_CAD_BOOK):
    runner = CliRunner()
    made_at = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(made_at), book)
    assert made.exit_code == 0, made.output
    if extra is not None:
        ledger = tmp_path / 'stated.txt'
        ledger.write_text(_filled(runner, made_at, extra), encoding='utf-8')
        landed = _run(runner, 'import', str(made_at), str(ledger))
        assert landed.exit_code == 0, landed.output
    drawn = _run(runner, 'balance-sheet', str(made_at), '--as-of', AS_OF)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


class TestATransactionThatDisposesOfNothing:

    def test_the_file_is_accepted(self, tmp_path):
        """It is an ordinary transaction carrying an ordinary custom key.

        Refusing it would refuse the export of any book holding a real one.
        """
        page = _page(tmp_path, STATED_ON_THE_RENT)

        assert key_of(page, 'total_assets') == '8300.00 CAD'

    def test_the_stated_key_is_no_exchange_gain(self, tmp_path):
        """800.00 CAD of rent, on a book that has never held foreign currency."""
        page = _page(tmp_path, STATED_ON_THE_RENT)

        assert key_of(page, 'realized_gains_fx') == '0.00 CAD'
        assert key_of(page, 'total_realized_gains') == '0.00 CAD'

    def test_the_working_lists_it_no_more_than_the_key_counts_it(self, tmp_path):
        page = _page(tmp_path, STATED_ON_THE_RENT)

        listed = [line for line in page.splitlines()
                  if line.lstrip().startswith('#   ') and 'Rent' in line]
        assert listed == [], page

    def test_the_book_without_it_reads_the_same(self, tmp_path):
        """The key is what changed, so the page must not depend on it."""
        page = _page(tmp_path)

        assert key_of(page, 'realized_gains_fx') == '0.00 CAD'


class TestASplitNoDifferenceCanLandOn:
    """A real disposal, with the key on the bank line rather than the gain.

    The sale made 100.00 and the bank received 1,400.00. One split claims the
    residual, so the one-claim rule has nothing to refuse, and the transaction
    is a disposal in the book's own currency giving its cost basis. Only the
    account turns it away — counted, the page would state the money the bank
    received as the gain.
    """

    def test_the_file_is_accepted(self, tmp_path):
        page = _page(tmp_path, STATED_ON_A_BANK_SPLIT,
                     book=A_BOOK_HOLDING_US_DOLLARS)

        assert key_of(page, 'total_assets') != '', page

    def test_the_bank_line_is_no_exchange_gain(self, tmp_path):
        page = _page(tmp_path, STATED_ON_A_BANK_SPLIT,
                     book=A_BOOK_HOLDING_US_DOLLARS)

        assert key_of(page, 'realized_gains_fx') == '0.00 CAD'
        assert key_of(page, 'total_realized_gains') == '0.00 CAD'

    def test_the_working_lists_no_bank_line(self, tmp_path):
        page = _page(tmp_path, STATED_ON_A_BANK_SPLIT,
                     book=A_BOOK_HOLDING_US_DOLLARS)

        listed = [line for line in page.splitlines()
                  if line.lstrip().startswith('#   ') and 'CAD Bank' in line]
        assert listed == [], page


class TestATransactionInAnotherCurrency:
    """A US dollar bank fee, with the key on the expense split.

    The split is one a difference could land on, so the account does not turn
    it away; the currency does. Counted, its 20.00 US dollars would be added
    into a Canadian total with no price applied.
    """

    def test_the_file_is_accepted(self, tmp_path):
        page = _page(tmp_path, STATED_IN_US_DOLLARS,
                     book=A_BOOK_HOLDING_US_DOLLARS)

        assert key_of(page, 'total_assets') != '', page

    def test_it_states_no_canadian_gain(self, tmp_path):
        page = _page(tmp_path, STATED_IN_US_DOLLARS,
                     book=A_BOOK_HOLDING_US_DOLLARS)

        assert key_of(page, 'realized_gains_fx') == '0.00 CAD'
        assert key_of(page, 'total_realized_gains') == '0.00 CAD'

    def test_the_working_lists_no_split_of_that_transaction(self, tmp_path):
        page = _page(tmp_path, STATED_IN_US_DOLLARS,
                     book=A_BOOK_HOLDING_US_DOLLARS)

        listed = [line for line in page.splitlines()
                  if line.lstrip().startswith('#   ') and 'Bank Fees' in line]
        assert listed == [], page
