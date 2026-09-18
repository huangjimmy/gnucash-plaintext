"""`$residual$` outside a disposal is not an exchange difference.

A residual split takes what the others leave over, and the format allows it on
any transaction — the way GnuCash's editor fills an Imbalance line once an
account is chosen. Paying the rent that way is ordinary bookkeeping and has
nothing to do with foreign currency.

`realized_gains_fx` is the sum of the splits a residual resolved to, so marking
every one of them put a Canadian rent line on the sheet as a realized exchange
loss of 900.00 CAD, and itemised it as one, on a book holding no foreign
currency at all. The mark now goes on only where the transaction disposes of
foreign currency against a cost basis and is stated in the book's own currency:
in a transaction stated in US dollars the residual is a US dollar figure, and
adding it in would state it as Canadian.
"""

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.text_report_pages import key_of

LEDGER = 'tests/fixtures/a_cad_book_using_residual_on_an_ordinary_expense.txt'
AS_OF = '2026-12-31'


def _page(tmp_path):
    """10,000.00 CAD of capital, and 900.00 of rent taken by `$residual$`."""
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    made = _run(runner, 'import', '--new', str(book), LEDGER)
    assert made.exit_code == 0, made.output
    sheet = _run(runner, 'balance-sheet', str(book), '--as-of', AS_OF)
    assert sheet.exit_code == 0, sheet.output
    return sheet.output


def test_the_rent_is_not_a_realized_exchange_loss(tmp_path):
    page = _page(tmp_path)

    assert key_of(page, 'realized_gains_fx') == '0.00 CAD'
    assert key_of(page, 'total_realized_gains') == '0.00 CAD'


def test_the_working_states_no_exchange_difference(tmp_path):
    """The key and its working have to agree, and both are nothing here."""
    page = _page(tmp_path)

    listed = [line for line in page.splitlines()
              if line.lstrip().startswith('#   ') and 'Rent' in line]
    assert listed == [], page


def test_the_sheet_balances(tmp_path):
    """9,100.00 either side: the capital less the rent."""
    page = _page(tmp_path)

    assert key_of(page, 'total_assets') == '9100.00 CAD'
    assert key_of(page, 'total_liabilities_and_equity') == '9100.00 CAD'
