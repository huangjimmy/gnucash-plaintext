"""What a statement block states beyond its figures: every account, and what its keys mean.

Three things a reader of a block depends on, none of which the figures alone
would catch:

- **Every account is listed, however deep.** GnuCash's statements default
  `Accounts / Levels of Subaccounts` to 3 and fold anything deeper into its
  parent — measured on 5.10, a book whose `Assets:Bank:Chequing` holds 300.00
  CAD with 700.00 in `Assets:Bank:Chequing:Payroll` prints one row, `Chequing
  C$1,000.00`, and no `Payroll` row at all. On a column page that is a reading
  convenience. In a block it is an account that does not appear, beside a line
  stating its child's money as its own, which every other line here promises it
  never does.
- **The income statement has no trading section.** GnuCash's own selects income
  and expense accounts and nothing else, so trading accounts never reach it
  even for a book that uses them; their gains reach the reader through the
  balance sheet's `trading_gains` key instead.
- **The block says what its keys mean**, in comment lines the report writes, so
  a reader meeting `share_price:` on an account line is told it is a valuation
  on that date rather than the rate of any transaction.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import (
    a_book_using_trading_accounts,
    amount_of,
    book_from,
    key_of,
    under,
)

FOUR_DEEP = 'a_cad_book_whose_accounts_run_four_levels_deep.txt'
THE_CAD_BOOK = 'a_cad_book_with_usd_hkd_and_shares_priced_in_its_price_database.txt'


class TestEveryAccountIsListedHoweverDeep:

    def test_the_fourth_level_is_a_line_of_its_own(self, tmp_path):
        """And the third level states only its own 300.00, not the 1,050.00 under it."""
        book = book_from(tmp_path, FOUR_DEEP)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert amount_of(result.output, 'Assets:Bank:Chequing') == '300.00 CAD'
        assert amount_of(result.output, 'Assets:Bank:Chequing:Payroll') == '750.00 CAD'
        assert key_of(result.output, 'total_assets') == '1050.00 CAD'

    def test_an_income_account_three_levels_down_is_listed(self, tmp_path):
        book = book_from(tmp_path, FOUR_DEEP)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--fiscal-year-end', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert amount_of(result.output, 'Income:Fees:Late') == '50.00 CAD'
        assert key_of(result.output, 'total_revenue') == '50.00 CAD'


class TestABookUsingTradingAccounts:
    """The trading gains are on the balance sheet, and the income statement has no trading section."""

    def test_the_income_statement_states_no_trading_section(self, tmp_path):
        book = a_book_using_trading_accounts(tmp_path, THE_CAD_BOOK)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--fiscal-year-end', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert 'total_trading' not in result.output, result.output
        assert 'Trading' not in result.output, result.output
        assert key_of(result.output, 'total_revenue') == '9421.60 CAD'

    def test_the_balance_sheet_states_the_trading_gains(self, tmp_path):
        book = a_book_using_trading_accounts(tmp_path, THE_CAD_BOOK)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert key_of(result.output, 'trading_gains') == '2303.20 CAD'
        assert key_of(result.output, 'total_equity') == '34982.80 CAD'


class TestMoneyTheBookCannotPrice:
    """A key states its figure even where the money behind it converts to nothing.

    GnuCash values what it cannot price at nothing, so a CAD book earning only
    in US dollars it holds no price for has retained earnings of 0.00 CAD. The
    book plainly has those earnings — 500.00 USD against 100.00 USD of fees —
    and an account line says so, stating what it holds beside `value: "0.00"`.
    A key that vanished at zero would tell a reader the book had no such
    earnings at all, which is a different claim and a false one.
    """

    FIXTURE = 'a_cad_book_earning_only_in_a_currency_it_has_no_price_for.txt'

    def test_the_retained_earnings_key_is_still_stated(self, tmp_path):
        book = book_from(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert key_of(result.output, 'retained_earnings') == '0.00 CAD'
        assert key_of(result.output, 'total_assets') == '0.00 CAD'

    def test_the_account_lines_show_the_money_valued_at_nothing(self, tmp_path):
        """What it holds, and no price — a `share_price:` of zero would be a claim the book does not make."""
        book = book_from(tmp_path, self.FIXTURE)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--fiscal-year-end', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert amount_of(result.output, 'Income:Consulting') == '500.00 USD'
        assert under(result.output, 'Income:Consulting') == {
            'account.commodity.mnemonic': 'USD',
            'value': '0.00'}
        assert key_of(result.output, 'total_revenue') == '0.00 CAD'
        assert key_of(result.output, 'net_income') == '0.00 CAD'


class TestTheBlockSaysWhatItsKeysMean:

    def _comments(self, page):
        return [line for line in page.splitlines() if line.lstrip().startswith('#')]

    def test_the_block_opens_with_comment_lines(self, tmp_path):
        book = book_from(tmp_path, FOUR_DEEP)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines[0] == '2026-12-31 balance-sheet'
        # Straight after the directive, before any key or account line.
        assert lines[1].lstrip().startswith('#'), lines[:3]
        assert len(self._comments(result.output)) > 5, result.output

    def test_every_comment_line_is_indented_inside_the_block(self, tmp_path):
        """One tab, like the block's own keys: at column 0 it would read as a directive."""
        book = book_from(tmp_path, FOUR_DEEP)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        for line in self._comments(result.output):
            assert line.startswith('\t#'), repr(line)

    def test_they_say_what_share_price_and_value_mean_here(self, tmp_path):
        """The distinction a reader cannot get from the keys themselves."""
        book = book_from(tmp_path, FOUR_DEEP)

        result = _run(CliRunner(), 'income-statement', str(book),
                      '--fiscal-year-end', '2026-12-31')

        assert result.exit_code == 0, result.output
        said = ' '.join(line.lstrip('\t# ') for line in self._comments(result.output))
        assert 'not the keys of the same name on a transaction split' in said, said
        assert 'price database' in said, said
        # An em dash, written as one character rather than mangled.
        assert '—' in said, said

    def test_the_keys_and_account_lines_read_the_same_with_them_there(self, tmp_path):
        """A comment opens a line, so nothing that reads the block picks one up."""
        book = book_from(tmp_path, FOUR_DEEP)

        result = _run(CliRunner(), 'balance-sheet', str(book), '--as-of', '2026-12-31')

        assert result.exit_code == 0, result.output
        assert key_of(result.output, 'currency.mnemonic') == 'CAD'
        assert amount_of(result.output, 'Assets:Bank:Chequing') == '300.00 CAD'
