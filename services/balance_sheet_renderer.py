"""Plain-text renderer for the balance sheet.

Reuses the income statement's section renderer (`_render_section_text`) so both
statements look identical in a `report` — same indented account tree, subtotals,
and section totals. `BSSection`/`BSLine` are shape-compatible with the income
statement's section/line (title, lines, currency_totals, cad_total; path, name,
depth, currency, balance, cad_balance)."""
from services.balance_sheet import BalanceSheetResult
from services.income_statement_renderer import _render_section_text


def render_text(result: BalanceSheetResult) -> str:
    out = ["=" * 60, "BALANCE SHEET", f"As of: {result.as_of_date}", "=" * 60, ""]
    if not result.fx_rates_provided:
        out.append("NOTE: No FX rates supplied. CAD totals not available.\n")
    if result.prices_provided:
        out.append("NOTE: Securities marked to market from supplied prices; "
                   "Unrealized Gains reconciles to cost.\n")
    out.extend(_render_section_text(result.assets, result.fx_rates_provided))
    out.extend(_render_section_text(result.liabilities, result.fx_rates_provided))
    out.extend(_render_section_text(result.equity, result.fx_rates_provided))
    out.append("=" * 60)
    status = "BALANCED" if result.balances else "NOT BALANCED — check the book"
    out.append(f"  {'Assets = Liabilities + Equity:':<48} {status}")
    out.append("=" * 60)
    return "\n".join(out)
