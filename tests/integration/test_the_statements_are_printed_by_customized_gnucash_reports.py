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

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import a_book_using_trading_accounts
from tests.integration.text_report_pages import amount_of as _amount
from tests.integration.text_report_pages import book_from as _book
from tests.integration.text_report_pages import directive_of as _directive
from tests.integration.text_report_pages import directives_of as _directives
from tests.integration.text_report_pages import key_of as _key
from tests.integration.text_report_pages import under as _under


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
        assert _key(result.output, 'currency.mnemonic') == 'HKD'
        assert _amount(result.output, 'Assets:HKD Bank') == '14800.00 HKD'
        assert _amount(result.output, 'Assets:USD Bank') == '1500.00 USD'
        assert _under(result.output, 'Assets:USD Bank')['value'] == '11700.00'
        assert _amount(result.output, 'Assets:CAD Bank') == '1900.00 CAD'
        assert _under(result.output, 'Assets:CAD Bank')['value'] == '10830.00'
        assert _key(result.output, 'total_assets') == '37330.00 HKD'
        assert _key(result.output, 'retained_earnings') == '8130.00 HKD'
        assert _key(result.output, 'total_liabilities_and_equity') == '37330.00 HKD'

    def test_the_income_statement_is_in_hkd(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--start', '2026-01-01', '--end', '2026-03-31')

        assert result.exit_code == 0, result.output
        assert _amount(result.output, 'Income:Consulting') == '5000.00 HKD'
        assert _amount(result.output, 'Income:US Consulting') == '500.00 USD'
        assert _under(result.output, 'Income:US Consulting')['value'] == '3900.00'
        assert _amount(result.output, 'Expenses:Canadian Fees') == '100.00 CAD'
        assert _under(result.output, 'Expenses:Canadian Fees')['value'] == '570.00'
        assert _key(result.output, 'total_revenue') == '8900.00 HKD'
        assert _key(result.output, 'total_expenses') == '770.00 HKD'
        assert _key(result.output, 'net_income') == '8130.00 HKD'

    def test_report_writes_a_block_for_each_statement(self, tmp_path):
        """Both statements on one page, each opened by its own directive."""
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'report', str(book), 'income-statement', 'balance-sheet',
                      '--start', '2026-01-01', '--end', '2026-03-31')

        assert result.exit_code == 0, result.output
        assert _directives(result.output) == ['2026-01-01 income-statement',
                                              '2026-03-31 balance-sheet']
        assert '8130.00 HKD' in result.output, result.output
        assert '37330.00 HKD' in result.output, result.output


class TestAFiscalYearThatIsNotTheCalendars:
    """A fiscal year ending anywhere cuts the book's trading wherever it falls.

    Consulting is billed every quarter across 2025 and 2026 and each quarter
    differs, so a year ending 03-31, 04-25 or 06-30 picks up a different four —
    and the 06-30 year catches the share sale on its last day, valued at the
    price nearest that day rather than the year end's.

    A Canadian filer's year rarely ends on 12-31, and a period that lines up
    with the calendar hides every date arithmetic defect there is.
    """

    FIXTURE = 'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'

    def test_a_year_ending_march_31(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--fiscal-year-end', '2026-03-31')

        assert result.exit_code == 0, result.output
        assert _directive(result.output) == '2025-04-01 income-statement'
        assert _key(result.output, 'end') == '2026-03-31'
        # Q1 1,000 + Q2 1,200 + Q3 1,400 + Q4 1,600, and no gain taken yet.
        assert _amount(result.output, 'Income:Consulting') == '5200.00 CAD'
        assert 'Income:Realized Gains' not in result.output, result.output
        assert _key(result.output, 'net_income') == '5150.00 CAD'

    def test_a_year_ending_april_25(self, tmp_path):
        """A year end on no quarter boundary, which the 04-10 bill falls inside."""
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--fiscal-year-end', '2026-04-25')

        assert result.exit_code == 0, result.output
        assert _directive(result.output) == '2025-04-26 income-statement'
        assert _key(result.output, 'end') == '2026-04-25'
        assert _amount(result.output, 'Income:Consulting') == '6100.00 CAD'
        assert _key(result.output, 'net_income') == '6050.00 CAD'

    def test_a_year_ending_june_30_catches_the_sale_on_its_last_day(self, tmp_path):
        """The shares are sold on 06-30, and the gain is valued at the 1.38 nearest that day."""
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--fiscal-year-end', '2026-06-30')

        assert result.exit_code == 0, result.output
        assert _directive(result.output) == '2025-07-01 income-statement'
        assert _amount(result.output, 'Income:Consulting') == '6900.00 CAD'
        assert _amount(result.output, 'Income:Realized Gains') == '480.00 USD'
        assert _under(result.output, 'Income:Realized Gains') == {
            'account.commodity.mnemonic': 'USD',
            'share_price': '1.38',
            'value': '662.40'}
        assert _key(result.output, 'net_income') == '7512.40 CAD'

    def test_an_account_the_period_never_touched_is_left_off(self, tmp_path):
        """The FX sale is in 2026-07 and the interest in 2026-09, so a year ending 03-31 has neither.

        This page's choice, not GnuCash's: with its shipped defaults GnuCash
        prints such an account with a zero figure, and its own page for this
        year shows `Realized FX Gains`, `Realized Gains` and `Interest`
        (measured on 5.10). A line for one states nothing twice — the figure is
        zero, and an empty balance knows no commodity, so a US dollar account
        would read `0.00 CAD`, which is false of the account.
        """
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--fiscal-year-end', '2026-03-31')

        assert result.exit_code == 0, result.output
        assert 'Income:Realized FX Gains' not in result.output, result.output
        assert 'Expenses:Interest' not in result.output, result.output
        assert _amount(result.output, 'Expenses:Fees') == '50.00 CAD'


class TestACadBookOverOneFiscalYear:
    """One CAD book: currency and shares bought against a cost basis and partly sold, business income billed across two years, and a USD loan still owed at the year end.

    GnuCash's reports price at the price nearest in time by default, so at the
    2026 year end the US dollars are at 1.42, the shares at 280.00 USD and a
    Hong Kong dollar at 0.2 CAD.
    """

    FIXTURE = 'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'

    def test_the_balance_sheet_at_the_year_end(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert _under(result.output, 'Assets:AMZN')['value'] == '4771.20'
        assert _under(result.output, 'Assets:USD Bank')['value'] == '10621.60'
        assert _under(result.output, 'Assets:HKD Bank')['value'] == '1100.00'
        assert _amount(result.output, 'Assets:CAD Bank') == '19840.00 CAD'
        assert _amount(result.output, 'Assets:Receivable') == '2200.00 CAD'
        assert _key(result.output, 'total_assets') == '38532.80 CAD'

    def test_what_is_still_owed_on_the_loan_is_a_liability_line(self, tmp_path):
        """1,500.00 USD of the 4,000.00 borrowed was repaid, and the rest is carried at the year-end rate."""
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert _amount(result.output, 'Liabilities:USD Loan') == '2500.00 USD'
        assert _under(result.output, 'Liabilities:USD Loan')['value'] == '3550.00'
        assert _key(result.output, 'total_liabilities') == '3550.00 CAD'
        assert _key(result.output, 'total_liabilities_and_equity') == '38532.80 CAD'

    def test_a_gain_taken_is_income_and_a_gain_on_what_is_held_is_a_key(self, tmp_path):
        """Both kinds of gain on one page, reached by different routes.

        The 480.00 USD taken on the shares and the 240.00 CAD taken on the
        currency are income, so on a balance sheet they are inside
        `retained_earnings` along with the consulting and the fees. What the
        holdings have made since they were bought is held by no account, so it
        is a key of the block.
        """
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert _key(result.output, 'retained_earnings') == '12679.60 CAD'
        assert _key(result.output, 'unrealized_gains') == '2303.20 CAD'

    def test_each_account_states_what_it_holds_and_what_gnucash_made_of_it(self, tmp_path):
        """The plaintext format's own shape: the account, then a split's keys."""
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert '<' not in result.output, result.output
        assert _directive(result.output) == '2026-12-31 balance-sheet'
        assert _key(result.output, 'currency.mnemonic') == 'CAD'
        assert _amount(result.output, 'Assets:USD Bank') == '7480.00 USD'
        assert _under(result.output, 'Assets:USD Bank') == {
            'account.commodity.mnemonic': 'USD',
            'share_price': '1.42',
            'value': '10621.60'}
        assert _amount(result.output, 'Assets:HKD Bank') == '5500.00 HKD'
        assert _under(result.output, 'Assets:HKD Bank') == {
            'account.commodity.mnemonic': 'HKD',
            # The book prices CAD in HKD at 5.0 at the year end, so a Hong Kong
            # dollar is exactly a fifth of a Canadian one.
            'share_price': '0.2',
            'value': '1100.00'}
        # Held in the report's own currency: no price and no value to state.
        assert _under(result.output, 'Assets:CAD Bank') == {}

    def test_the_balance_sheet_as_html_is_gnucash_own_page(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)
        page = tmp_path / 'balance-sheet.html'

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31',
                      '--output-format', 'html', '--output', str(page))

        assert result.exit_code == 0, result.output
        html = page.read_text(encoding='utf-8')
        assert '<table' in html and 'C$38,532.80' in html, html

    def test_the_balance_sheet_as_pdf_carries_gnucash_figures_as_text(self, tmp_path):
        """The PDF is GnuCash's HTML page laid out by WebKit, and its figures can be selected."""
        import pypdf

        from tests.integration.rendered_page import readable

        book = _book(tmp_path, self.FIXTURE)
        page = tmp_path / 'balance-sheet.pdf'

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31',
                      '--output-format', 'pdf', '--output', str(page))

        assert result.exit_code == 0, result.output
        text = ' '.join(readable('\n'.join(
            sheet.extract_text() for sheet in pypdf.PdfReader(str(page)).pages)).split())
        for figure in ('C$38,532.80', 'C$10,621.60', 'C$2,303.20'):
            assert figure in text, text

    def test_the_income_statement_for_the_fiscal_year(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--fiscal-year-end', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert _key(result.output, 'total_revenue') == '9421.60 CAD'
        assert _key(result.output, 'total_expenses') == '292.00 CAD'
        assert _key(result.output, 'net_income') == '9129.60 CAD'

    def test_the_income_statement_states_its_period_and_its_accounts(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--fiscal-year-end', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert '<' not in result.output, result.output
        assert _directive(result.output) == '2026-01-01 income-statement'
        assert _key(result.output, 'end') == '2026-12-31'
        assert _amount(result.output, 'Income:Consulting') == '8500.00 CAD'
        assert _amount(result.output, 'Income:Realized FX Gains') == '240.00 CAD'
        assert _amount(result.output, 'Income:Realized Gains') == '480.00 USD'
        assert _under(result.output, 'Income:Realized Gains') == {
            'account.commodity.mnemonic': 'USD',
            'share_price': '1.42',
            'value': '681.60'}
        assert _amount(result.output, 'Expenses:Fees') == '150.00 CAD'
        assert _amount(result.output, 'Expenses:Interest') == '100.00 USD'
        assert _under(result.output, 'Expenses:Interest')['value'] == '142.00'

    def test_a_currency_given_on_the_command_is_the_report_currency(self, tmp_path):
        """`--currency USD` on the CAD book: the statement is printed in USD.

        The prices are the book's own read the other way round: it holds USD in
        CAD at 1.42, so a Canadian dollar is 50/71 of a US one, and a Hong Kong
        dollar — a fifth of a Canadian — is 10/71.
        """
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31',
                      '--currency', 'USD')

        assert result.exit_code == 0, result.output
        assert _key(result.output, 'currency.mnemonic') == 'USD'
        assert _under(result.output, 'Assets:CAD Bank') == {
            'account.commodity.mnemonic': 'CAD',
            'share_price': '50/71',
            'value': '13971.83'}
        assert _under(result.output, 'Assets:HKD Bank') == {
            'account.commodity.mnemonic': 'HKD',
            'share_price': '10/71',
            'value': '774.65'}
        # Held in the report's currency now, so it states neither.
        assert _under(result.output, 'Assets:USD Bank') == {}
        assert _key(result.output, 'total_assets') == '27135.78 USD'


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
        assert _amount(result.output, 'Liabilities:USD Loan') == '1000.00 USD'
        assert _under(result.output, 'Liabilities:USD Loan')['value'] == '1400.00'
        assert _key(result.output, 'total_liabilities') == '1400.00 CAD'
        # One key whatever the sign, where GnuCash's page switches between
        # `Unrealized Gains` and `Unrealized Losses`.
        assert _key(result.output, 'unrealized_gains') == '-100.00 CAD'

    def test_the_sheet_balances_against_what_the_loan_put_in_the_bank(self, tmp_path):
        """A sign error in the liability term would show here and nowhere else."""
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-25')

        assert result.exit_code == 0, result.output
        assert _key(result.output, 'total_assets') == '1300.00 CAD'
        assert _key(result.output, 'total_liabilities_and_equity') == '1300.00 CAD'

    def test_on_the_day_it_was_drawn_nothing_is_unrealized(self, tmp_path):
        """Cost and value are the same figure that day, so the term is zero — and says so.

        The key states `0.00` rather than dropping off. The book holds the
        money either way; what a zero says is that none of it has moved yet,
        which is a different thing from the book having no such money at all.
        """
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-03')

        assert result.exit_code == 0, result.output
        assert _amount(result.output, 'Liabilities:USD Loan') == '1000.00 USD'
        assert _under(result.output, 'Liabilities:USD Loan')['value'] == '1300.00'
        assert _key(result.output, 'unrealized_gains') == '0.00 CAD'
        assert _key(result.output, 'total_liabilities_and_equity') == '1300.00 CAD'


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
        assert _key(result.output, 'total_liabilities_and_equity') == '0.00 CAD'


class TestABookUsingTradingAccounts:
    """The CAD book of the tests above, in a book whose "Use Trading Accounts" option is on.

    GnuCash's shipped Balance Sheet then prints the shares' gain as Trading
    Gains rather than as Unrealized Gains
    (`what_the_balance_sheet_prints_for_a_book_using_trading_accounts_probe.py`).
    """

    LEDGER = 'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'

    def test_the_balance_sheet_prints_trading_gains(self, tmp_path):
        """The same money the other book states as `unrealized_gains`, and only one of the two keys.

        GnuCash books the revaluation into Trading accounts as each transaction
        happens, so what the holdings have made is an account balance here
        rather than a figure the report derives.
        """
        book = a_book_using_trading_accounts(tmp_path, self.LEDGER)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert _key(result.output, 'trading_gains') == '2303.20 CAD'
        assert 'unrealized_gains' not in result.output, result.output
        assert _key(result.output, 'retained_earnings') == '12679.60 CAD'
        assert _key(result.output, 'total_liabilities_and_equity') == '38532.80 CAD'


class TestAWarningWhileTheReportIsDrawn:
    """The book's `date_format` is `%d %B %Y`, which GnuCash has no date style for."""

    def test_the_warning_is_given_and_the_page_is_still_printed(self, tmp_path):
        book = _book(tmp_path, 'a_cad_book_whose_company_writes_dates_as_day_month_year.txt',
                     '--include-business-objects')

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-01-31')

        assert result.exit_code == 0, result.output
        assert '⚠' in result.output and '%d %B %Y' in result.output, result.output
        assert _key(result.output, 'total_assets') == '500.00 CAD'

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
        assert _key(result.output, 'total_revenue') == '100.00 CAD'
        assert _key(result.output, 'total_expenses') == '300.00 CAD'
        # A loss is the same key with a negative figure, where GnuCash's page
        # changes the label to `Net loss for Period`.
        assert _key(result.output, 'net_income') == '-200.00 CAD'

    def test_the_balance_sheet_prints_retained_losses(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert _key(result.output, 'total_assets') == '800.00 CAD'
        assert _key(result.output, 'retained_earnings') == '-200.00 CAD'
        assert _key(result.output, 'total_liabilities_and_equity') == '800.00 CAD'


class TestABookWithNoAccounts:
    """A `company` block and nothing else, reported in a currency given on the command."""

    FIXTURE = 'a_company_with_no_accounts.txt'

    def test_the_balance_sheet_says_no_accounts_are_selected(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE, '--include-business-objects')

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-03-31',
                      '--currency', 'CAD')

        assert result.exit_code == 0, result.output
        assert _key(result.output, 'accounts') == 'none selected'

    def test_the_income_statement_says_no_accounts_are_selected(self, tmp_path):
        book = _book(tmp_path, self.FIXTURE, '--include-business-objects')

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--start', '2026-01-01', '--end', '2026-03-31', '--currency', 'CAD')

        assert result.exit_code == 0, result.output
        assert _key(result.output, 'accounts') == 'none selected'
