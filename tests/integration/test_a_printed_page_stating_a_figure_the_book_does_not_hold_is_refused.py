"""A printed invoice page that states a figure the book does not hold is refused on re-import.

`print-invoice --format plaintext` states what each line is worth: its amount,
its tax, and one `breakdown:` block per tax-table entry with the account, the
rate and the amount. Reading the page back recomputes each from the line and its
tax table and compares them exactly, so a page edited by hand, or copied into
another book, is refused for the figure it states wrongly, with both numbers.
A page that leaves the line's amount and tax out and states only the breakdown
is read like any other.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
ACCOUNTS = FIXTURES / 'q017_accounts.txt'
INVOICE = FIXTURES / 'q017_combined_hst_invoice.txt'

GST_BREAKDOWN = ('\t\tbreakdown:\n'
                 '\t\t\taccount: "Liabilities:Tax:GST"\n'
                 '\t\t\trate: 5.0\n'
                 '\t\t\tamount: 10.00\n')


@pytest.fixture
def printed(tmp_path):
    """The combined GST+PST invoice, printed as plaintext."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = runner.invoke(cli, ['import', '--new', str(book), str(ACCOUNTS)])
    assert made.exit_code == 0, made.output
    imported = runner.invoke(cli, ['import', str(book), str(INVOICE),
                                   '--include-business-objects'])
    assert imported.exit_code == 0, imported.output
    page = runner.invoke(cli, ['print-invoice', str(book), 'INV-Q17-COMBINED-200',
                               '--format', 'plaintext', '-o', '-'])
    assert page.exit_code == 0, page.output
    assert GST_BREAKDOWN in page.output, page.output
    return page.output


def _read_back(tmp_path, page):
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(ACCOUNTS.read_text() + '\n' + page)
    return CliRunner().invoke(cli, ['import', '--new', str(tmp_path / 'fresh.gnucash'),
                                    str(ledger), '--include-business-objects'])


@pytest.mark.parametrize('stated, edited, reason', [
    ('\t\tentry_amount: 200.00\n', '\t\tentry_amount: 199.00\n',
     'declared entry_amount 199 does not match'),
    ('\t\tentry_amount: 200.00\n', '\t\tentry_amount: "two hundred"\n',
     "entry_amount must be a number, got 'two hundred'"),
    (GST_BREAKDOWN, '',
     'declared breakdown has 1 block(s) but the tax_table'),
    (GST_BREAKDOWN, GST_BREAKDOWN.replace('Tax:GST', 'Tax:QST'),
     "breakdown account 'Liabilities:Tax:QST' is not on the entry's tax_table"),
    (GST_BREAKDOWN, GST_BREAKDOWN.replace('rate: 5.0', 'rate: "five"'),
     "breakdown for 'Liabilities:Tax:GST' must declare numeric rate and amount"),
    (GST_BREAKDOWN, GST_BREAKDOWN.replace('rate: 5.0', 'rate: 6.0'),
     "breakdown for 'Liabilities:Tax:GST' declares rate 6 but tax_table stores"),
], ids=['amount-differs', 'amount-not-a-number', 'a-breakdown-left-out',
        'a-breakdown-account-not-on-the-table', 'a-rate-not-a-number', 'a-rate-differs'])
def test_the_page_is_refused_for_the_figure_it_states(tmp_path, printed, stated, edited, reason):
    result = _read_back(tmp_path, printed.replace(stated, edited, 1))

    assert result.exit_code != 0, result.output
    assert reason in result.output, result.output


def test_a_page_stating_only_the_breakdown_is_read(tmp_path, printed):
    page = (printed.replace('\t\tentry_amount: 200.00\n', '', 1)
                   .replace('\t\tentry_tax: 26.00\n', '', 1))

    result = _read_back(tmp_path, page)

    assert result.exit_code == 0, result.output
