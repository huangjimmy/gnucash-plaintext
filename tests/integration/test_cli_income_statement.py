"""
Integration tests for the income-statement CLI command.

Uses temp_gnucash_for_close_books fixture (CAD + USD transactions across 2024).
Tests the full CLI path: argument parsing → use case → text/HTML rendering.
"""

import os
import tempfile

import pytest
from click.testing import CliRunner

from cli.main import cli

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

    def test_contains_income_section(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert result.exit_code == 0
        assert "INCOME" in result.output

    def test_contains_expenses_section(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert result.exit_code == 0
        assert "EXPENSES" in result.output

    def test_contains_net_income(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert result.exit_code == 0
        assert "NET INCOME" in result.output

    def test_shows_cad_amounts(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert "CAD" in result.output

    def test_shows_usd_amounts(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert "USD" in result.output

    def test_shows_fiscal_period_in_output(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert "2024-01-01" in result.output
        assert "2024-12-31" in result.output

    def test_no_fx_warning_shown_without_fx_rates(self, temp_gnucash_for_close_books):
        result = run_cli(temp_gnucash_for_close_books, *FULL_YEAR_ARGS)
        assert "No FX rates" in result.output or "fx-rates" in result.output.lower()

    def test_write_to_file(self, temp_gnucash_for_close_books, tmp_path):
        out_file = str(tmp_path / "report.txt")
        result = run_cli(
            temp_gnucash_for_close_books,
            *FULL_YEAR_ARGS,
            "--output", out_file,
        )
        assert result.exit_code == 0
        assert os.path.exists(out_file)
        with open(out_file) as f:
            content = f.read()
        assert "INCOME" in content


# ---------------------------------------------------------------------------
# FX rates integration
# ---------------------------------------------------------------------------

class TestFxRatesIntegration:

    def test_with_fx_rates_no_warning(self, temp_gnucash_for_close_books, tmp_path):
        fx_file = _fx_rates_file(tmp_path)
        result = run_cli(
            temp_gnucash_for_close_books,
            *FULL_YEAR_ARGS,
            "--fx-rates", fx_file,
        )
        assert result.exit_code == 0
        # Warning should NOT appear when FX rates are provided
        assert "No FX rates" not in result.output

    def test_with_fx_rates_shows_cad_total(self, temp_gnucash_for_close_books, tmp_path):
        fx_file = _fx_rates_file(tmp_path)
        result = run_cli(
            temp_gnucash_for_close_books,
            *FULL_YEAR_ARGS,
            "--fx-rates", fx_file,
        )
        assert result.exit_code == 0
        # With USD:1.35, net CAD = 5850 + 400*1.35 = 6390
        assert "6,390" in result.output or "6390" in result.output

    def test_missing_fx_rate_fails(self, temp_gnucash_for_close_books, tmp_path):
        # Rates file missing USD — book has USD transactions
        fx_file = _fx_rates_file(tmp_path, content="HKD: 0.172\n")
        result = run_cli(
            temp_gnucash_for_close_books,
            *FULL_YEAR_ARGS,
            "--fx-rates", fx_file,
        )
        assert result.exit_code != 0
        assert "USD" in result.output


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
        with open(out_file) as f:
            content = f.read()
        assert "<html" in content.lower()
        assert "INCOME" in content

    def test_html_contains_account_names(self, temp_gnucash_for_close_books, tmp_path):
        out_file = str(tmp_path / "report.html")
        run_cli(
            temp_gnucash_for_close_books,
            *FULL_YEAR_ARGS,
            "--output-format", "html",
            "--output", out_file,
        )
        with open(out_file) as f:
            content = f.read()
        assert "Salary" in content
        assert "Groceries" in content
