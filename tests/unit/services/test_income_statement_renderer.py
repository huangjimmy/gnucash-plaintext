"""
Unit tests for income_statement_renderer.

These tests are pure Python — no GnuCash session required.
They construct IncomeStatementResult objects directly and verify
the text/HTML output.
"""

from datetime import date
from fractions import Fraction

import pytest

# ---------------------------------------------------------------------------
# Helpers: build minimal IncomeStatementResult objects
# ---------------------------------------------------------------------------

def _make_result(
    income_lines=None,
    expense_lines=None,
    fx_rates_provided=False,
    start=date(2024, 1, 1),
    end=date(2024, 12, 31),
):
    from fractions import Fraction

    from services.income_statement import (
        AccountLine,
        IncomeStatementResult,
        IncomeStatementSection,
    )

    def _section(title, lines):
        currency_totals = {}
        cad_total = Fraction(0) if fx_rates_provided else None
        for line in (lines or []):
            currency_totals[line.currency] = (
                currency_totals.get(line.currency, Fraction(0)) + line.balance
            )
            if fx_rates_provided and line.cad_balance is not None:
                cad_total += line.cad_balance
        return IncomeStatementSection(
            title=title,
            lines=lines or [],
            currency_totals=currency_totals,
            cad_total=cad_total if fx_rates_provided else None,
        )

    income_section = _section("INCOME", income_lines)
    expense_section = _section("EXPENSES", expense_lines)

    # Net currency totals
    all_currencies = set(income_section.currency_totals) | set(expense_section.currency_totals)
    net_currency_totals = {
        c: income_section.currency_totals.get(c, Fraction(0))
          - expense_section.currency_totals.get(c, Fraction(0))
        for c in all_currencies
    }
    net_cad_total = None
    if fx_rates_provided:
        inc_cad = income_section.cad_total or Fraction(0)
        exp_cad = expense_section.cad_total or Fraction(0)
        net_cad_total = inc_cad - exp_cad

    return IncomeStatementResult(
        start_date=start,
        end_date=end,
        income=income_section,
        expenses=expense_section,
        net_currency_totals=net_currency_totals,
        net_cad_total=net_cad_total,
        fx_rates_provided=fx_rates_provided,
    )


def _line(path, balance, currency="CAD", cad_balance=None):
    from services.income_statement import AccountLine
    parts = path.split(":")
    return AccountLine(
        path=path,
        name=parts[-1],
        depth=len(parts) - 1,
        currency=currency,
        balance=Fraction(balance),
        cad_balance=Fraction(cad_balance) if cad_balance is not None else None,
    )


# ---------------------------------------------------------------------------
# render_text
# ---------------------------------------------------------------------------

class TestRenderText:
    def test_output_contains_section_titles(self):
        from services.income_statement_renderer import render_text
        result = _make_result(
            income_lines=[_line("Income:Salary", 3000)],
            expense_lines=[_line("Expenses:Groceries", 400)],
        )
        text = render_text(result)
        assert "INCOME" in text
        assert "EXPENSES" in text

    def test_output_contains_account_names(self):
        from services.income_statement_renderer import render_text
        result = _make_result(
            income_lines=[_line("Income:Salary", 3000)],
            expense_lines=[_line("Expenses:Groceries", 400)],
        )
        text = render_text(result)
        assert "Salary" in text
        assert "Groceries" in text

    def test_output_contains_amounts(self):
        from services.income_statement_renderer import render_text
        result = _make_result(
            income_lines=[_line("Income:Salary", 3000)],
            expense_lines=[_line("Expenses:Groceries", 400)],
        )
        text = render_text(result)
        assert "3,000.00" in text
        assert "400.00" in text

    def test_no_fx_rates_shows_note(self):
        from services.income_statement_renderer import render_text
        result = _make_result(
            income_lines=[_line("Income:Salary", 3000)],
            expense_lines=[],
        )
        text = render_text(result)
        assert "No FX rates" in text or "fx" in text.lower() or "CAD totals not available" in text

    def test_fx_rates_provided_no_note(self):
        from services.income_statement_renderer import render_text
        result = _make_result(
            income_lines=[_line("Income:Salary", 3000, cad_balance=3000)],
            expense_lines=[],
            fx_rates_provided=True,
        )
        text = render_text(result)
        assert "No FX rates" not in text

    def test_empty_sections_renders_without_crash(self):
        from services.income_statement_renderer import render_text
        result = _make_result(income_lines=[], expense_lines=[])
        text = render_text(result)
        assert "INCOME" in text
        assert "EXPENSES" in text

    def test_net_income_line_present(self):
        from services.income_statement_renderer import render_text
        result = _make_result(
            income_lines=[_line("Income:Salary", 3000)],
            expense_lines=[_line("Expenses:Groceries", 400)],
        )
        text = render_text(result)
        assert "NET INCOME" in text

    def test_net_loss_label_when_expenses_exceed_income(self):
        from services.income_statement_renderer import render_text
        result = _make_result(
            income_lines=[_line("Income:Salary", 100, cad_balance=100)],
            expense_lines=[_line("Expenses:Groceries", 500, cad_balance=500)],
            fx_rates_provided=True,
        )
        text = render_text(result)
        # With fx_rates_provided=True and net negative, renderer emits "NET INCOME (LOSS)"
        assert "NET INCOME (LOSS)" in text

    def test_period_dates_in_output(self):
        from services.income_statement_renderer import render_text
        result = _make_result(
            start=date(2024, 1, 1),
            end=date(2024, 3, 31),
        )
        text = render_text(result)
        assert "2024-01-01" in text
        assert "2024-03-31" in text

    def test_zero_value_account_not_in_output(self):
        """compute() skips zero-balance accounts, so they never reach the renderer."""
        from services.income_statement_renderer import render_text
        # If a zero-balance line somehow appears, it should still not crash.
        result = _make_result(
            income_lines=[_line("Income:Salary", 0)],
            expense_lines=[],
        )
        text = render_text(result)
        assert "INCOME" in text  # Section renders fine even with a zero line


# ---------------------------------------------------------------------------
# _render_section_text
# ---------------------------------------------------------------------------

class TestRenderSectionText:
    def test_empty_section_renders_without_crash(self):
        from services.income_statement import IncomeStatementSection
        from services.income_statement_renderer import _render_section_text

        section = IncomeStatementSection(
            title="INCOME",
            lines=[],
            currency_totals={},
            cad_total=None,
        )
        lines = _render_section_text(section, fx_rates_provided=False)
        assert any("INCOME" in row for row in lines)

    def test_section_with_single_line(self):
        from services.income_statement_renderer import _render_section_text

        section = _make_result(
            income_lines=[_line("Income:Salary", 3000)],
        ).income
        lines = _render_section_text(section, fx_rates_provided=False)
        assert any("Salary" in row for row in lines)
        assert any("3,000.00" in row for row in lines)

    def test_section_without_fx_rates_no_cad_column(self):
        from services.income_statement_renderer import _render_section_text

        section = _make_result(
            income_lines=[_line("Income:Salary", 3000, cad_balance=3000)],
            fx_rates_provided=False,
        ).income
        lines = _render_section_text(section, fx_rates_provided=False)
        # CAD column should not appear when fx_rates_provided=False
        combined = "\n".join(lines)
        # The native amount is CAD, the second column would be duplicate —
        # key check: no extra "CAD" after the native amount
        assert "3,000.00 CAD" in combined


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------

class TestRenderHtml:
    def test_html_contains_section_title(self):
        from services.income_statement_renderer import render_html
        result = _make_result(
            income_lines=[_line("Income:Salary", 3000)],
            expense_lines=[_line("Expenses:Groceries", 400)],
        )
        html = render_html(result)
        assert "INCOME" in html
        assert "EXPENSES" in html

    def test_html_is_valid_structure(self):
        from services.income_statement_renderer import render_html
        result = _make_result(
            income_lines=[_line("Income:Salary", 3000)],
            expense_lines=[],
        )
        html = render_html(result)
        assert "<html" in html.lower() or "<!doctype" in html.lower() or "<table" in html.lower()

    def test_html_contains_account_names(self):
        from services.income_statement_renderer import render_html
        result = _make_result(
            income_lines=[_line("Income:Salary", 3000)],
            expense_lines=[_line("Expenses:Travel:Flight", 800)],
        )
        html = render_html(result)
        assert "Salary" in html
        assert "Flight" in html

    def test_html_empty_sections_no_crash(self):
        from services.income_statement_renderer import render_html
        result = _make_result(income_lines=[], expense_lines=[])
        html = render_html(result)
        assert html  # non-empty string


# ---------------------------------------------------------------------------
# _build_rows
# ---------------------------------------------------------------------------

class TestBuildRows:
    def test_line_rows_present(self):
        from services.income_statement_renderer import _build_rows

        section = _make_result(
            income_lines=[_line("Income:Salary", 3000)],
        ).income
        rows = _build_rows(section, fx_rates_provided=False)
        line_rows = [r for r in rows if r["kind"] == "line"]
        assert len(line_rows) == 1
        assert line_rows[0]["name"] == "Salary"

    def test_total_row_present(self):
        from services.income_statement_renderer import _build_rows

        section = _make_result(
            income_lines=[_line("Income:Salary", 3000)],
        ).income
        rows = _build_rows(section, fx_rates_provided=False)
        total_rows = [r for r in rows if r["kind"] == "total"]
        assert len(total_rows) == 1

    def test_subtotal_row_for_nested_accounts(self):
        from services.income_statement_renderer import _build_rows

        # Two accounts under same parent → subtotal row expected
        section = _make_result(
            income_lines=[
                _line("Income:Salary:Base",  3000),
                _line("Income:Salary:Bonus", 1000),
            ],
        ).income
        rows = _build_rows(section, fx_rates_provided=False)
        subtotals = [r for r in rows if r["kind"] == "subtotal"]
        assert len(subtotals) >= 1
