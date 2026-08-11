"""A file still stating `cost_basis_available:` is refused, not read past.

The key was renamed to `cost_basis_balance:`. The old spelling is no longer a
reserved key, so a file carrying it would be kept as an ordinary custom key —
stored, exported again, and read by nothing.

That is the quiet failure. The balance would not be checked; the file's own
sales would not be counted as already applied; and the basis would be opened
at everything it brought in. A file recording that 40.00 of a 100.00 USD basis
had been sold would re-open all 100.00, with `Errors: 0`. It happens to net
out when the sale is in the same file, which is exactly why it would go
unnoticed — `export --start-date` produces files where it is not.

Refused by name instead, which is the one shape that cannot go quiet.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from cli.main import cli

LEDGER = """\
2026-01-01 commodity CAD
\tmnemonic: "CAD"
\tfullname: "Canadian Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 commodity USD
\tmnemonic: "USD"
\tfullname: "US Dollar"
\tnamespace: "CURRENCY"
\tfraction: 100
2026-01-01 open Assets
\ttype: Asset
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "CAD"
2026-01-01 open Assets:Bank:USD
\ttype: Bank
\tcommodity.namespace: "CURRENCY"
\tcommodity.mnemonic: "USD"

2026-01-10 * "Buy 100 USD at 1.35"
\tcurrency.mnemonic: "CAD"
\tAssets:Bank:USD 100.00 USD
\t\taccount.commodity.mnemonic: "USD"
\t\tshare_price: "1.35"
\t\tvalue: "135.00"
\t\t{key}: "60.00"
\tAssets:Bank -135.00 CAD
"""


def _import(tmp_path, key: str):
    book = tmp_path / 'book.gnucash'
    ledger = tmp_path / 'ledger.txt'
    ledger.write_text(LEDGER.format(key=key))
    return CliRunner().invoke(cli, ['import', '--new', str(book), str(ledger)])


class TestTheOldKey:
    def test_it_is_refused(self, tmp_path):
        result = _import(tmp_path, 'cost_basis_available')

        assert result.exit_code != 0, result.output

    def test_it_names_the_key_to_use_instead(self, tmp_path):
        result = _import(tmp_path, 'cost_basis_available')

        assert 'cost_basis_balance' in result.output, result.output

    def test_it_says_what_reading_past_it_would_cost(self, tmp_path):
        """A reader who does not know why should not have to guess."""
        result = _import(tmp_path, 'cost_basis_available')

        assert 'sold' in result.output, result.output


class TestTheNewKey:
    def test_it_is_accepted(self, tmp_path):
        result = _import(tmp_path, 'cost_basis_balance')

        assert result.exit_code == 0, result.output
