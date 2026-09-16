"""`balance-sheet`, `income-statement` and `report` print the statements through customized GnuCash reports, in the book's currency.

Q-042: the plaintext page is printed by the customized GnuCash reports in
`infrastructure/gnucash/reports/balance-sheet-and-income-statement-as-text.scm`, so every figure is
added up by GnuCash and converted through the book's price database by GnuCash;
gnucash-plaintext calculates none of them. The statements are in the currency
the book is kept in (`test_the_currency_a_book_is_kept_in.py`), which is not
taken to be CAD. `--output-format html` is GnuCash's report as GnuCash ships it.

Every expected figure below is the one GnuCash's Balance Sheet and Income
Statement reports give for the same book.
"""

from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import book_from as _book
from tests.integration.text_report_pages import figures as _figures


class TestABookKeptInHkd:
    """Top-level accounts in HKD, beneath them HKD, USD and CAD, and no `company` block.

    The reports are in HK$. The book prices USD at 7.80 HKD and CAD at 5.70 HKD,
    and GnuCash's report converts the USD and the CAD by those prices, showing
    each foreign balance beside its value in HK$.
    """

    FIXTURE = 'a_book_kept_in_hkd.txt'

    def test_the_balance_sheet_is_in_hkd(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-03-31')

        assert result.exit_code == 0, result.output
        assert _figures(result.output, 'HKD Bank') == ['HK$14,800.00']
        assert _figures(result.output, 'USD Bank') == ['$1,500.00', 'HK$11,700.00']
        assert _figures(result.output, 'CAD Bank') == ['C$1,900.00', 'HK$10,830.00']
        assert _figures(result.output, 'Total Assets') == ['HK$37,330.00']
        assert _figures(result.output, 'Retained Earnings') == ['HK$8,130.00']
        assert _figures(result.output, 'Total Liabilities & Equity') == ['HK$37,330.00']

    def test_the_income_statement_is_in_hkd(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--start', '2026-01-01', '--end', '2026-03-31')

        assert result.exit_code == 0, result.output
        assert _figures(result.output, 'Consulting') == ['HK$5,000.00']
        assert _figures(result.output, 'US Consulting') == ['$500.00', 'HK$3,900.00']
        assert _figures(result.output, 'Canadian Fees') == ['C$100.00', 'HK$570.00']
        assert _figures(result.output, 'Total Revenue') == ['HK$8,900.00']
        assert _figures(result.output, 'Total Expenses') == ['HK$770.00']
        assert _figures(result.output, 'Net income for Period') == ['HK$8,130.00']

    def test_report_gives_both_in_hkd(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'report', str(book), 'income-statement', 'balance-sheet',
                      '--start', '2026-01-01', '--end', '2026-03-31')

        assert result.exit_code == 0, result.output
        assert _figures(result.output, 'Net income for Period') == ['HK$8,130.00']
        assert _figures(result.output, 'USD Bank') == ['$1,500.00', 'HK$11,700.00']
        assert _figures(result.output, 'Total Assets') == ['HK$37,330.00']


class TestACadBookHoldingOtherCurrenciesAndShares:
    """USD, HKD and NASDAQ:AMZN in a CAD book, converted by GnuCash through the book's prices.

    GnuCash's reports price at the price nearest in time by default, so as of
    2026-01-25 the USD is at the 02-02 rate of 1.40, and the shares at 210 USD.
    """

    FIXTURE = 'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'

    def test_the_balance_sheet_as_of_january_25(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25')

        assert result.exit_code == 0, result.output
        for figure in ('C$2,940.00',     # 10 AMZN at 210 USD, at 1.40
                       'C$2,100.00',     # 1,500.00 USD at 1.40
                       'C$1,000.00',     # 5,500.00 HKD at 5.5 HKD a CAD
                       'C$900.00',
                       'C$6,940.00',     # total assets
                       'C$600.00',       # retained earnings
                       'C$140.00'):      # unrealized gains on the shares
            assert figure in result.output, result.output

    def test_the_balance_sheet_is_plain_text_with_each_figure_on_its_line(self, tmp_path):
        """A foreign balance beside its value in CAD, and every total on its label's line."""
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25')

        assert result.exit_code == 0, result.output
        assert '<' not in result.output, result.output
        assert _figures(result.output, 'USD Bank') == ['$1,500.00', 'C$2,100.00']
        assert _figures(result.output, 'HKD Bank') == ['HK$5,500.00', 'C$1,000.00']
        assert _figures(result.output, 'CAD Bank') == ['C$900.00']
        assert _figures(result.output, 'Total Assets') == ['C$6,940.00']
        assert _figures(result.output, 'Retained Earnings') == ['C$600.00']
        assert _figures(result.output, 'Unrealized Gains') == ['C$140.00']

    def test_the_balance_sheet_as_html_is_gnucash_own_page(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)
        page = tmp_path / 'balance-sheet.html'

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25',
                      '--output-format', 'html', '--output', str(page))

        assert result.exit_code == 0, result.output
        html = page.read_text(encoding='utf-8')
        assert '<table' in html and 'C$6,940.00' in html, html

    def test_the_balance_sheet_as_pdf_carries_gnucash_figures_as_text(self, tmp_path):
        """The PDF is GnuCash's HTML page laid out by WebKit, and its figures can be selected."""
        import pypdf

        from tests.integration.rendered_page import readable

        book = _book(tmp_path, self.FIXTURE)
        page = tmp_path / 'balance-sheet.pdf'

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25',
                      '--output-format', 'pdf', '--output', str(page))

        assert result.exit_code == 0, result.output
        text = ' '.join(readable('\n'.join(
            sheet.extract_text() for sheet in pypdf.PdfReader(str(page)).pages)).split())
        for figure in ('C$6,940.00', 'C$2,100.00', 'C$140.00'):
            assert figure in text, text

    def test_the_balance_sheet_as_of_march_1(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-03-01')

        assert result.exit_code == 0, result.output
        for figure in ('C$3,080.00', 'C$7,080.00', 'C$280.00'):
            assert figure in result.output, result.output

    def test_the_income_statement(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--start', '2026-01-01', '--end', '2026-01-25')

        assert result.exit_code == 0, result.output
        for figure in ('C$700.00', 'C$100.00', 'C$600.00'):
            assert figure in result.output, result.output

    def test_the_income_statement_is_plain_text_with_each_total_on_its_line(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--start', '2026-01-01', '--end', '2026-01-25')

        assert result.exit_code == 0, result.output
        assert '<' not in result.output, result.output
        assert _figures(result.output, 'Total Revenue') == ['C$700.00']
        assert _figures(result.output, 'Total Expenses') == ['C$100.00']
        assert _figures(result.output, 'Net income for Period') == ['C$600.00']

    def test_a_currency_given_on_the_command_is_the_report_currency(self, tmp_path):
        """`--currency USD` on the CAD book: the statement is printed in USD."""
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25',
                      '--currency', 'USD')

        assert result.exit_code == 0, result.output
        for figure in ('$642.86',        # 900.00 CAD at 1.40
                       '$714.29',        # 5,500.00 HKD at 5.5 HKD a CAD, then 1.40
                       '$4,957.15'):     # total assets
            assert figure in result.output, result.output


class TestABookOwingForeignCurrency:
    """A CAD book owing 1,000.00 USD it borrowed with Canadian dollars.

    The liability side of a balance sheet's unrealized gains, which no other
    book here reaches: every other fixture holds assets alone, and a loan whose
    two splits are both in US dollars states no CAD figure, so what it cost and
    what it is worth are one number and the liability terms cancel.

    Borrowed with CAD they do not. The book carries the loan at the 1.30 it was
    drawn at; by 2026-01-25 GnuCash's nearest price is the 02-02 rate of 1.40,
    so the debt is worth C$1,400.00 against C$1,300.00 of assets and the book
    owes 100.00 CAD more than it borrowed.
    """

    FIXTURE = 'a_cad_book_owing_usd_it_borrowed_with_cad.txt'

    def test_what_the_loan_has_cost_so_far_is_an_unrealized_loss(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25')

        assert result.exit_code == 0, result.output
        assert _figures(result.output, 'USD Loan') == ['$1,000.00', 'C$1,400.00']
        assert _figures(result.output, 'Total Liabilities') == ['C$1,400.00']
        assert _figures(result.output, 'Unrealized Losses') == ['C$100.00']
        assert _figures(result.output, 'Total Equity') == ['-C$100.00']

    def test_the_sheet_balances_against_what_the_loan_put_in_the_bank(self, tmp_path):
        """A sign error in the liability term would show here and nowhere else."""
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25')

        assert result.exit_code == 0, result.output
        assert _figures(result.output, 'Total Assets') == ['C$1,300.00']
        assert _figures(result.output, 'Total Liabilities & Equity') == ['C$1,300.00']

    def test_on_the_day_it_was_drawn_nothing_is_unrealized(self, tmp_path):
        """Cost and value are the same figure that day, so the term is zero."""
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-03')

        assert result.exit_code == 0, result.output
        assert _figures(result.output, 'USD Loan') == ['$1,000.00', 'C$1,300.00']
        assert _figures(result.output, 'Unrealized Gains') == ['C$0.00']
        assert _figures(result.output, 'Total Liabilities & Equity') == ['C$1,300.00']


class TestABookWhoseCurrencyIsNotKnown:
    """Top-level accounts in CAD and USD, and no `base_currency:`."""

    FIXTURE = 'a_book_whose_top_level_accounts_are_in_two_currencies.txt'

    def test_the_balance_sheet_is_refused_and_says_how_to_state_the_currency(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-03-31')

        assert result.exit_code != 0, result.output
        assert '--currency' in result.output and 'base_currency' in result.output, result.output

    def test_the_income_statement_is_refused_too(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--start', '2026-01-01', '--end', '2026-03-31')

        assert result.exit_code != 0, result.output
        assert '--currency' in result.output, result.output

    def test_a_currency_given_on_the_command_lets_it_run(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-03-31',
                      '--currency', 'CAD')

        assert result.exit_code == 0, result.output
        assert 'C$0.00' in result.output, result.output


class TestABookUsingTradingAccounts:
    """The CAD book of the tests above, in a book whose "Use Trading Accounts" option is on.

    A GnuCash user turns it on in File → Properties → Accounts, and GnuCash then
    records each multi-currency transaction with trading splits. Nothing in
    gnucash-plaintext sets it, so the book is made the way GnuCash keeps it: the
    option set on a new book, then the ledger imported. GnuCash's shipped Balance
    Sheet then prints the shares' gain as Trading Gains rather than as Unrealized
    Gains (`what_the_balance_sheet_prints_for_a_book_using_trading_accounts_probe.py`).
    """

    def _book(self, tmp_path):
        from gnucash import ACCT_TYPE_BANK, Account

        from infrastructure.gnucash.kvp import write_book_string_option
        from repositories.gnucash_repository import GnuCashRepository, SessionMode

        book = tmp_path / 'trading.gnucash'
        repo = GnuCashRepository(str(book))
        repo.open(SessionMode.NEW)
        try:
            write_book_string_option(repo.book, 'Accounts', 'Use Trading Accounts', 't')
            # A new book holding nothing but a book option writes no file when
            # saved, so it is given a top-level CAD account, which keeps the
            # book kept in CAD.
            petty_cash = Account(repo.book)
            petty_cash.BeginEdit()
            petty_cash.SetName('Petty Cash')
            petty_cash.SetType(ACCT_TYPE_BANK)
            petty_cash.SetCommodity(repo.book.get_table().lookup('CURRENCY', 'CAD'))
            repo.book.get_root_account().append_child(petty_cash)
            petty_cash.CommitEdit()
            repo.save()
        finally:
            repo.close()
        imported = _run(CliRunner(), 'import', str(book), str(
            Path('tests/fixtures/a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt')))
        assert imported.exit_code == 0, imported.output
        return book

    def test_the_balance_sheet_prints_trading_gains(self, tmp_path):
        book = self._book(tmp_path)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25')

        assert result.exit_code == 0, result.output
        assert _figures(result.output, 'Trading Gains') == ['C$140.00']
        assert 'Unrealized Gains' not in result.output, result.output
        assert _figures(result.output, 'Total Equity') == ['C$6,940.00']
        assert _figures(result.output, 'Total Liabilities & Equity') == ['C$6,940.00']


class TestAWarningWhileTheReportIsDrawn:
    """The book's `date_format` is `%d %B %Y`, which GnuCash has no date style for."""

    def test_the_warning_is_given_and_the_page_is_still_printed(self, tmp_path):
        book = _book(tmp_path, 'a_cad_book_whose_company_writes_dates_as_day_month_year.txt',
                     '--include-business-objects')

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-31')

        assert result.exit_code == 0, result.output
        assert '⚠' in result.output and '%d %B %Y' in result.output, result.output
        assert _figures(result.output, 'Total Assets') == ['C$500.00']

    def test_it_is_given_once_however_many_statements_one_run_draws(self, tmp_path):
        """`report` renders each statement in the one process, and the book's
        date format is a property of the book rather than of a page."""
        book = _book(tmp_path, 'a_cad_book_whose_company_writes_dates_as_day_month_year.txt',
                     '--include-business-objects')

        result = _run(CliRunner(), 'report', str(book), 'income-statement', 'balance-sheet',
                      '--start', '2026-01-01', '--end', '2026-01-31')

        assert result.exit_code == 0, result.output
        assert result.output.count('%d %B %Y') == 1, result.output


class TestABookRunningALoss:
    """Expenses of 300.00 CAD against income of 100.00 CAD in 2026."""

    FIXTURE = 'a_cad_book_whose_expenses_exceed_its_income.txt'

    def test_the_income_statement_prints_a_net_loss(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--start', '2026-01-01', '--end', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert _figures(result.output, 'Total Revenue') == ['C$100.00']
        assert _figures(result.output, 'Total Expenses') == ['C$300.00']
        assert _figures(result.output, 'Net loss for Period') == ['C$200.00']

    def test_the_balance_sheet_prints_retained_losses(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert _figures(result.output, 'Total Assets') == ['C$800.00']
        assert _figures(result.output, 'Retained Losses') == ['C$200.00']
        assert _figures(result.output, 'Total Equity') == ['C$800.00']


class TestABookWithNoAccounts:
    """A `company` block and nothing else, reported in a currency given on the command."""

    FIXTURE = 'a_company_with_no_accounts.txt'

    def test_the_balance_sheet_says_no_accounts_are_selected(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE, '--include-business-objects')

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-03-31',
                      '--currency', 'CAD')

        assert result.exit_code == 0, result.output
        assert 'No accounts selected' in result.output, result.output

    def test_the_income_statement_says_no_accounts_are_selected(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE, '--include-business-objects')

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--start', '2026-01-01', '--end', '2026-03-31', '--currency', 'CAD')

        assert result.exit_code == 0, result.output
        assert 'No accounts selected' in result.output, result.output
