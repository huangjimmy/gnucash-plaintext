"""
Renders an IncomeStatementResult to text, HTML, or PDF.
"""

from fractions import Fraction
from pathlib import Path
from typing import Dict, Optional

from infrastructure.gnucash.utils import money_text
from services.foreign_currency import BASE_CURRENCY
from services.income_statement import IncomeStatementResult, IncomeStatementSection

# ---------------------------------------------------------------------------
# Plain text renderer
# ---------------------------------------------------------------------------

def _grouped(figure: str) -> str:
    """Thousands separators in the integer part, left as exact text.

    A figure with no exact decimal arrives as a fraction and passes through
    untouched — there is no integer part to group.
    """
    if '/' in figure:
        return figure
    sign = '-' if figure.startswith('-') else ''
    whole, _, decimals = figure.lstrip('-').partition('.')
    return sign + f'{int(whole):,}' + ('.' + decimals if decimals else '')


def _amount(amount: Fraction, unit: int) -> str:
    """An amount at its own currency's decimals, exactly.

    A statement figure is money: it is written at the smallest unit its
    currency actually has — hundredths for CAD, whole units for JPY — and it
    gets there through GnuCash's rounding rather than a float that can land a
    half-cent on the wrong side.
    """
    return _grouped(money_text(amount, unit))


def _fmt(amount: Fraction, currency: str, unit: int, width: int = 14) -> str:
    """Format a Fraction as a fixed-width currency string."""
    return f"{_amount(amount, unit)} {currency}".rjust(width)


def _unit_of(units: Dict[str, int], currency: str) -> int:
    return units.get(currency, 100)


def _render_section_text(section: IncomeStatementSection, fx_rates_provided: bool,
                         units: Dict[str, int]) -> list:
    lines = []
    lines.append(section.title)
    lines.append("-" * 60)

    prev_parent = ""
    subtotal_native: Dict[str, Fraction] = {}
    subtotal_cad = Fraction(0)

    def _flush_subtotal(parent_path: str):
        nonlocal subtotal_cad
        if not parent_path:
            return
        indent = "  " * (len(parent_path.split(":")) - 1)
        label = f"{indent}  Subtotal: {parent_path.split(':')[-1]}"
        native_str = "  ".join(
            f"{_amount(v, _unit_of(units, c)):>12} {c}"
            for c, v in sorted(subtotal_native.items())
        )
        if fx_rates_provided:
            cad_str = _fmt(subtotal_cad, BASE_CURRENCY,_unit_of(units, BASE_CURRENCY))
            lines.append(f"  {label:<50} {native_str}  {cad_str}")
        else:
            lines.append(f"  {label:<50} {native_str}")
        subtotal_native.clear()
        subtotal_cad = Fraction(0)

    for line in section.lines:
        parts = line.path.split(":")
        parent = ":".join(parts[:-1]) if len(parts) > 1 else ""

        if prev_parent and parent != prev_parent:
            _flush_subtotal(prev_parent)
            subtotal_native.clear()
            subtotal_cad = Fraction(0)

        if parent:
            subtotal_native[line.currency] = (
                subtotal_native.get(line.currency, Fraction(0)) + line.balance
            )
            if fx_rates_provided and line.cad_balance is not None:
                subtotal_cad += line.cad_balance

        indent = "  " * line.depth
        label = f"{indent}{line.name}"
        native_str = _fmt(line.balance, line.currency, _unit_of(units, line.currency))
        if fx_rates_provided:
            cad_str = (_fmt(line.cad_balance, BASE_CURRENCY,_unit_of(units, BASE_CURRENCY))
                       if line.cad_balance is not None else "")
            lines.append(f"  {label:<48} {native_str}  {cad_str}")
        else:
            lines.append(f"  {label:<48} {native_str}")

        prev_parent = parent

    if prev_parent:
        _flush_subtotal(prev_parent)

    # Section total
    lines.append("-" * 60)
    total_label = f"Total {section.title.title()}"
    native_totals = "  ".join(
        f"{_amount(v, _unit_of(units, c)):>12} {c}"
        for c, v in sorted(section.currency_totals.items())
    )
    if fx_rates_provided and section.cad_total is not None:
        cad_str = _fmt(section.cad_total, BASE_CURRENCY,_unit_of(units, BASE_CURRENCY))
        lines.append(f"  {total_label:<48} {native_totals}  {cad_str}")
    else:
        lines.append(f"  {total_label:<48} {native_totals}")
    lines.append("")
    return lines


def render_text(result: IncomeStatementResult) -> str:
    """Render income statement as plain text."""
    out = []
    out.append("=" * 60)
    out.append("INCOME STATEMENT")
    out.append(f"Period: {result.start_date} to {result.end_date}")
    out.append("=" * 60)
    out.append("")

    if not result.fx_rates_provided:
        out.append(
            f"NOTE: No FX rates supplied. {BASE_CURRENCY} totals not available.\n"
            "      Rerun with --fx-rates rates.yaml for CRA T2 filing.\n"
        )

    units = result.currency_units
    out.extend(_render_section_text(result.income, result.fx_rates_provided, units))
    out.extend(_render_section_text(result.expenses, result.fx_rates_provided, units))

    # Net income
    out.append("=" * 60)
    net_totals = "  ".join(
        f"{_amount(v, _unit_of(units, c)):>12} {c}"
        for c, v in sorted(result.net_currency_totals.items())
    )
    if result.fx_rates_provided and result.net_cad_total is not None:
        net_is_loss = result.net_cad_total < Fraction(0)
        label = "NET INCOME (LOSS)" if net_is_loss else "NET INCOME"
        cad_str = _fmt(result.net_cad_total, BASE_CURRENCY,_unit_of(units, BASE_CURRENCY))
        out.append(f"  {label:<48} {net_totals}  {cad_str}")
    else:
        out.append(f"  {'NET INCOME':<48} {net_totals}")
    out.append("=" * 60)

    return "\n".join(out)


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

def _build_rows(section: IncomeStatementSection, fx_rates_provided: bool,
                units: Dict[str, int]) -> list:
    """
    Build a flat list of row dicts for template rendering.

    Amounts reach the template as finished text, already at each currency's own
    decimals. The template prints them as given: formatting there would mean a
    float and a fixed two decimals, which is wrong for a currency that has no
    minor unit and can shift a half-cent in one that does.

    Each row is one of:
      {"kind": "line",     "depth": int, "name": str, "balance": str,
       "currency": str, "cad_balance": str|None}
      {"kind": "subtotal", "depth": int, "label": str,
       "native_totals": [(currency, str)], "cad_total": str|None}
      {"kind": "total",    "label": str,
       "native_totals": [(currency, str)], "cad_total": str|None}
    """
    rows = []
    prev_parent = ""
    subtotal_native: Dict[str, Fraction] = {}
    subtotal_cad = Fraction(0)

    def flush_subtotal(parent_path: str):
        nonlocal subtotal_cad
        if not parent_path:
            return
        depth = len(parent_path.split(":")) - 1
        label = f"Subtotal: {parent_path.split(':')[-1]}"
        rows.append({
            "kind": "subtotal",
            "depth": depth,
            "label": label,
            "native_totals": [(c, _amount(v, _unit_of(units, c)))
                              for c, v in sorted(subtotal_native.items())],
            "cad_total": (_amount(subtotal_cad, _unit_of(units, BASE_CURRENCY))
                          if fx_rates_provided else None),
        })
        subtotal_native.clear()
        subtotal_cad = Fraction(0)

    for line in section.lines:
        parts = line.path.split(":")
        parent = ":".join(parts[:-1]) if len(parts) > 1 else ""

        if prev_parent and parent != prev_parent:
            flush_subtotal(prev_parent)
            subtotal_native.clear()
            subtotal_cad = Fraction(0)

        if parent:
            subtotal_native[line.currency] = (
                subtotal_native.get(line.currency, Fraction(0)) + line.balance
            )
            if fx_rates_provided and line.cad_balance is not None:
                subtotal_cad += line.cad_balance

        rows.append({
            "kind": "line",
            "depth": line.depth,
            "name": line.name,
            "balance": _amount(line.balance, _unit_of(units, line.currency)),
            "currency": line.currency,
            "cad_balance": (_amount(line.cad_balance, _unit_of(units, BASE_CURRENCY))
                            if line.cad_balance is not None else None),
        })
        prev_parent = parent

    if prev_parent:
        flush_subtotal(prev_parent)

    rows.append({
        "kind": "total",
        "label": f"Total {section.title.title()}",
        "native_totals": [(c, _amount(v, _unit_of(units, c)))
                          for c, v in sorted(section.currency_totals.items())],
        "cad_total": (_amount(section.cad_total, _unit_of(units, BASE_CURRENCY))
                      if section.cad_total is not None else None),
    })
    return rows


def render_html(
    result: IncomeStatementResult,
    fx_rate_labels: Optional[list] = None,
) -> str:
    """
    Render income statement as HTML using the Jinja2 template.

    Args:
        result: IncomeStatementResult
        fx_rate_labels: List of strings like ["HKD: 0.172", "CNY: 0.185"]
                        for the footer note. Pass None if no FX rates.
    Returns:
        HTML string
    """
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
    )

    template = env.get_template("income_statement.html")

    units = result.currency_units
    income_rows = _build_rows(result.income, result.fx_rates_provided, units)
    expense_rows = _build_rows(result.expenses, result.fx_rates_provided, units)

    net_currency_totals = [(c, _amount(v, _unit_of(units, c)))
                           for c, v in sorted(result.net_currency_totals.items())]
    net_cad_total = (_amount(result.net_cad_total, _unit_of(units, BASE_CURRENCY))
                     if result.net_cad_total is not None else None)
    net_is_loss = result.net_cad_total is not None and result.net_cad_total < Fraction(0)

    return template.render(
        start_date=result.start_date,
        end_date=result.end_date,
        # The reporting currency is named once, here — the template prints
        # whatever the book reports in rather than a currency of its own.
        base_currency=BASE_CURRENCY,
        fx_rates_provided=result.fx_rates_provided,
        income_title=result.income.title,
        income_rows=income_rows,
        expense_title=result.expenses.title,
        expense_rows=expense_rows,
        net_currency_totals=net_currency_totals,
        net_cad_total=net_cad_total,
        net_is_loss=net_is_loss,
        fx_rate_labels=fx_rate_labels or [],
    )


# ---------------------------------------------------------------------------
# PDF renderer
# ---------------------------------------------------------------------------

def render_pdf(
    result: IncomeStatementResult,
    output_path: str,
    fx_rate_labels: Optional[list] = None,
) -> None:
    """
    Render income statement as PDF via WeasyPrint.

    Args:
        result: IncomeStatementResult
        output_path: Path to write PDF file
        fx_rate_labels: List of FX rate label strings for footer
    """
    import weasyprint

    html = render_html(result, fx_rate_labels=fx_rate_labels)
    weasyprint.HTML(string=html).write_pdf(output_path)
