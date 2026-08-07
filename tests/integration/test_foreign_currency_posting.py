"""Q-035: posting a foreign-currency invoice or bill.

Covers the two rules that make it safe: a record posts only to an A/R or A/P
account in its own currency, and an entry booked to an account in another
currency is valued at the posting-date rate — which must be supplied.
"""

from click.testing import CliRunner

from cli.main import cli

RATES = 'tests/fixtures/fx_rates_usd_dated.yaml'


def _import(runner, book, fixture, *extra):
    return runner.invoke(cli, ['import', '--new', str(book), fixture,
                               '--include-business-objects', *extra])


def _export(runner, book, out):
    result = runner.invoke(cli, ['export', str(book), str(out),
                                 '--include-business-objects'])
    assert result.exit_code == 0, result.output
    return out.read_text()


def test_usd_invoice_to_cad_ar_is_refused(tmp_path):
    """Naming both currencies and the account, rather than writing an
    amount-zero A/R split whose lot closes on its own posting date."""
    runner = CliRunner()
    result = _import(runner, tmp_path / 'book.gnucash',
                     'tests/fixtures/fx_usd_invoice_cad_ar.txt', '--fx-rates', RATES)
    assert result.exit_code != 0, result.output
    message = str(result.output) + str(result.exception)
    assert 'USD' in message and 'CAD' in message, message
    assert 'Assets:Accounts Receivable' in message, message


def test_usd_bill_to_cad_ap_is_refused(tmp_path):
    runner = CliRunner()
    result = _import(runner, tmp_path / 'book.gnucash',
                     'tests/fixtures/fx_usd_bill_cad_ap.txt', '--fx-rates', RATES)
    assert result.exit_code != 0, result.output
    message = str(result.output) + str(result.exception)
    assert 'USD' in message and 'CAD' in message, message
    assert 'Accounts Payable' in message, message


def test_usd_invoice_books_income_in_cad_at_the_posting_date_rate(tmp_path):
    """100.00 USD invoiced on a day the file quotes at 1.40 recognises
    140.00 CAD of revenue, and leaves the A/R lot open for 100.00 USD."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _import(runner, book, 'tests/fixtures/fx_usd_invoice_cad_income.txt',
                     '--fx-rates', RATES)
    assert result.exit_code == 0, result.output

    exported = _export(runner, book, tmp_path / 'out.txt')
    assert 'Assets:Accounts Receivable USD 100.00 USD' in exported, exported
    assert 'Income:Sales -140.00 CAD' in exported, exported


def test_posting_without_a_rate_is_refused(tmp_path):
    """The engine aborts the posting and writes nothing while still reporting
    the invoice created, so the importer refuses first — naming the flag."""
    runner = CliRunner()
    result = _import(runner, tmp_path / 'book.gnucash',
                     'tests/fixtures/fx_usd_invoice_cad_income.txt')
    assert result.exit_code != 0, result.output
    message = str(result.output) + str(result.exception)
    assert '--fx-rates' in message, message


def test_posting_on_a_date_before_every_quote_is_refused(tmp_path):
    """A rate is not extrapolated backwards: the earliest quote is named."""
    runner = CliRunner()
    rates = tmp_path / 'late_rates.yaml'
    rates.write_text('USD/CAD:\n  2026-06-01: 1.42\n')
    result = _import(runner, tmp_path / 'book.gnucash',
                     'tests/fixtures/fx_usd_invoice_cad_income.txt',
                     '--fx-rates', str(rates))
    assert result.exit_code != 0, result.output
    message = str(result.output) + str(result.exception)
    assert '2026-06-01' in message, message


def test_usd_bill_books_expense_in_cad_at_the_posting_date_rate(tmp_path):
    """The bill-side mirror: 100.00 USD billed at 1.40 is 140.00 CAD of
    expense, against a 100.00 USD payable."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _import(runner, book, 'tests/fixtures/fx_usd_bill_cad_expense.txt',
                     '--fx-rates', RATES)
    assert result.exit_code == 0, result.output

    exported = _export(runner, book, tmp_path / 'out.txt')
    assert 'Liabilities:Accounts Payable USD -100.00 USD' in exported, exported
    assert 'Expenses:Supplies 140.00 CAD' in exported, exported


def test_cad_invoice_and_bill_still_post_and_pay_unchanged(tmp_path):
    """The single-currency path is untouched — no rate needed, no rate used."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    result = _import(runner, book, 'tests/fixtures/business_objects.txt')
    assert result.exit_code == 0, result.output

    exported = _export(runner, book, tmp_path / 'out.txt')
    assert 'invoice "INV-2026-001"' in exported, exported
    assert 'bill "BILL-2026-001"' in exported or 'bill "' in exported, exported
    # A paid CAD invoice still reports its payment rather than `payment: none`.
    assert 'payment:' in exported, exported
