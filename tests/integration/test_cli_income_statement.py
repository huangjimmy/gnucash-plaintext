"""
Integration tests for the income-statement CLI command.

Uses temp_gnucash_for_close_books fixture (CAD + USD transactions across 2024).
Tests the full CLI path: argument parsing → GnuCash's report → text/HTML output.
The figures are GnuCash's, measured on GnuCash 5.10: 7,200.00 CAD of income and
1,350.00 CAD of expenses, beside 500.00 USD of income and 100.00 USD of
expenses that the book holds no USD price for.
"""

import os

from click.testing import CliRunner

from cli.main import cli
from tests.integration.text_report_pages import figures

FULL_YEAR_ARGS = ["--fiscal-year-end", "2024-12-31"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_cli(*args):
    runner = CliRunner()
    return runner.invoke(cli, ["income-statement"] + list(args))


def _fx_rates_file(tmp_path, content="USD: 1.35\n"):
    p = tmp_path / "rates.yaml"
    p.write_text(content)
    return str(p)


# ---------------------------------------------------------------------------
# Date range validation
# ---------------------------------------------------------------------------

class TestDateRangeValidation:

    def test_no_date_args_fails(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books)
        assert result.exit_code != 0
        assert "date range" in result.output.lower() or "usage" in result.output.lower()

    def test_fiscal_year_end_only(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, "--fiscal-year-end", "2024-12-31")
        assert result.exit_code == 0

    def test_start_end_explicit(self, temp_gnucash_for_close_books):
        result = run_cli(
            temp_gnucash_for_close_books,
            "--start", "2024-01-01",
            "--end", "2024-12-31",
        )
        assert result.exit_code == 0

    def test_fiscal_year_end_plus_start_fails(self, temp_gnucash_for_close_books):
        result = run_cli(
            temp_gnucash_for_close_books,
            "--fiscal-year-end", "2024-12-31",
            "--start", "2024-01-01",
        )
        assert result.exit_code != 0

    def test_only_start_fails(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, "--start", "2024-01-01")
        assert result.exit_code != 0

    def test_start_after_end_fails(self, temp_gnucash_for_close_books):
        result = run_cli(
            temp_gnucash_for_close_books,
            "--start", "2024-12-31",
            "--end", "2024-01-01",
        )
        assert result.exit_code != 0

    def test_invalid_date_format_fails(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, "--fiscal-year-end", "31/12/2024")
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Text output content
# ---------------------------------------------------------------------------

class TestTextOutput:

    def test_contains_revenue_total(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert result.exit_code == 0, result.output
        assert figures(result.output, "Total Revenue") == ["C$7,200.00"]

    def test_contains_expense_total(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert result.exit_code == 0, result.output
        assert figures(result.output, "Total Expenses") == ["C$1,350.00"]

    def test_contains_net_income(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert result.exit_code == 0, result.output
        assert figures(result.output, "Net income for Period") == ["C$5,850.00"]

    def test_a_usd_account_shows_its_balance_beside_its_value(self, temp_gnucash_for_close_books):
        """The book holds no USD price, so GnuCash's report values the USD at nothing."""
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert result.exit_code == 0, result.output
        assert figures(result.output, "Freelance") == ["$500.00", "C$0.00"]

    def test_shows_the_period_in_its_title(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert result.output.splitlines()[0].startswith("Income Statement For Period Covering")

    def test_write_to_file(self, temp_gnucash_for_close_books, tmp_path):
        out_file = str(tmp_path / "report.txt")
        result = run_cli(
            temp_gnucash_for_close_books,
            *FULL_YEAR_ARGS,
            "--output", out_file,
        )
        assert result.exit_code == 0
        assert os.path.exists(out_file)
        with open(out_file, encoding="utf-8") as f:
            content = f.read()
        assert figures(content, "Net income for Period") == ["C$5,850.00"]


# ---------------------------------------------------------------------------
# FX rates integration
# ---------------------------------------------------------------------------

class TestFxRatesIntegration:

    def test_a_rates_file_prices_the_usd_accounts(self, temp_gnucash_for_close_books, tmp_path):
        fx_file = _fx_rates_file(tmp_path)
        result = run_cli(
            temp_gnucash_for_close_books,
            *FULL_YEAR_ARGS,
            "--fx-rates", fx_file,
        )
        assert result.exit_code == 0, result.output
        assert figures(result.output, "Freelance") == ["$500.00", "C$675.00"]
        assert figures(result.output, "Net income for Period") == ["C$6,390.00"]

    def test_a_rate_for_a_currency_gnucash_does_not_know_is_refused(
            self, temp_gnucash_for_close_books, tmp_path):
        fx_file = _fx_rates_file(tmp_path, content="XYZ: 0.172\n")
        result = run_cli(
            temp_gnucash_for_close_books,
            *FULL_YEAR_ARGS,
            "--fx-rates", fx_file,
        )
        assert result.exit_code != 0
        assert "XYZ" in result.output


# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------

class TestHtmlOutput:

    def test_html_requires_output_file(self, temp_gnucash_for_close_books):
        result = run_cli(
            temp_gnucash_for_close_books,
            *FULL_YEAR_ARGS,
            "--output-format", "html",
        )
        assert result.exit_code != 0

    def test_html_output_written(self, temp_gnucash_for_close_books, tmp_path):
        out_file = str(tmp_path / "report.html")
        result = run_cli(
            temp_gnucash_for_close_books,
            *FULL_YEAR_ARGS,
            "--output-format", "html",
            "--output", out_file,
        )
        assert result.exit_code == 0, result.output
        assert os.path.exists(out_file)
        with open(out_file, encoding="utf-8") as f:
            content = f.read()
        assert "<html" in content.lower()
        assert "Income Statement" in content

    def test_html_contains_account_names(self, temp_gnucash_for_close_books, tmp_path):
        out_file = str(tmp_path / "report.html")
        run_cli(
            temp_gnucash_for_close_books,
            *FULL_YEAR_ARGS,
            "--output-format", "html",
            "--output", out_file,
        )
        with open(out_file, encoding="utf-8") as f:
            content = f.read()
        assert "Salary" in content
        assert "Groceries" in content
