"""The gain notes are the balance sheet's, and the income statement states none.

Both statements are drawn by the same report and share the prose that says what
their keys mean. The gain keys belong to the balance sheet alone, so the
paragraphs explaining them do too — Q-043 says these lines are "added only
where they mean something".

Added to the shared list they appeared on every income statement, which then
told a reader that "the gain keys are the exception" on a page carrying no gain
key, and described "the last key" as GnuCash's own balancing amount, added into
nothing — when the last key on an income statement is `net_income`, which is
the figure the whole page is for.

Nothing caught it: the test that checks an income statement carries no gain
working looks for the `name:` headers of the working groups, and the prose has
none. This asserts the prose itself.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import a_book_using_trading_accounts, key_of

LEDGER = 'tests/fixtures/a_cad_book_holding_us_listed_shares.txt'
THE_CAD_BOOK = 'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'

# Sentences the balance sheet uses to explain figures the income statement has
# no equivalent of.
GAIN_PROSE = (
    'The gain keys are the exception',
    'A gain already taken is stated apart',
    'Nothing adds it in',
    # These two were added to the shared list rather than this one, so every
    # income statement told a reader that two of its section totals were not
    # GnuCash's and that `gnucash_balancing_amount` stated GnuCash's beside
    # them — on a page carrying neither key, and every one of whose totals is
    # GnuCash's own. The three sentences above did not catch it.
    #
    # Matched on what the claim is about, never on the words it is made in.
    # Taken from the sentence as it happened to read, the check passed against
    # its own wording and missed the same claim said differently: "and so is
    # every section total but two" and "Every section total on this page is
    # GnuCash's own figure but two" are one claim and share no phrase worth
    # matching. A key is what does not move. An income statement has neither
    # of these, so neither can honestly appear on one.
    'total_equity and total_liabilities_and_equity',
    'gnucash_balancing_amount',
)


def _book(tmp_path):
    made = _run(CliRunner(), 'import', '--new', str(tmp_path / 'book.gnucash'),
                LEDGER)
    assert made.exit_code == 0, made.output
    return tmp_path / 'book.gnucash'


def test_the_income_statement_carries_none_of_the_gain_prose(tmp_path):
    drawn = _run(CliRunner(), 'income-statement', str(_book(tmp_path)),
                 '--start', '2026-01-01', '--end', '2026-12-31')
    assert drawn.exit_code == 0, drawn.output

    for sentence in GAIN_PROSE:
        assert sentence not in drawn.output, sentence


def test_its_last_key_is_its_own(tmp_path):
    """What the borrowed paragraph called "the last key" was `net_income`.

    On a book that has income and expenses to state: the shares book holds
    neither, so its income statement selects no accounts and has no keys at all
    to be wrong about.
    """
    book = tmp_path / 'trading.gnucash'
    made = _run(CliRunner(), 'import', '--new', str(book),
                'tests/fixtures/a_cad_book_whose_expenses_exceed_its_income.txt')
    assert made.exit_code == 0, made.output

    drawn = _run(CliRunner(), 'income-statement', str(book),
                 '--start', '2026-01-01', '--end', '2026-12-31')
    assert drawn.exit_code == 0, drawn.output

    assert key_of(drawn.output, 'net_income').endswith(' CAD'), drawn.output
    for sentence in GAIN_PROSE:
        assert sentence not in drawn.output, sentence


def test_the_balance_sheet_still_explains_its_gain_keys(tmp_path):
    """Moved, not deleted: the page they belong to keeps them."""
    drawn = _run(CliRunner(), 'balance-sheet', str(_book(tmp_path)),
                 '--as-of', '2026-12-31')
    assert drawn.exit_code == 0, drawn.output

    for sentence in GAIN_PROSE:
        assert sentence in drawn.output, sentence


def test_a_trading_accounts_sheet_explains_no_gain_keys(tmp_path):
    """A balance sheet that prints no gain key explains none either.

    A book using trading accounts keeps its gains in its Trading accounts as
    account balances, states them as `trading_gains`, and prints no gain key
    and no `gnucash_balancing_amount` at all. The paragraphs would describe
    figures that are not on the page — and would tell a reader that two of its
    totals differ from GnuCash's when neither does, `total_equity` carrying an
    unrealized total of zero.

    The same fault as putting them on an income statement, one page along, and
    the test beside this one checks the keys are absent without checking that
    the prose about them is.
    """
    book = a_book_using_trading_accounts(tmp_path, THE_CAD_BOOK)

    drawn = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')
    assert drawn.exit_code == 0, drawn.output

    assert key_of(drawn.output, 'trading_gains') == '2303.20 CAD'
    for sentence in GAIN_PROSE:
        assert sentence not in drawn.output, sentence
    assert 'An account line states' in drawn.output, drawn.output


def test_both_statements_keep_the_prose_they_share(tmp_path):
    """Only the gain paragraphs moved; what explains an account line did not."""
    book = _book(tmp_path)
    shared = 'An account line states'

    sheet = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')
    statement = _run(CliRunner(), 'income-statement', str(book),
                     '--start', '2026-01-01', '--end', '2026-12-31')

    assert shared in sheet.output, sheet.output
    assert shared in statement.output, statement.output
