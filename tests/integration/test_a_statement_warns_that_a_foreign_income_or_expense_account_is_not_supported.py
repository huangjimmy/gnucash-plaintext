"""An income or expense account kept in another currency is warned about on the page.

gnucash-plaintext does not support one, and says so on the statement rather
than refusing to draw it. An expense is what it cost on the day it was
incurred, and the account's balance is a sum of amounts from many days, each of
those days having had a rate of its own. No one rate turns that sum into the
book's own currency, so both statements convert it at the report date's rate:
the expense is stated at a rate it was never incurred at, and a page drawn a
month later states it differently.

The page is still drawn, because every other figure on it is right and because
it carries what a reader needs to work the expense out: the account line states
what the account holds in its own currency and the rate the page converted it
at.

`tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt`
keeps `Expenses:Interest` in US dollars, which is the account these tests read.
"""

from click.testing import CliRunner

from cli.main import cli
from tests.conftest import _run
from tests.integration.text_report_pages import book_from

IN_US_DOLLARS = 'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'
ALL_IN_CANADIAN_DOLLARS = 'a_broker_fee_two_us_loans_and_part_of_the_shares_sold.txt'


def _sheet(book, *flags):
    drawn = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31',
                 '--no-itemize', *flags)
    assert drawn.exit_code == 0, drawn.output
    return drawn.output


class TestTheWarningTheBalanceSheetCarries:
    def test_the_page_is_drawn_rather_than_refused(self, tmp_path):
        """Every other figure on it is right, so refusing would withhold them."""
        page = _sheet(book_from(tmp_path, IN_US_DOLLARS))

        assert '\ttotal_assets: 38532.80 CAD' in page, page
        assert '\ttotal_liabilities_and_equity: 38532.80 CAD' in page, page

    def test_it_lists_the_account_and_the_currency_it_is_kept_in(self, tmp_path):
        page = _sheet(book_from(tmp_path, IN_US_DOLLARS))

        assert 'WARNING' in page, page
        assert '# These income and expense accounts are not kept in CAD:' in page, page
        assert '#   Expenses:Interest — USD' in page, page

    def test_it_says_gnucash_plaintext_does_not_support_one(self, tmp_path):
        page = _sheet(book_from(tmp_path, IN_US_DOLLARS))

        assert '# gnucash-plaintext does not support that, and every figure on this' in page
        assert '# page those accounts reach can be wrong.' in page, page

    def test_it_says_why_no_one_rate_converts_the_balance(self, tmp_path):
        page = _sheet(book_from(tmp_path, IN_US_DOLLARS))

        assert '# those days had a rate of its own. No one rate turns that sum' in page
        assert '# into CAD. This page converts it at the rate of its own date,' in page

    def test_it_says_the_reader_can_work_the_figure_out_from_the_line(self, tmp_path):
        """Which is what the account line beneath it carries: the holding and the rate."""
        page = _sheet(book_from(tmp_path, IN_US_DOLLARS))

        assert '# knows what each amount cost on its own day can work the right' in page

    def test_a_book_keeping_them_all_in_its_own_currency_is_not_warned(self, tmp_path):
        book = book_from(tmp_path, ALL_IN_CANADIAN_DOLLARS)
        drawn = _run(CliRunner(), 'balance-sheet', str(book),
                     '--as-of', '2028-12-31', '--no-itemize')
        assert drawn.exit_code == 0, drawn.output

        assert 'WARNING' not in drawn.output, drawn.output

    def test_a_page_drawn_in_another_currency_says_to_draw_it_in_the_books_own(self, tmp_path):
        """The accounts are kept right, and it is the page's currency that converts them.

        Every income and expense account of this book is in Canadian dollars,
        its own currency. Drawn in US dollars, the page listed every one of
        them as "not kept in USD" and told the reader to keep them in US
        dollars — advice that is wrong for a Canadian book. What is true is
        that a page in US dollars converts them at its own date's rate, and the
        advice for that is to draw the page in Canadian dollars.
        """
        book = book_from(tmp_path, ALL_IN_CANADIAN_DOLLARS)
        for command, dated in (('balance-sheet', ['--as-of', '2028-12-31', '--no-itemize']),
                               ('income-statement', ['--start', '2028-01-01',
                                                     '--end', '2028-12-31'])):
            drawn = _run(CliRunner(), command, str(book), '--currency', 'USD', *dated)
            assert drawn.exit_code == 0, drawn.output

            assert 'not kept in' not in drawn.output, drawn.output
            assert '# This page is drawn in USD, and the book is kept in CAD.' \
                in drawn.output, drawn.output
            assert '# Draw the page in CAD for those figures to be right.' \
                in drawn.output, drawn.output


class TestTheWarningTheIncomeStatementCarries:
    def _statement(self, book):
        drawn = _run(CliRunner(), 'income-statement', str(book),
                     '--start', '2026-01-01', '--end', '2026-12-31')
        assert drawn.exit_code == 0, drawn.output
        return drawn.output

    def test_the_same_accounts_are_listed(self, tmp_path):
        """The page the error reaches most directly: the expense is a line of it."""
        page = self._statement(book_from(tmp_path, IN_US_DOLLARS))

        assert '#   Expenses:Interest — USD' in page, page

    def test_the_account_line_states_the_holding_and_the_rate(self, tmp_path):
        """100.00 USD at the sheet's 1.42, which is the 142.00 the warning is about.

        The dollars that paid the interest cost 1.30, so the expense was 130.00
        CAD on the day. A reader with the warning and these three lines can
        work that out; the page cannot, because nothing in the book says which
        day each amount of the balance belongs to once they are summed.
        """
        page = self._statement(book_from(tmp_path, IN_US_DOLLARS))

        assert '\tExpenses:Interest 100.00 USD' in page, page
        assert '\t\tshare_price: "1.42"' in page, page
        assert '\t\tvalue: "142.00"' in page, page


class TestWhatVerifyIntegritySays:
    def test_it_reports_the_account_and_exits_one(self, tmp_path):
        book = book_from(tmp_path, IN_US_DOLLARS)

        checked = CliRunner().invoke(cli, ['--verify-integrity', str(book)])

        assert checked.exit_code == 1, checked.output
        assert 'Expenses:Interest (USD)' in checked.output, checked.output
        assert ("checked: every income and expense account is kept in the "
                "book's own currency") in checked.output, checked.output

    def test_a_book_keeping_them_all_in_its_own_currency_passes(self, tmp_path):
        book = book_from(tmp_path, ALL_IN_CANADIAN_DOLLARS)

        checked = CliRunner().invoke(cli, ['--verify-integrity', str(book)])

        assert checked.exit_code == 0, checked.output
        assert 'The book is consistent and balanced.' in checked.output, checked.output
