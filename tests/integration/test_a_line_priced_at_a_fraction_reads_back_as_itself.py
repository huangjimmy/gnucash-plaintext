"""A line priced at a fraction reads back as itself.

The export writes a figure no decimal says exactly as the fraction it is:
`price: 100/3`. Three of that line total 100.00, which the receivable holds,
and reading the export back into the same book changes nothing.
"""

import re
from fractions import Fraction
from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

ACCOUNTS = 'tests/fixtures/payment_roundtrip_accounts.txt'
THIRD = 'tests/fixtures/an_invoice_line_priced_at_a_third.txt'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


@pytest.mark.parametrize('key, stated', [
    ('price', '33.3333333'),
    ('quantity', '1.2345678'),
    ('price', '12345.678901234567'),
], ids=['price', 'quantity', 'price-with-seventeen-digits'])
def test_a_figure_with_more_decimals_is_kept_as_written(tmp_path, key, stated):
    """A price or a quantity is a ratio, not money, and is held as the file states it.

    Measured on 5.10 before: the line's figures were read at six decimals and
    the rest dropped, so `price: 33.3333333` was stored as 33333333/1000000 and
    the export wrote `price: 33.333333`, a figure the file never stated.
    """
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, ACCOUNTS).exit_code == 0
    text = Path(THIRD).read_text()
    written = {'price': '\t\tprice: 100/3\n', 'quantity': '\t\tquantity: 3\n'}[key]
    assert written in text, text
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(text.replace(written, f'\t\t{key}: {stated}\n'))
    made = _run('import', book, ledger, '--include-business-objects')
    assert made.exit_code == 0, made.output

    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0

    # The same figure, whichever way the export spells it: past nine decimals
    # it writes the fraction, which states the value just as exactly.
    written_back = re.search(rf'\t\t{key}: ([^\n]+)\n', out.read_text()).group(1)
    assert Fraction(written_back) == Fraction(stated), out.read_text()


def test_a_price_gnucash_cannot_hold_exactly_is_refused(tmp_path):
    """0.1234567890123456789 is 1234567890123456789 over ten to the nineteenth.

    GnuCash keeps a figure as a 64-bit numerator over a 64-bit denominator, and
    that denominator does not fit, so no book can hold this price. It is
    refused rather than rounded to one that fits. Measured on 5.10 before: read
    through a float it was stored as 0.12345678901234568; read exactly, the
    binding refused it with an error about `gint64`.
    """
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, ACCOUNTS).exit_code == 0
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(Path(THIRD).read_text().replace(
        '\t\tprice: 100/3\n', '\t\tprice: 0.1234567890123456789\n'))

    made = _run('import', book, ledger, '--include-business-objects')

    assert made.exit_code != 0, made.output
    assert '0.1234567890123456789 cannot be held exactly' in made.output, made.output
    assert 'gint64' not in made.output, made.output


def test_the_export_writes_the_fraction_and_reads_back_unchanged(tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, ACCOUNTS).exit_code == 0
    made = _run('import', book, THIRD, '--include-business-objects')
    assert made.exit_code == 0, made.output
    out = tmp_path / 'out.txt'
    assert _run('export', book, out, '--include-business-objects').exit_code == 0
    text = out.read_text()
    assert 'price: 100/3' in text, text
    assert 'Assets:Accounts Receivable 100.00 CAD' in text, text

    again = _run('import', book, out, '--include-business-objects')

    assert again.exit_code == 0, again.output
    assert 'invoice "INV-THIRD": unchanged' in again.output, again.output
