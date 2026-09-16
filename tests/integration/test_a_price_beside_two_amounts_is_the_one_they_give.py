"""A split stating both amounts has the price they give, and a price stated beside them that differs is warned about.

GnuCash's transfer dialog takes one amount and then either the rate or the
other amount, never all three. A file can state all three: the export writes
`share_price:` beside `value:` as information, the price the two amounts give.
Where a file's price is not that one, the two amounts decide and the import
says so.

Measured on 5.10 before: a new transaction stating 45.00 USD, `value: "63.23"`
and `share_price: "1.5"` stored 6323/4500 with nothing said, and the same
block read with `--strategy update` stored the stated price instead. The
value became 67.50, GnuCash added `Imbalance-CAD -4.27`, and the run said
`Errors: 0`.
"""

import re
from pathlib import Path

from click.testing import CliRunner

from cli.main import cli

HOTEL = 'tests/fixtures/a_usd_hotel_paid_from_the_cad_bank.txt'
AGREEING = 'share_price: "6323/4500"'
WARNED = 'the price is the one the two amounts give'


def _run(*args):
    return CliRunner().invoke(cli, [str(arg) for arg in args])


def _with_price(tmp_path, price, name='ledger.txt'):
    text = Path(HOTEL).read_text()
    assert AGREEING in text, text
    ledger = tmp_path / name
    ledger.write_text(text.replace(AGREEING, f'share_price: "{price}"'))
    return ledger


def _the_hotel(book, tmp_path):
    out = tmp_path / 'out.txt'
    assert _run('export', book, out).exit_code == 0
    return re.search(r'2026-01-10 \* "Hotel in USD"[^\n]*\n(?:\t[^\n]*\n)*',
                     out.read_text()).group(0)


def test_a_new_transaction_warns_and_takes_the_price_the_amounts_give(tmp_path):
    book = tmp_path / 'book.gnucash'

    made = _run('import', '--new', book, _with_price(tmp_path, '1.5'))

    assert made.exit_code == 0, made.output
    assert WARNED in made.output, made.output
    hotel = _the_hotel(book, tmp_path)
    assert AGREEING in hotel, hotel
    assert 'value: "63.23"' in hotel, hotel


def test_an_update_warns_and_keeps_the_two_amounts(tmp_path):
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, HOTEL).exit_code == 0

    updated = _run('import', book, _with_price(tmp_path, '1.5'), '--strategy', 'update')

    assert updated.exit_code == 0, updated.output
    assert WARNED in updated.output, updated.output
    hotel = _the_hotel(book, tmp_path)
    assert 'value: "63.23"' in hotel, hotel
    assert AGREEING in hotel, hotel
    assert 'Imbalance' not in hotel, hotel


def test_an_update_stating_a_price_and_no_value_values_the_split_at_it(tmp_path):
    """One amount and the price, as the transfer dialog takes them: the value is the amount times the price."""
    book = tmp_path / 'book.gnucash'
    assert _run('import', '--new', book, HOTEL).exit_code == 0
    text = Path(HOTEL).read_text()
    for written in (AGREEING, '\t\tvalue: "63.23"\n', '\tAssets:Bank -63.23 CAD\n',
                    '\t\tvalue: "-63.23"\n'):
        assert written in text, text
    ledger = tmp_path / 'priced.txt'
    ledger.write_text(text.replace(AGREEING, 'share_price: "1.5"')
                      .replace('\t\tvalue: "63.23"\n', '')
                      .replace('\tAssets:Bank -63.23 CAD\n', '\tAssets:Bank -67.50 CAD\n')
                      .replace('\t\tvalue: "-63.23"\n', '\t\tvalue: "-67.50"\n'))

    updated = _run('import', book, ledger, '--strategy', 'update')

    assert updated.exit_code == 0, updated.output
    assert WARNED not in updated.output, updated.output
    hotel = _the_hotel(book, tmp_path)
    assert 'value: "67.50"' in hotel, hotel
    assert 'Imbalance' not in hotel, hotel


def test_a_price_the_amounts_give_says_nothing(tmp_path):
    made = _run('import', '--new', tmp_path / 'book.gnucash', HOTEL)

    assert made.exit_code == 0, made.output
    assert WARNED not in made.output, made.output
