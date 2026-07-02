"""
Integration tests for the account-balance CLI command.

Uses the temp_gnucash_account_balance fixture (all 5 account types,
CAD + HKD, sub-accounts under Expenses:Food and Income:HKDIncome).

Behaviour summary:
  No ACCOUNT_PREFIX         -> all accounts with recursive totals (needs FX for mixed-currency)
  With ACCOUNT_PREFIX       -> only that account with recursive total
  With ACCOUNT_PREFIX
    + --with-children       -> account + all sub-accounts each with recursive total
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

    def test_nonexistent_account_prefix_raises_error(self, temp_gnucash_account_balance):
        """Typo in account prefix should fail clearly, not silently return empty output."""
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Asset:Bank")  # missing 's'
        assert result.exit_code != 0, (
            f"Expected error for nonexistent account 'Asset:Bank', got: {result.output}"
        )

    def test_mixed_currency_no_prefix_without_fx_raises_error(self, temp_gnucash_account_balance):
        """No prefix on multi-currency book without FX rates must fail."""
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31")
        assert result.exit_code != 0, (
            f"Expected error for mixed-currency book without FX, got: {result.output}"
        )

    def test_mixed_currency_prefix_without_fx_raises_error(self, temp_gnucash_account_balance):
        """Mixed-currency account without FX rates must fail."""
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Assets:Bank")
        assert result.exit_code != 0, (
            f"Expected error for Assets:Bank without FX, got: {result.output}"
        )


# ---------------------------------------------------------------------------
# Single account (no --with-children): recursive total only
# ---------------------------------------------------------------------------

class TestAccountBalanceSingleAccount:

    def test_outputs_balance_directive_header(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Expenses:Food")
        assert result.exit_code == 0, result.output
        assert "2024-12-31 balance" in result.output

    def test_single_cad_leaf_balance(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Assets:Bank:Checking")
        assert result.exit_code == 0, result.output
        assert "3420.00" in result.output
        assert "CAD" in result.output
        assert "Assets:Bank:Checking" in result.output

    def test_single_hkd_leaf_balance(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Assets:Bank:HKD")
        assert result.exit_code == 0, result.output
        assert "8700.00" in result.output
        assert "HKD" in result.output

    def test_parent_single_currency_recursive_total(self, temp_gnucash_account_balance):
        """Expenses:Food total = Groceries(50) + Dining(30) = 80 CAD."""
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Expenses:Food")
        assert result.exit_code == 0, result.output
        assert "Expenses:Food" in result.output
        assert "80.00" in result.output
        assert "CAD" in result.output
        # No sub-account breakdown by default
        assert "Groceries" not in result.output
        assert "Dining" not in result.output

    def test_default_as_of_succeeds_for_single_currency(self, temp_gnucash_account_balance):
        """Omitting --as-of should succeed for single-currency account (uses today)."""
        result = run_cli(temp_gnucash_account_balance, "Expenses:Food")
        assert result.exit_code == 0, result.output
        assert "balance" in result.output

    def test_output_to_file(self, temp_gnucash_account_balance, tmp_path):
        out_file = str(tmp_path / "balances.txt")
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Expenses:Food", "-o", out_file)
        assert result.exit_code == 0, result.output
        assert "Written to" in result.output
        with open(out_file) as f:
            content = f.read()
        assert "2024-12-31 balance" in content
        assert "Expenses:Food" in content
        assert "80.00" in content


# ---------------------------------------------------------------------------
# --with-children: account + sub-account breakdown
# ---------------------------------------------------------------------------

class TestAccountBalanceWithChildren:

    def test_with_children_shows_parent_and_sub_accounts(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Expenses:Food", "--with-children")
        assert result.exit_code == 0, result.output
        assert "Expenses:Food" in result.output
        assert "Expenses:Food:Groceries" in result.output
        assert "Expenses:Food:Dining" in result.output

    def test_with_children_parent_balance_is_recursive_total(self, temp_gnucash_account_balance):
        """Expenses:Food line shows 80.00 (sum of children), children show their own amounts."""
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Expenses:Food", "--with-children")
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        food_line = next(
            (line for line in lines if "Expenses:Food" in line and "Groceries" not in line
             and "Dining" not in line),
            None,
        )
        assert food_line is not None, f"No Expenses:Food line in:\n{result.output}"
        assert "80.00" in food_line, f"Expected 80.00 in {food_line!r}"

        groceries_line = next((line for line in lines if "Groceries" in line), None)
        assert groceries_line is not None
        assert "50.00" in groceries_line, f"Expected 50.00 in {groceries_line!r}"

    def test_with_children_filters_other_accounts(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Expenses:Food", "--with-children")
        assert result.exit_code == 0, result.output
        assert "Transport" not in result.output
        assert "Assets" not in result.output
        assert "Income" not in result.output
        assert "Liabilities" not in result.output

    def test_with_children_mixed_currency_requires_fx(self, temp_gnucash_account_balance):
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "Assets:Bank", "--with-children")
        assert result.exit_code != 0, (
            f"Expected error for Assets:Bank --with-children without FX: {result.output}"
        )


# ---------------------------------------------------------------------------
# Whole-book export (no ACCOUNT_PREFIX) with FX rates
# ---------------------------------------------------------------------------

class TestAccountBalanceWholeBook:

    def test_whole_book_with_fx_shows_all_accounts(self, temp_gnucash_account_balance, tmp_path):
        fx = _fx_file(tmp_path)
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "--fx-rates", fx)
        assert result.exit_code == 0, result.output
        # Parent accounts
        assert "Assets:Bank" in result.output
        assert "Expenses:Food" in result.output
        assert "Income:HKDIncome" in result.output
        # Leaf accounts
        assert "Assets:Bank:Checking" in result.output
        assert "Assets:Bank:HKD" in result.output
        assert "Expenses:Food:Groceries" in result.output

    def test_whole_book_all_in_cad(self, temp_gnucash_account_balance, tmp_path):
        fx = _fx_file(tmp_path)
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "--fx-rates", fx)
        assert result.exit_code == 0, result.output
        account_lines = [
            line for line in result.output.splitlines()
            if line.startswith("\t") and not line.startswith("\t\t")
        ]
        assert account_lines, "No account lines found in output"
        for line in account_lines:
            assert line.strip().endswith("CAD"), f"Expected CAD suffix: {line!r}"


# ---------------------------------------------------------------------------
# FX rates: conversion details
# ---------------------------------------------------------------------------

class TestAccountBalanceFxRates:

    def test_fx_hkd_leaf_shows_share_price_and_original(self, temp_gnucash_account_balance, tmp_path):
        """HKD leaf account shows share_price and original amount on their own lines."""
        fx = _fx_file(tmp_path)
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "--fx-rates", fx, "Assets:Bank:HKD")
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        share_price_line = next((line for line in lines if "share_price:" in line), None)
        original_line = next((line for line in lines if "original:" in line), None)
        assert share_price_line is not None, f"No share_price line in:\n{result.output}"
        assert "17/100" in share_price_line, f"Expected 17/100 in: {share_price_line!r}"
        assert original_line is not None, f"No original line in:\n{result.output}"
        assert "8700.00 HKD" in original_line, f"Expected 8700.00 HKD in: {original_line!r}"

    def test_fx_cad_account_no_metadata(self, temp_gnucash_account_balance, tmp_path):
        """CAD account with FX: no share_price/original metadata (already in CAD)."""
        fx = _fx_file(tmp_path)
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "--fx-rates", fx, "Assets:Bank:Checking")
        assert result.exit_code == 0, result.output
        assert "3420.00" in result.output
        assert "CAD" in result.output
        assert "share_price:" not in result.output
        assert "original:" not in result.output

    def test_fx_hkd_converted_amount(self, temp_gnucash_account_balance, tmp_path):
        """HKD 8700 * 0.17 = 1479.00 CAD."""
        fx = _fx_file(tmp_path)
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "--fx-rates", fx, "Assets:Bank:HKD")
        assert result.exit_code == 0, result.output
        assert "1479.00" in result.output
        assert "CAD" in result.output

    def test_fx_mixed_currency_parent_total(self, temp_gnucash_account_balance, tmp_path):
        """Assets:Bank with FX: recursive total = 3420 + 8700*0.17 = 4899.00 CAD."""
        fx = _fx_file(tmp_path)
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "--fx-rates", fx, "Assets:Bank")
        assert result.exit_code == 0, result.output
        assert "4899.00" in result.output
        assert "CAD" in result.output
        # No sub-account breakdown (default, no --with-children)
        assert "Assets:Bank:Checking" not in result.output
        assert "Assets:Bank:HKD" not in result.output


# ---------------------------------------------------------------------------
# Pricedb persistence
# ---------------------------------------------------------------------------


class TestAccountBalancePricedbPersistence:
    """Verify that --fx-rates actually saves price entries to disk.

    Gap identified: all other tests verify the CLI output, which is computed
    from the in-memory YAML rates within the same session. If repo.save() were
    silently skipped, the output would be identical but the pricedb entries
    would not survive the session close.
    """

    def test_fx_rates_written_to_pricedb_on_disk(self, temp_gnucash_account_balance, tmp_path):
        """HKD/CAD price entry appears in a fresh session opened after the CLI run."""
        import time

        from gnucash.gnucash_core_c import gnc_pricedb_get_db, gnc_pricedb_lookup_latest

        from repositories.gnucash_repository import GnuCashRepository, SessionMode

        # GnuCash backup filenames are timestamp-based (second resolution).
        # The fixture saves during setup; without this sleep the CLI save would
        # collide with the same-second backup → ERR_FILEIO_BACKUP_ERROR → no save.

        fx = _fx_file(tmp_path)
        result = run_cli(temp_gnucash_account_balance, "--as-of", "2024-12-31",
                         "--fx-rates", fx)
        assert result.exit_code == 0, result.output

        # Open a brand-new session from disk — no shared state with the CLI run.
        repo = GnuCashRepository(temp_gnucash_account_balance)
        repo.open(mode=SessionMode.READ_ONLY)
        try:
            book = repo.book
            commod_table = book.get_table()
            hkd = commod_table.lookup("CURRENCY", "HKD")
            cad = commod_table.lookup("CURRENCY", "CAD")

            assert hkd is not None, "HKD commodity not found in book"
            assert cad is not None, "CAD commodity not found in book"

            pricedb = gnc_pricedb_get_db(book.instance)
            price = gnc_pricedb_lookup_latest(pricedb, hkd.instance, cad.instance)

            assert price is not None, (
                "No HKD/CAD price entry found in pricedb after account-balance "
                "--fx-rates run. repo.save() was not called or the pricedb write "
                "was not persisted to disk."
            )
        finally:
            repo.close()
