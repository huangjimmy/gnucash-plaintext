"""What `balance-sheet`, `income-statement` and `report` share.

Each prints a statement through a GnuCash report (Q-042). The book's currency is
found the same way, a rates or prices file is added to the book for the run the
same way, and the page is written out the same way. Text is printed by the
customized GnuCash reports in `infrastructure/gnucash/reports/`; HTML and PDF are GnuCash's Balance
Sheet or Income Statement report as GnuCash ships it.
"""

from pathlib import Path

import click

from services.book_currency import BookCurrencyUnknownError, book_currency
from services.report_prices import RatesFileError, add_for_the_run, read_quotes

OUTPUT_FORMATS = ('text', 'html', 'pdf')

CURRENCY_HELP = ("The currency the report is in (e.g. HKD). Without it: the company "
                 "block's base_currency, or else the currency the book's top-level "
                 "accounts share.")

RATES_HELP = ("YAML prices of other currencies in the report's currency (e.g. USD: 1.40), "
              "added to the book for this run and never saved.")

PRICES_HELP = ("YAML prices of securities (e.g. AMZN: 250, or AMZN/USD: 250), added to the "
               "book for this run and never saved.")

PRICE_SOURCE_HELP = ("Which recorded price the statement is priced from: pricedb-nearest "
                     "(GnuCash's default), pricedb-latest, or pricedb-before from GnuCash "
                     "4.8. Each reads the book's price database, so the price on a line is "
                     "one the book records.")

FX_GAIN_ACCOUNT_HELP = ("An account this book's realized exchange differences are booked to. "
                        "For a book whose disposals carry no took_the_residual, which is "
                        "every book written before that key existed: such a book states "
                        "realized_gains_fx: 0.00 though its income statement carries the "
                        "difference. Repeatable, for a book keeping its gains and its losses "
                        "in two accounts. The account is believed: on a disposal, whatever "
                        "sits on it is taken for the exchange difference, so specifying an "
                        "account that holds something else counts that instead — a bank "
                        "charge on a specified account is read as a loss. What the option "
                        "cannot do is widen where a difference may sit. Three conditions "
                        "the book answers for itself hold either way: the account must be "
                        "an income or expense account, the transaction must be stated in "
                        "the book's own currency, and one of its splits must state the "
                        "cost basis it draws on in cost_basis_split_guid. So it counts "
                        "nothing on a "
                        "transaction that disposed of no currency, and nothing at all for "
                        "a bank or receivable account — which is warned about, since such "
                        "an account can never count. Applies to the "
                        "plaintext page: --output-format html and pdf are GnuCash's own "
                        "Balance Sheet, which states no realized gain to specify an account "
                        "for.")

MAX_ITEMS_HELP = ("How many entries each itemized list beneath a gain figure may show. "
                  "-1, the "
                  "default, is no cap, which is what lets a reader add a total up for "
                  "themselves; 0 lists none of them. A book of 2,500 foreign purchases "
                  "draws a page of 40,154 lines and 1.4 MB uncapped, so a larger one can "
                  "be shortened with this. A shortened list says on its own line how many "
                  "entries there are, and ends with a not_listed: entry stating how many "
                  "were left out and what they come to, so the entries still add up to "
                  "the total printed beneath them.")


def page_for(output_format: str) -> str:
    """Which page GnuCash draws for an output format: text, or HTML for HTML and PDF."""
    return 'text' if output_format == 'text' else 'html'


def check_output(output_format: str, output_file) -> None:
    """Refuse a page format that cannot be written to the terminal, before the book is opened."""
    if output_format in ('html', 'pdf') and not output_file:
        raise click.UsageError(f'--output <file> is required for --output-format {output_format}')


def the_currency(book, stated) -> str:
    """The currency the report is in, or the refusal as a command error."""
    try:
        return book_currency(book, stated)
    except BookCurrencyUnknownError as refusal:
        raise click.ClickException(str(refusal)) from refusal


def read_price_files(fx_rates_file, prices_file) -> tuple:
    """The prices in the `--fx-rates` and `--prices` files, read before the book is opened."""
    try:
        return (read_quotes(fx_rates_file) if fx_rates_file else [],
                read_quotes(prices_file) if prices_file else [])
    except (OSError, RatesFileError) as refusal:
        raise click.ClickException(str(refusal)) from refusal


def add_the_files_prices(book, quotes, currency, report_days) -> None:
    """The files' prices, into the open book's price database for this run only."""
    rates, prices = quotes
    try:
        add_for_the_run(book, rates, prices, currency, report_days)
    except RatesFileError as refusal:
        raise click.ClickException(str(refusal)) from refusal


def write_out(page: str, output_format: str, output_file) -> None:
    """The page GnuCash drew, to the terminal or to a file, as text, HTML or PDF."""
    if output_format == 'text':
        if output_file:
            Path(output_file).write_text(page, encoding='utf-8')
            click.echo(f'Written to {output_file}')
        else:
            click.echo(page, nl=False)
    elif output_format == 'html':
        Path(output_file).write_text(page, encoding='utf-8')
        click.echo(f'HTML report written to {output_file}')
    else:
        from infrastructure.pdf.printing import laid_out_by_webkit

        Path(output_file).write_bytes(laid_out_by_webkit(page, 'pdf'))
        click.echo(f'PDF report written to {output_file}')
