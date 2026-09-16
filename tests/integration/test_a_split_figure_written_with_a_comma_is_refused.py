"""A split's `value:` or `share_price:` written with a comma is refused, never read as a point.

A figure in this format is written with a point, and the export writes every
one that way. In most of the world a comma separates thousands, so `1,350` is
one thousand three hundred and fifty. The reader turned every comma into a
point: 1000.00 USD bought for `value: "1,350"` CAD was booked at 1.35 CAD, a
rate of 0.00135, and GnuCash put the other 1348.65 CAD in Imbalance-CAD, with
`Errors: 0`. So a comma is refused, as `cost_basis_balance: "60,00"` already
is (`docs/multi-currency.md`).
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

BOUGHT = 'tests/fixtures/a_thousand_usd_bought_for_cad.txt'


@pytest.mark.parametrize('old, new, figure', [
    ('\t\tvalue: "1350.00"\n', '\t\tvalue: "1,350"\n', '1,350'),
    ('\t\tshare_price: "1.35"\n', '\t\tshare_price: "1,35"\n', '1,35'),
], ids=['value-with-a-thousands-comma', 'share-price-with-a-decimal-comma'])
def test_it_is_refused_and_nothing_is_booked(tmp_path, old, new, figure):
    text = Path(BOUGHT).read_text()
    assert old in text, text
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(text.replace(old, new))
    book = tmp_path / 'book.gnucash'

    result = CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger)])

    assert f"must be a number, got '{figure}'" in result.output, result.output
    assert 'Errors:       1' in result.output, result.output
    if book.exists():
        out = tmp_path / 'out.txt'
        exported = CliRunner().invoke(cli, ['export', str(book), str(out)])
        assert exported.exit_code == 0, exported.output
        assert 'Imbalance' not in out.read_text(), out.read_text()
        assert 'Buy 1000 USD' not in out.read_text(), out.read_text()
