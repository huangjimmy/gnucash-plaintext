"""
CLI command for generating an income statement.

Supports CRA T2 fiscal year periods with optional FX conversion to CAD.
Output formats: text (stdout), HTML, PDF.
"""

from datetime import date, datetime
from typing import Optional

import click

from repositories.gnucash_repository import GnuCashRepository
from services.fx_rates import FxRates, MissingFxRateError
from use_cases.generate_income_statement import GenerateIncomeStatementUseCase, fiscal_year_start


def _parse_date(ctx, param, value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise click.BadParameter(f"Date must be in YYYY-MM-DD format, got: {value}") from e


@click.command("income-statement")
@click.argument("gnucash_file", type=click.Path(exists=True))
@click.option(
    "--fiscal-year-end",
    default=None,
    callback=_parse_date,
    is_eager=True,
    expose_value=True,
    help="Fiscal year end date (YYYY-MM-DD). Start is auto-computed as end − 1 year + 1 day.",
)
@click.option(
    "--start",
    default=None,
    callback=_parse_date,
    is_eager=True,
    expose_value=True,
    help="Period start date (YYYY-MM-DD). Use with --end for explicit range.",
)
@click.option(
    "--end",
    default=None,
    callback=_parse_date,
    is_eager=True,
    expose_value=True,
    help="Period end date (YYYY-MM-DD). Use with --start for explicit range.",
)
@click.option(
    "--fx-rates",
    "fx_rates_file",
    default=None,
    type=click.Path(exists=True),
    help="YAML file with FX rates → CAD (required for CRA T2 multi-currency totals).",
)
@click.option(
    "--output-format",
    type=click.Choice(["text", "html", "pdf"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format.",
)
@click.option(
    "--output",
    "output_file",
    default=None,
    type=click.Path(),
    help="Output file path. Required for html/pdf. Defaults to stdout for text.",
)
def income_statement(
    gnucash_file,
    fiscal_year_end,
    start,
    end,
    fx_rates_file,
    output_format,
    output_file,
):
    """
    Generate an income statement for a fiscal period.

    Supports CRA T2 filing with optional FX conversion of all currencies to CAD.

    \b
    Date range — use ONE of:
      --fiscal-year-end YYYY-MM-DD       (auto-computes start = end − 1 year + 1 day)
      --start YYYY-MM-DD --end YYYY-MM-DD (explicit range)

    \b
    Examples:
      Text output (calendar year 2024):
        gnucash-plaintext income-statement ledger.gnucash --fiscal-year-end 2024-12-31

      HTML with FX conversion to CAD:
        gnucash-plaintext income-statement ledger.gnucash \\
            --fiscal-year-end 2024-03-31 \\
            --fx-rates rates.yaml \\
            --output-format html --output report.html

      PDF for CRA T2:
        gnucash-plaintext income-statement ledger.gnucash \\
            --start 2023-04-01 --end 2024-03-31 \\
            --fx-rates rates.yaml \\
            --output-format pdf --output report.pdf
    """
    # --- Resolve date range ---
    if fiscal_year_end is not None and (start is not None or end is not None):
        raise click.UsageError(
            "--fiscal-year-end cannot be combined with --start/--end. Use one or the other."
        )

    if fiscal_year_end is not None:
        period_end = fiscal_year_end
        period_start = fiscal_year_start(fiscal_year_end)
    elif start is not None and end is not None:
        period_start = start
        period_end = end
    elif start is not None or end is not None:
        raise click.UsageError("Provide both --start and --end together.")
    else:
        raise click.UsageError(
            "Provide a date range: --fiscal-year-end YYYY-MM-DD  "
            "or --start YYYY-MM-DD --end YYYY-MM-DD"
        )

    # --- Output file validation ---
    if output_format in ("html", "pdf") and not output_file:
        raise click.UsageError(f"--output <file> is required for --output-format {output_format}")

    # --- Load FX rates ---
    fx_rates: Optional[FxRates] = None
    fx_rate_labels: list = []
    if fx_rates_file:
        try:
            fx_rates = FxRates.load(fx_rates_file)
            fx_rate_labels = [
                f"{c}: {fx_rates.get_rate(c)}"
                for c in sorted(fx_rates.available_currencies)
                if c != "CAD"
            ]
        except (FileNotFoundError, ValueError) as e:
            raise click.ClickException(str(e)) from e

    # --- Run ---
    repo = GnuCashRepository(gnucash_file)
    repo.open()

    try:
        use_case = GenerateIncomeStatementUseCase(repo)
        try:
            result = use_case.execute(
                start_date=period_start,
                end_date=period_end,
                fx_rates=fx_rates,
            )
        except MissingFxRateError as e:
            raise click.ClickException(str(e)) from e
        except ValueError as e:
            raise click.ClickException(str(e)) from e
    finally:
        repo.close()

    # --- Render ---
    from services.income_statement_renderer import render_html, render_pdf, render_text

    if output_format == "text":
        text = render_text(result)
        if output_file:
            _write_file(output_file, text)
            click.echo(f"Written to {output_file}")
        else:
            click.echo(text)

    elif output_format == "html":
        html = render_html(result, fx_rate_labels=fx_rate_labels)
        _write_file(output_file, html)
        click.echo(f"HTML report written to {output_file}")

    elif output_format == "pdf":
        try:
            render_pdf(result, output_file, fx_rate_labels=fx_rate_labels)
        except ImportError as e:
            raise click.ClickException(
                "WeasyPrint is not installed. Install it with:\n"
                "  pip install weasyprint\n"
                "or in Docker: apt install python3-weasyprint  (Debian) / "
                "pip install weasyprint  (Ubuntu)"
            ) from e
        click.echo(f"PDF report written to {output_file}")


def _write_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
