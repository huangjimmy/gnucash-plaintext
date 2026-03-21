"""
Integration tests for the account-balance CLI command.

Uses the temp_gnucash_account_balance fixture (all 5 account types,
CAD + HKD, sub-accounts under Expenses:Food and Income:HKDIncome).
"""

import pytest
from click.testing import CliRunner

from cli.main import cli


def run_cli(*args):
    runner = CliRunner()
    return runner.invoke(cli, ["account-balance"] + list(args))


def _fx_file(tmp_path, content="HKD: 0.17\n"):
    p = tmp_path / "rates.yaml"
    p.write_text(content)
    return str(p)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestAccountBalanceErrors:

    def test_missing_gnucash_file(self):
        result = run_cli("/nonexistent/file.gnucash")
        assert result.exit_code != 0

    def test_invalid_as_of_date(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "not-a-date")
        assert result.exit_code != 0
        assert "YYYY-MM-DD" in result.output

    def test_invalid_fx_rates_file(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--fx-rates", "/nonexistent/rates.yaml")
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------

class TestAccountBalanceOutput:

    def test_outputs_balance_directive_header(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31")
        assert result.exit_code == 0
        assert "2024-12-31 balance" in result.output

    def test_outputs_leaf_accounts_with_amounts(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31")
        assert result.exit_code == 0
        assert "Assets:Bank:Checking" in result.output
        assert "Assets:Bank:HKD" in result.output
        assert "Expenses:Food:Groceries" in result.output
        assert "Expenses:Food:Dining" in result.output
        assert "Income:HKDIncome:Freelance" in result.output
        assert "Income:HKDIncome:Dividends" in result.output
        assert "Expenses:HKDExpenses:Transport" in result.output
        assert "Liabilities:CreditCard" in result.output
        assert "Liabilities:HKDLoan" in result.output

    def test_parent_accounts_not_in_output(self, temp_gnucash_account_balance):
        """Parent-only accounts (placeholder) must not appear as balance lines."""
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31")
        assert result.exit_code == 0
        lines = result.output.splitlines()
        account_lines = [line for line in lines if line.startswith("\t")]
        account_names = [line.split()[0] for line in account_lines]
        assert "Expenses:Food" not in account_names
        assert "Expenses:HKDExpenses" not in account_names
        assert "Income:HKDIncome" not in account_names

    def test_checking_balance_value(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Assets:Bank:Checking")
        assert result.exit_code == 0
        assert "3420.00" in result.output
        assert "CAD" in result.output

    def test_hkd_bank_balance_value(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Assets:Bank:HKD")
        assert result.exit_code == 0
        assert "8700.00" in result.output
        assert "HKD" in result.output

    def test_account_prefix_filters_output(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Assets:Bank")
        assert result.exit_code == 0
        assert "Assets:Bank:Checking" in result.output
        assert "Assets:Bank:HKD" in result.output
        assert "Expenses" not in result.output
        assert "Income" not in result.output
        assert "Liabilities" not in result.output

    def test_expenses_food_prefix(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Expenses:Food")
        assert result.exit_code == 0
        assert "Expenses:Food:Groceries" in result.output
        assert "Expenses:Food:Dining" in result.output
        assert "Transport" not in result.output

    def test_output_to_file(self, temp_gnucash_account_balance, tmp_path):
        out_file = str(tmp_path / "balances.txt")
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "-o", out_file)
        assert result.exit_code == 0
        assert "Written to" in result.output
        with open(out_file) as f:
            content = f.read()
        assert "2024-12-31 balance" in content
        assert "Assets:Bank:Checking" in content

    def test_default_as_of_is_today(self, temp_gnucash_account_balance):
        """Omitting --as-of should succeed (uses today)."""
        result = run_cli(temp_gnucash_account_balance)
        assert result.exit_code == 0
        assert "balance" in result.output


# ---------------------------------------------------------------------------
# FX rates consolidation
# ---------------------------------------------------------------------------

class TestAccountBalanceFxRates:

    def test_with_fx_rates_outputs_cad(self, temp_gnucash_account_balance, tmp_path):
        fx = _fx_file(tmp_path)
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "--fx-rates", fx, "Assets:Bank")
        assert result.exit_code == 0, result.output
        # Account lines use a single leading tab; metadata lines use two tabs
        account_lines = [line for line in result.output.splitlines()
                         if line.startswith("\t") and not line.startswith("\t\t")]
        for line in account_lines:
            assert line.strip().endswith("CAD"), f"Expected CAD suffix: {line!r}"

    def test_with_fx_rates_shows_share_price_and_original(self, temp_gnucash_account_balance, tmp_path):
        """HKD account shows share_price and original amount metadata."""
        fx = _fx_file(tmp_path)
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "--fx-rates", fx, "Assets:Bank:HKD")
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        share_price_line = next((line for line in lines if "share_price:" in line), None)
        original_line = next((line for line in lines if "original:" in line), None)
        assert share_price_line is not None, f"No share_price line in:\n{result.output}"
        assert "17/100" in share_price_line, f"Expected 17/100 in share_price line: {share_price_line!r}"
        assert original_line is not None, f"No original line in:\n{result.output}"
        assert "8700.00 HKD" in original_line, f"Expected 8700.00 HKD in original line: {original_line!r}"

    def test_with_fx_rates_checking_converted_correctly(self, temp_gnucash_account_balance, tmp_path):
        """CAD account should remain 3420.00 CAD (rate 1.0)."""
        fx = _fx_file(tmp_path)
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "--fx-rates", fx, "Assets:Bank:Checking")
        assert result.exit_code == 0
        assert "3420.00" in result.output
        assert "CAD" in result.output

    def test_with_fx_rates_hkd_converted_correctly(self, temp_gnucash_account_balance, tmp_path):
        """HKD 8700 * 0.17 = 1479.00 CAD."""
        fx = _fx_file(tmp_path)
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "--fx-rates", fx, "Assets:Bank:HKD")
        assert result.exit_code == 0
        assert "1479.00" in result.output
        assert "CAD" in result.output
