"""A printed document's totals are in the document's currency.

A USD invoice is for USD. Its line items say so, and its subtotal and amount
due have to say the same — printed for a customer, the figure at the bottom is
the one they are being asked to pay.

The totals were summed off the posting transaction's splits, by account type,
using each split's **amount**. A split's amount is in its own account's
commodity: post a USD invoice whose `Income:Sales` is CAD and the income split
holds the CAD figure, so a USD 100.00 invoice printed `USD 140.00` — the CAD
value at 1.40, under a USD label — while the line above it read `$100.00`.
Only the totals were wrong, because the line rows are computed from the
entries in the invoice's own currency.

Nothing sums anything now: GnuCash's own Printable Invoice draws the page, and
it prices a document from the document — so the line rows, the subtotal, the
tax and the amount due are all in the currency the document is written in.

**A cross-currency payment is GnuCash's own, and 3.8 states it differently.**
This invoice is USD 100.00, settled through a transaction GnuCash values in
CAD. The book is identical on both builds — measured: `IsPaid()` true, the
posted lot holding two splits and a balance of zero on 5.10 and on 3.8 alike —
and the report is not. 5.10 states the payment in the document's currency and
ends on `Amount Due $0.00`; 3.8 prints the row as `-C$140.00` and leaves
`Amount Due` at `$100.00`, having not matched a payment it read in another
currency against a USD document.

That row is the report's, not ours, so what these tests read is the totals: the
figure the whole defect was about. That a paid document shows nothing still due
is `test_a_printed_document_shows_what_is_still_due`, on a CAD invoice paid
from a CAD bank — every build gets that right.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
LEDGER = str(FIXTURES / 'fx_usd_invoice_settled_into_an_hkd_bank.txt')
RATES = str(FIXTURES / 'fx_rates_usd_and_hkd.yaml')


def _money_cells(html: str):
    """Every table cell holding a figure, as plain text."""
    import re

    cells = [re.sub(r'<[^>]+>', '', c).replace('\xa0', ' ').strip()
             for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', html, re.S)]
    return [c for c in cells if re.search(r'\d+\.\d\d', c)]


def _totals(html: str) -> dict:
    """`{'Net Price': '$100.00', …}` — the report's labelled total rows.

    Read as label-and-figure pairs rather than by position: the payment rows
    sit among them, carry no label cell, and are the one place a version
    difference lives.
    """
    import re

    return {label.strip(): figure.strip() for label, figure in re.findall(
        r'total-label-cell"[^>]*>(.*?)</td>\s*'
        r'<td class="total-number-cell"[^>]*>(.*?)</td>', html, re.S)}


def _entry_cells(html: str):
    """The figures on the entry lines — `number-cell`, not the totals'
    `total-number-cell`."""
    import re

    return [c.strip() for c in
            re.findall(r'<td class="number-cell"[^>]*>(.*?)</td>', html, re.S)]


@pytest.fixture
def printed(tmp_path):
    runner = CliRunner()
    book = tmp_path / 'book.gnucash'
    built = runner.invoke(cli, ['import', '--new', str(book), LEDGER,
                                '--include-business-objects',
                                '--fx-rates', RATES])
    assert built.exit_code == 0, built.output

    out = tmp_path / 'inv.html'
    result = runner.invoke(cli, ['print-invoice', str(book),
                                 'INV-USD-INTO-HKD', '--format', 'html',
                                 '-o', str(out)])
    assert result.exit_code == 0, result.output
    return out.read_text()


class TestAUsdInvoiceWhoseIncomeAccountIsCad:
    def test_no_total_is_the_base_currency_value(self, printed):
        """140.00 is the CAD the book values it at, and `C$` is how GnuCash
        writes CAD — so a total carrying either is a total in the wrong
        currency."""
        totals = _totals(printed)

        assert totals, printed
        for label, figure in totals.items():
            assert 'C$' not in figure and '140.00' not in figure, \
                (label, totals)

    def test_the_entry_rows_are_the_documents_own_currency(self, printed):
        """The line items were always right; they are checked so a change that
        made the totals right by making the lines wrong cannot pass.

        `number-cell` is the entry columns' class; a total's is
        `total-number-cell`, so this reads the lines and nothing else.
        """
        lines = _entry_cells(printed)

        assert lines, printed
        for figure in lines:
            assert 'C$' not in figure, (figure, lines)

    def test_the_total_is_the_hundred_dollars_the_document_is_for(self,
                                                                 printed):
        """`Total Price`, not `Amount Due`: this invoice has been settled, and
        what remains due after a payment is the one figure the versions read
        differently (see the module docstring)."""
        totals = _totals(printed)

        assert totals.get('Total Price') == '$100.00', totals


BILL_LEDGER = str(FIXTURES / 'fx_bill_usd_overpaid_from_usd_bank.txt')


@pytest.fixture
def printed_bill(tmp_path):
    """The bill side of the same defect: a USD bill on CAD expense accounts."""
    runner = CliRunner()
    book = tmp_path / 'bills.gnucash'
    built = runner.invoke(cli, ['import', '--new', str(book), BILL_LEDGER,
                                '--include-business-objects',
                                '--fx-rates', RATES])
    assert built.exit_code == 0, built.output

    listed = runner.invoke(cli, ['export', str(book), str(tmp_path / 'e.txt'),
                                 '--include-business-objects'])
    assert listed.exit_code == 0, listed.output
    import re
    bill_id = re.search(r'bill "([^"]+)"',
                        (tmp_path / 'e.txt').read_text()).group(1)

    out = tmp_path / 'bill.html'
    result = runner.invoke(cli, ['print-bill', str(book), bill_id,
                                 '--format', 'html', '-o', str(out)])
    assert result.exit_code == 0, result.output
    return out.read_text(), bill_id


class TestAUsdBillWhoseExpenseAccountIsCad:
    """`bill_renderer.py` summed the posting the same way, so the vendor's
    document showed the book's valuation of what is owed rather than the
    figure the vendor invoiced."""

    def test_every_total_is_in_the_bills_own_currency(self, printed_bill):
        html, bill_id = printed_bill
        totals = _totals(html)

        # The bill is 100.00 USD, and 140.00 is what the book values that at
        # in CAD. Nothing on a document addressed to a US vendor says CAD.
        assert totals, (bill_id, html)
        for label, figure in totals.items():
            assert 'C$' not in figure and '140.00' not in figure, \
                (bill_id, label, totals)

    def test_the_total_is_the_hundred_dollars_owed(self, printed_bill):
        html, bill_id = printed_bill
        cells = _money_cells(html)

        assert any('100.00' in c for c in cells), (bill_id, cells)
