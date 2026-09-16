"""A printed invoice states its tax rate as the tax table stores it.

A whole-number rate is printed with one decimal, `5.0`, and a rate that already
has decimals with the ones it has, `9.975`, rather than with a `.0` added after
them. An invoice that is not posted has no posted lot to read a payment from,
so its page says it has none.
"""

import pytest
from click.testing import CliRunner

from cli.main import cli

FIXTURE = 'tests/fixtures/two_invoices_taxed_at_a_rate_with_three_decimals.txt'


@pytest.fixture
def book(tmp_path):
    gnc = tmp_path / 'book.gnucash'
    made = CliRunner().invoke(cli, ['import', '--new', str(gnc), FIXTURE,
                                    '--include-business-objects'])
    assert made.exit_code == 0, made.output
    return gnc


def _page(book, invoice_id):
    printed = CliRunner().invoke(cli, ['print-invoice', str(book), invoice_id,
                                       '--format', 'plaintext', '-o', '-'])
    assert printed.exit_code == 0, printed.output
    return printed.output


@pytest.mark.parametrize('invoice_id', ['INV-QST-POSTED', 'INV-QST-DRAFT'])
def test_the_rate_keeps_its_decimals(book, invoice_id):
    page = _page(book, invoice_id)

    assert '9.975' in page, page
    assert '9.975.0' not in page, page


def test_a_draft_says_it_has_no_payment(book):
    page = _page(book, 'INV-QST-DRAFT')

    assert '\tpayment: none' in page, page
