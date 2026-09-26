"""How `report` is asked for a period, and what it refuses.

The command takes its period three ways that cannot be combined, an optional
as-of date for the balance sheet, optional rate and price files, and an
optional output file. Only the fiscal-year form over stdout was covered
(T-009), so every refusal and every alternative was untested — including the
one that decides which dates a whole statement is computed over.

Book (tests/fixtures/closing_book.txt): Sales 1,000.00 in June 2026 and Office
300.00 in July, so Assets 1,000.00 at the end of June and 700.00 at the end of
the year, in GnuCash's own figures.
"""

from pathlib import Path

from click.testing import CliRunner

from cli.main import cli
from tests.integration.text_report_pages import key_of as _key

BOOK = str(Path('tests/fixtures/closing_book.txt'))


def _book(tmp_path):
    gf = tmp_path / 'book.gnucash'
    result = CliRunner().invoke(cli, ['import', '--new', str(gf), BOOK])
    assert result.exit_code == 0, result.output
    return gf


class TestChoosingThePeriod:
    def test_explicit_start_and_end_are_accepted(self, tmp_path):
        gf = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'report', str(gf), 'income-statement',
            '--start', '2026-01-01', '--end', '2026-12-31'])

        assert result.exit_code == 0, result.output
        assert _key(result.output, 'net_income') == '700.00 CAD'

    def test_a_fiscal_year_end_cannot_be_combined_with_a_range(self, tmp_path):
        """Two answers to one question, and the command says so."""
        gf = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'report', str(gf), 'income-statement',
            '--fiscal-year-end', '2026-12-31', '--start', '2026-01-01'])

        assert result.exit_code != 0
        assert 'cannot be combined' in result.output

    def test_no_period_at_all_is_refused_listing_both_spellings(self, tmp_path):
        gf = _book(tmp_path)
        result = CliRunner().invoke(cli, ['report', str(gf), 'income-statement'])

        assert result.exit_code != 0
        assert '--fiscal-year-end' in result.output
        assert '--start' in result.output

    def test_only_one_end_of_a_range_is_not_a_period(self, tmp_path):
        """`--start` without `--end` falls through to the same refusal."""
        gf = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'report', str(gf), 'income-statement', '--start', '2026-01-01'])

        assert result.exit_code != 0
        assert 'Provide a period' in result.output

    def test_a_range_that_runs_backwards_is_refused(self, tmp_path):
        """A period that ends before it starts is a typo, not a period.

        GnuCash draws a statement over an inverted range without complaint —
        every figure comes out zero — so nothing downstream reports it. The
        sibling command refuses it and this one has to as well: these are the
        figures a return is prepared from.
        """
        gf = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'report', str(gf), 'income-statement',
            '--start', '2026-12-31', '--end', '2026-01-01'])

        assert result.exit_code != 0, result.output
        assert 'on or before' in result.output, result.output

    def test_a_date_that_is_not_a_date_says_the_format(self, tmp_path):
        gf = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'report', str(gf), 'income-statement',
            '--fiscal-year-end', '31/12/2026'])

        assert result.exit_code != 0
        assert 'YYYY-MM-DD' in result.output
        assert '31/12/2026' in result.output


class TestTheBalanceSheetDate:
    def test_as_of_overrides_the_period_end(self, tmp_path):
        """The balance sheet is a moment, and it need not be the period's."""
        gf = _book(tmp_path)
        result = CliRunner().invoke(cli, [
            'report', str(gf), 'balance-sheet',
            '--fiscal-year-end', '2026-12-31', '--as-of', '2026-06-30'])

        assert result.exit_code == 0, result.output
        assert _key(result.output, 'total_assets') == '1000.00 CAD'


class TestWritingToAFile:
    def test_the_output_goes_to_the_named_file_and_is_announced(self, tmp_path):
        gf = _book(tmp_path)
        out = tmp_path / 'statements.txt'
        result = CliRunner().invoke(cli, [
            'report', str(gf), 'income-statement', 'balance-sheet',
            '--fiscal-year-end', '2026-12-31', '--output', str(out)])

        assert result.exit_code == 0, result.output
        assert f'Written to {out}' in result.output
        text = out.read_text(encoding='utf-8')
        assert _key(text, 'net_income') == '700.00 CAD'
        assert _key(text, 'total_assets') == '700.00 CAD'
        # Written, not echoed as well.
        assert 'net_income' not in result.output


class TestWhenARatesFileCannotPriceTheReport:
    def test_a_rate_into_another_currency_is_reported_rather_than_traced(self, tmp_path):
        """A rate is a price in the report's currency, CAD here, and this one is in EUR."""
        gf = _book(tmp_path)
        rates = tmp_path / 'rates.yaml'
        rates.write_text('USD/EUR: 0.9\n', encoding='utf-8')

        result = CliRunner().invoke(cli, [
            'report', str(gf), 'income-statement',
            '--fiscal-year-end', '2026-12-31', '--fx-rates', str(rates)])

        assert result.exit_code != 0, result.output
        assert 'Traceback' not in result.output
        assert 'USD/EUR' in result.output and 'CAD' in result.output, result.output


class TestRateFiles:
    """A file that is there and will not parse.

    A file that is *absent* never reaches the command — `click.Path(exists=
    True)` refuses it first — so the handler inside is about the other case:
    a rates file that exists and says something the loader cannot read.
    """

    def test_an_unreadable_rates_file_is_reported_rather_than_traced(self, tmp_path):
        gf = _book(tmp_path)
        rates = tmp_path / 'rates.yaml'
        rates.write_text('this: [is not: a rates file\n')

        result = CliRunner().invoke(cli, [
            'report', str(gf), 'income-statement',
            '--fiscal-year-end', '2026-12-31', '--fx-rates', str(rates)])

        assert result.exit_code != 0
        assert 'Traceback' not in result.output
        assert 'Error' in result.output

    def test_an_unreadable_prices_file_is_reported_rather_than_traced(self, tmp_path):
        gf = _book(tmp_path)
        prices = tmp_path / 'prices.yaml'
        prices.write_text('this: [is not: a prices file\n')

        result = CliRunner().invoke(cli, [
            'report', str(gf), 'balance-sheet',
            '--fiscal-year-end', '2026-12-31', '--prices', str(prices)])

        assert result.exit_code != 0
        assert 'Traceback' not in result.output
        assert 'Error' in result.output
