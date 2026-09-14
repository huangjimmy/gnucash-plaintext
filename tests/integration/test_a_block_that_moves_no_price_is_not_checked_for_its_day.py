"""A block that puts no price on a day is not checked against that day.

README, "One price a day": `import` refuses a block that would put a second
price of a commodity and a currency on one local day. Only a new price, or an
edit that changes a price's `time:`, puts a price on a day. A block that
changes nothing, or an edit that leaves `time:` as it is, puts none.

The difference shows when a book already holds two prices of one pair on one
local day of the machine importing. GnuCash keeps one price a day on the local
day of the machine that adds the price, so two prices added in Toronto on two
days stay two when the book is opened where both fall on one day. Here the
book is built in a child process under TZ=America/Toronto, and everything
after it runs in this process, whose local day is UTC's in the test images.
"""

import os
import re
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

from click.testing import CliRunner

from tests.conftest import _run
from tests.integration.prices_in_a_book import prices_in, utc

FIXTURES = Path('tests/fixtures')
FIRST_GUID = '6d1e5a4f2b3c4d5e8f9a0b1c2d3e4f5a'
SECOND_GUID = '7e2f6b5a3c4d5e6f9a0b1c2d3e4f5a6b'


def _book_built_in_toronto(tmp_path):
    book = tmp_path / 'book.gnucash'
    done = subprocess.run(
        [sys.executable, '-c', 'from cli.main import cli; cli()', 'import', '--new', str(book),
         str(FIXTURES / 'two_amzn_prices_a_day_apart_in_toronto_on_one_utc_day.txt')],
        env={**os.environ, 'TZ': 'America/Toronto'}, capture_output=True, check=False)
    assert done.returncode == 0, (done.stdout + done.stderr).decode('utf-8', 'replace')
    return book


def _amzn(book):
    return [p for p in prices_in(book) if p.commodity == 'NASDAQ:AMZN']


class TestABookHoldingTwoPricesOnOneDayOfThisProcess:
    def test_the_book_holds_both_on_one_day_here(self, tmp_path):
        """What the tests below stand on: GnuCash kept both, and this process puts them on one day."""
        book = _book_built_in_toronto(tmp_path)

        prices = _amzn(book)

        assert [(p.guid, p.time) for p in prices] == [
            (FIRST_GUID, utc(2026, 1, 6, 4, 59, 59)),
            (SECOND_GUID, utc(2026, 1, 6, 10, 59)),
        ]
        assert len({time.localtime(p.time)[:3] for p in prices}) == 1, (
            f'TZ={os.environ.get("TZ")!r} puts the two prices on two days, so the tests '
            f'in this file prove nothing here; they need a timezone where 04:59:59 and '
            f'10:59 UTC on 2026-01-06 are one day, as UTC is')

    def test_its_own_export_imports_back_unchanged(self, tmp_path):
        book = _book_built_in_toronto(tmp_path)
        ledger = tmp_path / 'ledger.txt'
        exported = _run(CliRunner(), 'export', str(book), str(ledger), '--include-prices')
        assert exported.exit_code == 0, exported.output

        result = _run(CliRunner(), 'import', str(book), str(ledger))

        assert result.exit_code == 0, result.output
        assert re.search(r'Prices:\s+0 created, 0 updated, 2 unchanged, 0 refused',
                         result.output), result.output

    def test_a_value_corrected_on_one_of_them_is_updated(self, tmp_path):
        book = _book_built_in_toronto(tmp_path)

        result = _run(CliRunner(), 'import', str(book),
                      str(FIXTURES / 'the_first_amzn_price_on_that_utc_day_with_its_value_corrected.txt'))

        assert result.exit_code == 0, result.output
        assert re.search(r'Prices:\s+0 created, 1 updated, 0 unchanged, 0 refused',
                         result.output), result.output
        assert [(p.guid, p.time, p.value) for p in _amzn(book)] == [
            (FIRST_GUID, utc(2026, 1, 6, 4, 59, 59), Fraction(21600, 100)),
            (SECOND_GUID, utc(2026, 1, 6, 10, 59), Fraction(21700, 100)),
        ]
