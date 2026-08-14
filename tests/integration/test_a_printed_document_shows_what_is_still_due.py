"""What a printed document says is owed, after what has been paid on it.

GnuCash's Printable Invoice lists each payment as a row of its own and ends on
`Amount Due` — the total less those payments. So a fully paid invoice prints
zero due with its payment above it, and a part-paid one prints the remainder.
Neither is dropped and neither is drawn as unpaid.

Both documents here are CAD in a CAD book, paid from a CAD bank, so what is
asserted is the arithmetic and not a currency conversion — the version
difference in how a *cross-currency* payment is stated belongs to
`test_a_printed_document_totals_in_its_own_currency`, which measures it.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURES = Path('tests/fixtures')
LEDGER = str(FIXTURES / 'business_objects.txt')


def _totals(html: str) -> dict:
    """The report's labelled total rows, `{'Amount Due': 'C$0.00', …}`."""
    return {label.strip(): figure.strip() for label, figure in re.findall(
        r'total-label-cell"[^>]*>(.*?)</td>\s*'
        r'<td class="total-number-cell"[^>]*>(.*?)</td>', html, re.S)}


@pytest.fixture
def book(tmp_path):
    path = tmp_path / 'book.gnucash'
    built = CliRunner().invoke(cli, ['import', '--new', str(path), LEDGER,
                                     '--include-business-objects'])
    assert built.exit_code == 0, built.output
    return path


def _printed(book, tmp_path, invoice_id):
    out = tmp_path / f'{invoice_id}.html'
    result = CliRunner().invoke(cli, [
        'print-invoice', str(book), invoice_id, '--format', 'html',
        '--output', str(out)])
    assert result.exit_code == 0, result.output
    return out.read_text()


class TestAnInvoicePaidInFull:
    """INV-2026-003: 200.00 plus 5% GST, settled with one payment of 210.00."""

    @pytest.fixture
    def printed(self, book, tmp_path):
        return _printed(book, tmp_path, 'INV-2026-003')

    def test_the_total_is_what_it_was_for(self, printed):
        assert _totals(printed).get('Total Price') == 'C$210.00', \
            _totals(printed)

    def test_nothing_is_still_due(self, printed):
        assert _totals(printed).get('Amount Due') == 'C$0.00', _totals(printed)

    def test_the_payment_is_on_the_page(self, printed):
        """Listed, not merely subtracted — the customer can see it landed."""
        assert 'C$210.00' in printed
        assert 'Payment' in printed, printed


class TestAnInvoicePaidInPart:
    """INV-2026-004: 3 × 100.00 plus 5% GST = 315.00, with 200.00 paid."""

    @pytest.fixture
    def printed(self, book, tmp_path):
        return _printed(book, tmp_path, 'INV-2026-004')

    def test_the_total_is_what_it_was_for(self, printed):
        assert _totals(printed).get('Total Price') == 'C$315.00', \
            _totals(printed)

    def test_what_is_left_is_still_due(self, printed):
        assert _totals(printed).get('Amount Due') == 'C$115.00', \
            _totals(printed)
